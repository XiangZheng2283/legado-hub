"""Plugin scheduler: execute plugins concurrently from LegadoHub core."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from app.source_plugins.loader import PluginLoader
from app.source_plugins.context import PluginContext
from app.source_plugins.fetcher import Fetcher
from app.source_plugins.models import (
    LoadedPlugin,
    SearchResult,
    BookDetail,
    ChapterItem,
    ChapterContent,
    PluginFailure,
)
from app.source_plugins.errors import (
    PluginExecutionError,
    PluginTimeout,
    ERROR_CODE_MAP,
    normalize_failure,
)
from app.source_plugins.id_codec import encode_book_id, encode_chapter_id
from app.services.browser_challenge import BrowserChallengeService


class PluginScheduler:
    def __init__(
        self,
        loader: PluginLoader | None = None,
        config: dict | None = None,
    ):
        self.loader = loader or PluginLoader()
        self._plugins: dict[str, LoadedPlugin] = {}
        self.config = self._default_config() if config is None else config
        self._load_plugins()

    def _default_config(self) -> dict:
        from app.config import SOURCE_POOL_CONFIG_PATH

        if not SOURCE_POOL_CONFIG_PATH.exists():
            return {}
        try:
            data = json.loads(SOURCE_POOL_CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _load_plugins(self) -> None:
        try:
            self._plugins = self.loader.load_all()
        except Exception:
            self._plugins = {}

    def reload(self) -> None:
        self._load_plugins()

    def _enabled_plugins(self) -> list[LoadedPlugin]:
        return [p for p in self._plugins.values() if p.metadata.enabled]

    def _make_fetcher(self, plugin: LoadedPlugin | None = None) -> Fetcher:
        proxy_url = ""
        proxy_cfg = self.config.get("proxy", {})
        proxy_mode = (plugin.metadata.proxy or {}).get("mode", "auto") if plugin else "auto"
        if proxy_mode != "never" and proxy_cfg.get("enabled"):
            proxy_url = proxy_cfg.get("url", "")
        return Fetcher(
            user_agent=self.config.get("default_user_agent", ""),
            timeout=self.config.get("source_timeout_seconds", 8.0),
            proxy_url=proxy_url,
        )

    def _make_ctx(self, plugin_id: str) -> PluginContext:
        from app.services.plugin_auth_repository import PluginAuthRepository
        from app.services.browser_fetch import BrowserFetchService

        auth_repository = PluginAuthRepository()
        plugin = self._plugins.get(plugin_id)
        proxy_url = self._proxy_url_for_plugin(plugin)
        ctx = PluginContext(
            fetcher=self._make_fetcher_with_cookies(plugin_id, auth_repository),
            plugin_id=plugin_id,
            auth_repository=auth_repository,
            browser_fetcher=BrowserFetchService(
                proxy_url=proxy_url,
                user_agent=self.config.get("default_user_agent", ""),
                cookies=auth_repository.get_cookies(plugin_id),
            ),
        )
        if plugin and (plugin.metadata.browser or {}).get("searchFallback") == "search_engine":
            ctx.allow_search_engine_fallback = True
        return ctx

    def _proxy_url_for_plugin(self, plugin: LoadedPlugin | None = None) -> str:
        try:
            fetcher = self._make_fetcher(plugin)
        except TypeError:
            fetcher = self._make_fetcher()
        return str(getattr(fetcher, "proxy_url", "") or "")

    def _make_fetcher_with_cookies(self, plugin_id: str, auth_repository) -> Fetcher:
        try:
            fetcher = self._make_fetcher(self._plugins.get(plugin_id))
        except TypeError:
            fetcher = self._make_fetcher()
        for domain, cookies in auth_repository.get_cookies(plugin_id).items():
            if isinstance(cookies, dict):
                for name, value in cookies.items():
                    fetcher.set_cookie(domain, name, value)
        return fetcher

    def timeout_for_plugin(self, plugin: LoadedPlugin | None = None) -> float:
        if plugin and (plugin.metadata.browser or {}).get("mode") in {"required", "optional"}:
            return float(self.config.get("browser_source_timeout_seconds", 90.0))
        return float(self.config.get("source_timeout_seconds", 8.0))

    def search_timeout_for_plugin(self, plugin: LoadedPlugin | None = None) -> float:
        if plugin and (plugin.metadata.browser or {}).get("mode") in {"required", "optional"}:
            return float(self.config.get("browser_search_timeout_seconds", 30.0))
        return float(self.config.get("source_timeout_seconds", 8.0))

    async def search(self, keyword: str, page: int = 1) -> dict:
        plugins = self._enabled_plugins()
        max_concurrency = self.config.get("max_concurrency", 6)
        overall_timeout = self.config.get("overall_search_timeout_seconds", 30.0)
        source_batch_size = self.config.get("source_batch_size", 20)

        if not plugins:
            return {
                "implemented": True,
                "keyword": keyword,
                "page": page,
                "items": [],
                "debug": {
                    "sourceCount": 0,
                    "attemptedCount": 0,
                    "successCount": 0,
                    "errorCount": 0,
                    "disabledCount": 0,
                    "timeoutCount": 0,
                    "elapsedMs": 0,
                    "errors": [],
                    "partialSuccess": False,
                },
            }

        all_items: list[dict] = []
        errors: list[dict] = []
        browser_challenges: list[dict] = []
        start_time = time.perf_counter()
        success_count = 0
        attempted_count = 0
        timeout_count = 0

        batches = [plugins[i : i + source_batch_size] for i in range(0, len(plugins), source_batch_size)]
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _search_one(plugin: LoadedPlugin) -> tuple[list[dict], dict | None]:
            if "search" not in plugin.capabilities:
                return [], None
            ctx = self._make_ctx(plugin.metadata.id)
            source_timeout = self.search_timeout_for_plugin(plugin)
            t0 = time.perf_counter()
            try:
                raw_items = await asyncio.wait_for(
                    plugin.source.search(ctx, keyword, page),
                    timeout=source_timeout,
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                items = []
                for item in raw_items or []:
                    if isinstance(item, dict):
                        item.setdefault("sourceId", plugin.metadata.id)
                        items.append(item)
                self._trace_success(ctx, plugin.metadata.id, "search", latency_ms)
                return items, None
            except asyncio.TimeoutError:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                extra: dict[str, Any] = {}
                code = "PLUGIN_TIMEOUT"
                message = "timeout"
                if (plugin.metadata.browser or {}).get("mode") in {"required", "optional"}:
                    challenge = BrowserChallengeService().create_for_plugin(
                        plugin,
                        stage="search",
                        reason="BROWSER_REQUIRED",
                        message="source timed out and may require browser verification",
                    )
                    extra["browserChallenge"] = challenge
                    extra["requiresBrowserVerification"] = True
                    code = "BROWSER_REQUIRED"
                    message = "timeout; browser verification may be required"
                err = {
                    **normalize_failure(
                        source_id=plugin.metadata.id,
                        stage="search",
                        code=code,
                        message=message,
                        url=extra.get("browserChallenge", {}).get("openUrl", ""),
                        extra=extra,
                    )
                }
                self._trace_failure(ctx, plugin.metadata.id, "search", code, message)
                return [], err
            except Exception as exc:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                err = self._failure_for_exception(plugin, "search", exc)
                self._trace_failure(ctx, plugin.metadata.id, "search", err.get("code", "PLUGIN_RUNTIME_ERROR"), str(exc))
                return [], err
            finally:
                await ctx._fetcher.close()

        for batch in batches:
            if (time.perf_counter() - start_time) >= overall_timeout:
                errors.append({"sourceId": "", "code": "PLUGIN_TIMEOUT", "stage": "search", "message": "overall timeout"})
                break

            tasks = [asyncio.create_task(_search_one(p)) for p in batch]
            attempted_count += len(batch)
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=max(0.1, overall_timeout - (time.perf_counter() - start_time)),
                )
            except asyncio.TimeoutError:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                results = []
                for task in tasks:
                    if task.done() and not task.cancelled():
                        try:
                            results.append(task.result())
                        except Exception as e:
                            results.append(([], {"sourceId": "", "code": "PLUGIN_RUNTIME_ERROR", "stage": "search", "message": str(e)}))
                    else:
                        results.append(([], {"sourceId": "", "code": "PLUGIN_TIMEOUT", "stage": "search", "message": "overall timeout"}))

            for result in results:
                if isinstance(result, Exception):
                    errors.append({"sourceId": "", "code": "PLUGIN_RUNTIME_ERROR", "stage": "search", "message": str(result)})
                    continue
                items, err = result
                if isinstance(items, Exception):
                    errors.append({"sourceId": "", "code": "PLUGIN_RUNTIME_ERROR", "stage": "search", "message": str(items)})
                    continue
                if err:
                    errors.append(err)
                    challenge = err.get("extra", {}).get("browserChallenge")
                    if challenge:
                        browser_challenges.append(challenge)
                    if err.get("code") == "PLUGIN_TIMEOUT":
                        timeout_count += 1
                if items:
                    success_count += 1
                    all_items.extend(items)

        # Merge by name+author, score, rewrite bookUrl
        merged = self._merge_search_results(all_items)
        from app.config import HOST, PORT
        base_api = f"http://{HOST}:{PORT}"
        for item in merged:
            source_id = item.get("sourceId", "")
            book_url = item.get("bookUrl", "")
            if book_url:
                book_id = encode_book_id(source_id, book_url)
                item["bookUrl"] = f"{base_api}/api/legado/book/{book_id}"

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        partial_success = success_count > 0 and len(errors) > 0

        return {
            "implemented": True,
            "keyword": keyword,
            "page": page,
            "items": merged,
            "debug": {
                "sourceCount": len(plugins),
                "batchSize": source_batch_size,
                "batchCount": len(batches),
                "attemptedCount": attempted_count,
                "successCount": success_count,
                "errorCount": len(errors),
                "disabledCount": 0,
                "timeoutCount": timeout_count,
                "elapsedMs": elapsed_ms,
                "errors": errors,
                "browserChallenges": browser_challenges,
                "partialSuccess": partial_success,
            },
        }

    async def detail(self, source_id: str, book_url: str) -> dict:
        plugin = self._plugins.get(source_id)
        if not plugin or "detail" not in plugin.capabilities:
            return {"implemented": True, "data": None, "debug": {"error": f"plugin not found or no detail capability: {source_id}"}}
        ctx = self._make_ctx(source_id)
        try:
            raw = await asyncio.wait_for(
                plugin.source.detail(ctx, book_url),
                timeout=self.timeout_for_plugin(plugin),
            )
            if isinstance(raw, dict):
                raw.setdefault("sourceId", source_id)
            else:
                raw = {"sourceId": source_id}
            return {"implemented": True, "data": raw, "debug": {}}
        except Exception as exc:
            err = self._failure_for_exception(plugin, "detail", exc)
            return {"implemented": True, "data": None, "debug": {"error": err, "browserChallenges": self._challenges_from_error(err)}}
        finally:
            await ctx._fetcher.close()

    async def toc(self, source_id: str, toc_url: str) -> dict:
        plugin = self._plugins.get(source_id)
        if not plugin or "toc" not in plugin.capabilities:
            return {"implemented": True, "bookId": "", "chapters": [], "debug": {"error": f"plugin not found or no toc capability: {source_id}"}}
        ctx = self._make_ctx(source_id)
        try:
            raw_items = await asyncio.wait_for(
                plugin.source.toc(ctx, toc_url),
                timeout=self.timeout_for_plugin(plugin),
            )
            chapters = []
            for item in raw_items or []:
                if isinstance(item, dict):
                    item.setdefault("sourceId", source_id)
                    chapters.append(item)
            # Rewrite chapter URLs
            from app.config import HOST, PORT
            base_api = f"http://{HOST}:{PORT}"
            for ch in chapters:
                ch_url = ch.get("chapterUrl", "")
                if ch_url:
                    ch_id = encode_chapter_id(source_id, ch_url)
                    ch["chapterUrl"] = f"{base_api}/api/legado/chapter/{ch_id}"
            return {"implemented": True, "bookId": "", "chapters": chapters, "debug": {}}
        except Exception as exc:
            err = self._failure_for_exception(plugin, "toc", exc)
            return {"implemented": True, "bookId": "", "chapters": [], "debug": {"error": err, "browserChallenges": self._challenges_from_error(err)}}
        finally:
            await ctx._fetcher.close()

    async def chapter(self, source_id: str, chapter_url: str) -> dict:
        plugin = self._plugins.get(source_id)
        if not plugin or "chapter" not in plugin.capabilities:
            return {"implemented": True, "chapterId": "", "title": "", "content": "", "debug": {"error": f"plugin not found or no chapter capability: {source_id}"}}
        ctx = self._make_ctx(source_id)
        try:
            raw = await asyncio.wait_for(
                plugin.source.chapter(ctx, chapter_url),
                timeout=self.timeout_for_plugin(plugin),
            )
            if isinstance(raw, dict):
                raw.setdefault("sourceId", source_id)
                return {"implemented": True, "chapterId": "", "title": raw.get("title", ""), "content": raw.get("content", ""), "debug": {}}
            return {"implemented": True, "chapterId": "", "title": "", "content": "", "debug": {}}
        except Exception as exc:
            err = self._failure_for_exception(plugin, "chapter", exc)
            return {"implemented": True, "chapterId": "", "title": "", "content": "", "debug": {"error": err, "browserChallenges": self._challenges_from_error(err)}}
        finally:
            await ctx._fetcher.close()

    async def explore_groups(self, source_id: str | None = None) -> dict:
        plugins = self._enabled_plugins()
        if source_id:
            plugin = self._plugins.get(source_id)
            plugins = [plugin] if plugin and plugin.metadata.enabled else []
        groups: list[dict] = []
        errors: list[dict] = []
        start_time = time.perf_counter()
        for plugin in plugins:
            if not plugin or "explore" not in plugin.capabilities:
                continue
            ctx = self._make_ctx(plugin.metadata.id)
            timeout = self.timeout_for_plugin(plugin)
            try:
                raw_groups = await asyncio.wait_for(plugin.source.explore_groups(ctx), timeout=timeout)
                for group in raw_groups or []:
                    if not isinstance(group, dict):
                        continue
                    group.setdefault("sourceId", plugin.metadata.id)
                    group.setdefault("sourceName", plugin.metadata.name)
                    group.setdefault("kind", "other")
                    group.setdefault("pageable", True)
                    groups.append(group)
            except asyncio.TimeoutError:
                errors.append(normalize_failure(source_id=plugin.metadata.id, stage="explore_groups", code="PLUGIN_TIMEOUT", message="timeout"))
            except Exception as exc:
                errors.append(self._failure_for_exception(plugin, "explore_groups", exc))
            finally:
                await ctx._fetcher.close()
        return {
            "implemented": True,
            "sourceId": source_id or "",
            "groups": groups,
            "debug": {
                "sourceCount": len(plugins),
                "groupCount": len(groups),
                "errorCount": len(errors),
                "elapsedMs": int((time.perf_counter() - start_time) * 1000),
                "errors": errors,
            },
        }

    async def explore(self, source_id: str, group_id: str | None = None, page: int = 1) -> dict:
        plugin = self._plugins.get(source_id)
        if not plugin or "explore" not in plugin.capabilities:
            return {
                "implemented": True,
                "sourceId": source_id,
                "groupId": group_id or "",
                "page": page,
                "items": [],
                "debug": {"error": f"plugin not found or no explore capability: {source_id}"},
            }
        ctx = self._make_ctx(source_id)
        start_time = time.perf_counter()
        try:
            raw_items = await asyncio.wait_for(
                plugin.source.explore(ctx, group_id, page),
                timeout=self.timeout_for_plugin(plugin),
            )
            items = []
            for index, item in enumerate(raw_items or [], start=1):
                if not isinstance(item, dict):
                    continue
                item.setdefault("sourceId", source_id)
                item.setdefault("sourceName", plugin.metadata.name)
                item.setdefault("groupId", group_id or "")
                item.setdefault("rank", index)
                items.append(item)
            return {
                "implemented": True,
                "sourceId": source_id,
                "groupId": group_id or "",
                "page": page,
                "items": items,
                "debug": {"elapsedMs": int((time.perf_counter() - start_time) * 1000), "errorCount": 0, "errors": []},
            }
        except asyncio.TimeoutError:
            err = normalize_failure(source_id=source_id, stage="explore", code="PLUGIN_TIMEOUT", message="timeout")
            return {"implemented": True, "sourceId": source_id, "groupId": group_id or "", "page": page, "items": [], "debug": {"error": err, "errors": [err]}}
        except Exception as exc:
            err = self._failure_for_exception(plugin, "explore", exc)
            return {"implemented": True, "sourceId": source_id, "groupId": group_id or "", "page": page, "items": [], "debug": {"error": err, "errors": [err], "browserChallenges": self._challenges_from_error(err)}}
        finally:
            await ctx._fetcher.close()

    async def smoke(self, plugin_id: str, keyword: str = "凡人修仙传") -> dict:
        from app.source_plugins.smoke import run_fixture_smoke, run_smoke
        from app.services.plugin_health_repository import PluginHealthRepository
        plugin = self._plugins.get(plugin_id)
        if not plugin:
            return {"pass": False, "error": f"plugin not found: {plugin_id}"}
        plugin_dir = self.loader.plugins_dir / plugin_id
        if (plugin_dir / "tests" / "smoke.yaml").exists():
            result = await run_fixture_smoke(plugin, plugin_dir, keyword)
        else:
            ctx = self._make_ctx(plugin_id)
            try:
                result = await run_smoke(plugin, ctx, keyword)
            finally:
                await ctx._fetcher.close()
        repo = PluginHealthRepository()
        repo.ensure_plugin(plugin_id, plugin.metadata.name, plugin.metadata.enabled)
        repo.update_test_result(plugin_id, result)
        if result.get("pass"):
            repo.record_success(plugin_id, result.get("stages", {}).get("search", {}).get("elapsedMs", 0))
        else:
            first_error = (result.get("errors") or [{"message": "smoke failed"}])[0]
            repo.record_failure(plugin_id, first_error.get("stage", "smoke"), first_error.get("message", "smoke failed"))
        return result

    def _merge_search_results(self, items: list[dict]) -> list[dict]:
        groups: dict[tuple[str, str], list[dict]] = {}
        for item in items:
            key = (item.get("name", "").strip(), item.get("author", "").strip())
            groups.setdefault(key, []).append(item)
        merged: list[dict] = []
        for key, group_items in groups.items():
            if len(group_items) == 1:
                merged.append(group_items[0])
                continue
            best = max(group_items, key=lambda x: x.get("score", 0))
            sources_info = ", ".join(
                f"{g.get('sourceId','')}" for g in group_items
            )
            best = dict(best)
            intro = best.get("intro", "")
            best["intro"] = f"{intro} [来源: {sources_info}]" if intro else f"[来源: {sources_info}]"
            merged.append(best)
        return merged

    def _trace_success(self, ctx: PluginContext, plugin_id: str, stage: str, latency_ms: int) -> None:
        ctx.trace(stage, message=f"success {latency_ms}ms")

    def _trace_failure(self, ctx: PluginContext, plugin_id: str, stage: str, code: str, message: str) -> None:
        ctx.trace(stage, message=f"failure {code}: {message}")

    def _failure_for_exception(self, plugin: LoadedPlugin, stage: str, exc: Exception) -> dict:
        code = getattr(exc, "code", "PLUGIN_RUNTIME_ERROR")
        url = getattr(exc, "url", "") or ""
        extra: dict[str, Any] = {}
        if code in {"CLOUDFLARE_REQUIRED", "BROWSER_REQUIRED"}:
            challenge = BrowserChallengeService().create_for_plugin(
                plugin,
                stage=stage,
                url=url,
                reason=code,
                message=str(exc),
            )
            extra["browserChallenge"] = challenge
            extra["requiresBrowserVerification"] = True
        if getattr(exc, "status_code", None):
            extra["statusCode"] = getattr(exc, "status_code")
        return normalize_failure(
            source_id=plugin.metadata.id,
            stage=stage,
            code=code,
            message=str(exc),
            url=url,
            extra=extra,
        )

    def _challenges_from_error(self, err: dict) -> list[dict]:
        challenge = err.get("extra", {}).get("browserChallenge") if isinstance(err, dict) else None
        return [challenge] if challenge else []
