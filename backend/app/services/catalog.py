"""Concurrent search across enabled plugins with batched execution, failure recording, and proxy fallback."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from app.config import HOST, PORT, SOURCE_POOL_CONFIG_PATH
from app.core.proxy import ProxyConfig
from app.source_plugins.id_codec import decode_book_id, decode_chapter_id, encode_book_id, encode_chapter_id
from app.services.cache import Cache
from app.source_plugins.scheduler import PluginScheduler
from app.services.plugin_health_repository import PluginHealthRepository


class Catalog:
    def __init__(self, repo: PluginHealthRepository | None = None, cache: Cache | None = None):
        self.repo = repo or PluginHealthRepository()
        self.cache = cache or Cache()
        self.scheduler = PluginScheduler(config=self._get_search_config())

    def _get_proxy_config(self) -> ProxyConfig:
        import json as _json
        pool_path = SOURCE_POOL_CONFIG_PATH
        if pool_path.exists():
            data = _json.loads(pool_path.read_text(encoding="utf-8"))
            return ProxyConfig.from_dict(data.get("proxy", {}))
        return ProxyConfig()

    def _get_search_config(self) -> dict:
        import json as _json
        pool_path = SOURCE_POOL_CONFIG_PATH
        if pool_path.exists():
            return _json.loads(pool_path.read_text(encoding="utf-8"))
        return {}

    def _record_attempt(
        self,
        source_id: str,
        stage: str,
        url: str,
        proxy_used: bool,
        success: bool,
        latency_ms: int,
        error: str = "",
    ) -> None:
        self.repo.record_attempt(
            source_id=source_id,
            stage=stage,
            url=url,
            direct_status="success" if success and not proxy_used else ("failed" if not proxy_used else "-"),
            proxy_status="success" if success and proxy_used else ("failed" if proxy_used else "-"),
            proxy_used=proxy_used,
            latency_ms=latency_ms,
            error=error,
        )

    async def search(
        self,
        keyword: str,
        page: int = 1,
    ) -> dict:
        cached = self.cache.get_search(keyword, page)
        if cached is not None:
            return cached

        result = await self.scheduler.search(keyword, page)

        # Convert plugin result dicts to SearchResultItem shape for cache consistency
        # and ensure bookId / sourceName are present
        items = result.get("items", [])
        for item in items:
            if "bookId" not in item and item.get("bookUrl"):
                # extract original url from bookUrl if it's a local api url
                # otherwise use bookUrl directly
                book_url = item.get("bookUrl", "")
                source_id = item.get("sourceId", "")
                item["bookId"] = encode_book_id(source_id, book_url)
            if "sourceName" not in item:
                plugin = self.scheduler._plugins.get(item.get("sourceId", ""))
                item["sourceName"] = plugin.metadata.name if plugin else item.get("sourceId", "")

        # Ensure debug fields exist for old clients
        debug = result.get("debug", {})
        debug.setdefault("disabledCount", 0)

        response = {
            "implemented": True,
            "keyword": keyword,
            "page": page,
            "items": items,
            "debug": debug,
        }

        self.cache.set_search(keyword, page, response)
        return response

    async def explore(self, source_id: str = "", group_id: str = "", page: int = 1) -> dict:
        """Reading-compatible discover/explore endpoint.

        If source_id is omitted, collect the first explore group from every
        enabled plugin that supports explore. If group_id is omitted for a
        source, use that source's first declared group.
        """
        if source_id:
            return await self._explore_one(source_id, group_id, page)

        groups_result = await self.scheduler.explore_groups()
        items: list[dict] = []
        errors: list[dict] = []
        seen_sources: set[str] = set()
        for group in groups_result.get("groups", []):
            sid = group.get("sourceId", "")
            if not sid or sid in seen_sources:
                continue
            seen_sources.add(sid)
            result = await self.scheduler.explore(sid, group.get("groupId", ""), page)
            items.extend(self._normalize_explore_items(result.get("items", [])))
            errors.extend(result.get("debug", {}).get("errors", []))

        return {
            "implemented": True,
            "sourceId": "",
            "groupId": group_id,
            "page": page,
            "items": items,
            "debug": {
                "sourceCount": len(seen_sources),
                "itemCount": len(items),
                "errors": errors,
                "browserChallenges": [
                    err.get("extra", {}).get("browserChallenge")
                    for err in errors
                    if err.get("extra", {}).get("browserChallenge")
                ],
            },
        }

    async def _explore_one(self, source_id: str, group_id: str = "", page: int = 1) -> dict:
        actual_group_id = group_id
        if not actual_group_id:
            groups = await self.scheduler.explore_groups(source_id)
            first = (groups.get("groups") or [{}])[0]
            actual_group_id = first.get("groupId", "")
        result = await self.scheduler.explore(source_id, actual_group_id, page)
        result["items"] = self._normalize_explore_items(result.get("items", []))
        return result

    def _normalize_explore_items(self, items: list[dict]) -> list[dict]:
        from app.config import HOST, PORT

        base_api = f"http://{HOST}:{PORT}"
        normalized: list[dict] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            out = dict(item)
            source_id = out.get("sourceId", "")
            raw_book_url = out.get("bookUrl", "")
            if raw_book_url and "/api/legado/book/" not in raw_book_url:
                book_id = encode_book_id(source_id, raw_book_url)
                out["rawBookUrl"] = raw_book_url
                out["bookUrl"] = f"{base_api}/api/legado/book/{book_id}"
            normalized.append(out)
        return normalized

    async def stream_search(self, keyword: str, page: int = 1, max_sources_override: int | None = None):
        """Yield console search progress events as dictionaries."""
        config = self._get_search_config()
        max_concurrency = config.get("max_concurrency", 6)
        source_batch_size = config.get("source_batch_size", 20)
        overall_timeout = config.get("overall_search_timeout_seconds", 30.0)
        max_sources = max_sources_override if max_sources_override is not None else config.get("max_sources_per_search", 200)
        proxy_config = self._get_proxy_config()
        plugins = self.scheduler._enabled_plugins()
        if max_sources is not None:
            plugins = plugins[:max_sources]

        source_batch_size = int(source_batch_size) if source_batch_size else 20
        if source_batch_size <= 0:
            source_batch_size = 20
        batches = [plugins[i : i + source_batch_size] for i in range(0, len(plugins), source_batch_size)]
        start_time = time.perf_counter()
        all_items: list[dict] = []
        errors: list[dict] = []
        success_count = 0
        completed_count = 0
        timeout_count = 0

        yield {
            "type": "summary",
            "keyword": keyword,
            "page": page,
            "sourceCount": len(plugins),
            "batchSize": source_batch_size,
            "batchCount": len(batches),
            "maxConcurrency": max_concurrency,
            "overallTimeoutSeconds": overall_timeout,
        }

        if not plugins:
            yield {
                "type": "done",
                "items": [],
                "debug": {
                    "sourceCount": 0,
                    "attemptedCount": 0,
                    "successCount": 0,
                    "errorCount": 0,
                    "timeoutCount": 0,
                    "elapsedMs": 0,
                    "partialSuccess": False,
                },
            }
            return

        async def _search_one(plugin) -> dict:
            sid = plugin.metadata.id
            if "search" not in plugin.capabilities:
                return {"source": {"sourceId": sid, "bookSourceName": plugin.metadata.name}, "items": [], "error": None, "latencyMs": 0, "proxyUsed": False}
            ctx = self.scheduler._make_ctx(sid)
            source_timeout = self.scheduler.search_timeout_for_plugin(plugin)
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
                        item.setdefault("sourceId", sid)
                        item.setdefault("sourceName", plugin.metadata.name)
                        if "bookId" not in item and item.get("bookUrl"):
                            item["bookId"] = encode_book_id(sid, item["bookUrl"])
                        items.append(item)
                self._record_attempt(sid, "search", "", False, True, latency_ms)
                self.repo.record_success(sid, latency_ms)
                return {"source": {"sourceId": sid, "bookSourceName": plugin.metadata.name}, "items": items, "error": None, "latencyMs": latency_ms, "proxyUsed": False}
            except asyncio.TimeoutError:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._record_attempt(sid, "search", "", False, False, latency_ms, "timeout")
                err = {"sourceId": sid, "stage": "search", "url": "", "proxyUsed": False, "error": "timeout"}
                return {"source": {"sourceId": sid, "bookSourceName": plugin.metadata.name}, "items": [], "error": err, "latencyMs": latency_ms, "proxyUsed": False}
            except Exception as exc:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._record_attempt(sid, "search", "", False, False, latency_ms, str(exc))
                err = {"sourceId": sid, "stage": "search", "url": "", "proxyUsed": False, "error": str(exc)}
                return {"source": {"sourceId": sid, "bookSourceName": plugin.metadata.name}, "items": [], "error": err, "latencyMs": latency_ms, "proxyUsed": False}
            finally:
                await ctx._fetcher.close()

        for batch_index, batch in enumerate(batches, start=1):
            elapsed = time.perf_counter() - start_time
            if elapsed >= overall_timeout:
                errors.append({"sourceId": "", "stage": "search", "url": "", "error": "overall timeout"})
                yield {"type": "overall_timeout", "elapsedMs": int(elapsed * 1000)}
                break

            for plugin in batch:
                yield {
                    "type": "source_start",
                    "batchIndex": batch_index,
                    "sourceId": plugin.metadata.id,
                    "sourceName": plugin.metadata.name,
                    "proxyMode": "auto",
                }

            tasks = [asyncio.create_task(_search_one(p)) for p in batch]
            pending = set(tasks)
            while pending:
                remaining_timeout = max(0.1, overall_timeout - (time.perf_counter() - start_time))
                done, pending = await asyncio.wait(pending, timeout=remaining_timeout, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    timeout_count += len(pending)
                    errors.append({"sourceId": "", "stage": "search", "url": "", "error": "overall timeout"})
                    yield {"type": "overall_timeout", "elapsedMs": int((time.perf_counter() - start_time) * 1000)}
                    pending = set()
                    break

                for task in done:
                    result = task.result()
                    src = result["source"]
                    items = result["items"]
                    err = result["error"]
                    completed_count += 1
                    if err:
                        errors.append(err)
                        if "timeout" in str(err.get("error", "")).lower():
                            timeout_count += 1
                    if items:
                        success_count += 1
                        for item in items:
                            score = 0
                            if keyword.lower() in item.get("name", "").lower():
                                score += 100
                            if item.get("author"):
                                score += 10
                            if item.get("lastChapter"):
                                score += 5
                            if item.get("intro"):
                                score += 3
                            item["score"] = score
                        all_items.extend(items)

                    yield {
                        "type": "source_done",
                        "sourceId": src["sourceId"],
                        "sourceName": src.get("bookSourceName") or src["sourceId"],
                        "status": "error" if err else "success",
                        "resultCount": len(items),
                        "latencyMs": result["latencyMs"],
                        "proxyUsed": result["proxyUsed"],
                        "error": err,
                        "completedCount": completed_count,
                        "sourceCount": len(plugins),
                    }
                    for item in items:
                        yield {
                            "type": "result",
                            "item": item,
                            "sourceId": src["sourceId"],
                            "sourceName": src.get("bookSourceName") or src["sourceId"],
                        }

            yield {
                "type": "batch_done",
                "batchIndex": batch_index,
                "completedCount": completed_count,
                "sourceCount": len(plugins),
            }

        merged = self._merge_results(all_items)
        merged.sort(key=lambda x: (-x.get("score", 0), x.get("name", "")))
        base_api = f"http://{HOST}:{PORT}"
        for item in merged:
            if item.get("bookUrl"):
                item["bookUrl"] = f"{base_api}/api/legado/book/{item['bookId']}"

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        response = {
            "implemented": True,
            "keyword": keyword,
            "page": page,
            "items": merged,
            "debug": {
                "sourceCount": len(plugins),
                "batchSize": source_batch_size,
                "batchCount": len(batches),
                "attemptedCount": completed_count,
                "successCount": success_count,
                "errorCount": len(errors),
                "disabledCount": 0,
                "timeoutCount": timeout_count,
                "elapsedMs": elapsed_ms,
                "errors": errors,
                "partialSuccess": success_count > 0 and len(errors) > 0,
            },
        }
        self.cache.set_search(keyword, page, response)
        yield {
            "type": "done",
            "items": response["items"],
            "debug": response["debug"],
        }

    def _merge_results(self, items: list[dict]) -> list[dict]:
        """Merge results with same name and author."""
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
            best = dict(best)
            sources_info = ", ".join(
                f"{g.get('sourceName','')}({g.get('sourceId','')})" for g in group_items
            )
            intro = best.get("intro", "")
            best["intro"] = f"{intro} [来源: {sources_info}]" if intro else f"[来源: {sources_info}]"
            merged.append(best)
        return merged

    async def book_detail(self, book_id: str, user_agent: str = "") -> dict:
        cached = self.cache.get_book(book_id)
        if cached is not None:
            return cached

        try:
            source_id, book_url = decode_book_id(book_id)
        except Exception:
            return {"implemented": True, "data": None, "debug": {"error": "invalid book_id format"}}

        result = await self.scheduler.detail(source_id, book_url)
        data = result.get("data")
        if data is None:
            return {"implemented": True, "data": None, "debug": result.get("debug", {})}

        base_api = f"http://{HOST}:{PORT}"
        data["bookUrl"] = f"{base_api}/api/legado/book/{book_id}"
        data["tocUrl"] = f"{base_api}/api/legado/book/{book_id}/toc"

        self._ensure_book_record(book_id, data)

        response = {"implemented": True, "data": data, "debug": {}}
        self.cache.set_book(book_id, source_id, book_url, response)
        return response

    def _ensure_book_record(self, book_id: str, data: dict) -> None:
        import sqlite3
        from app.config import DB_PATH
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO book_records
                (book_id, name, author, last_chapter, last_seen_at, created_at)
                VALUES (?, ?, ?, ?, datetime('now'), COALESCE((SELECT created_at FROM book_records WHERE book_id=?), datetime('now')))
                """,
                (book_id, data.get("name", ""), data.get("author", ""), data.get("lastChapter", ""), book_id),
            )
            conn.commit()

    async def toc(self, book_id: str, user_agent: str = "") -> dict:
        cached = self.cache.get_toc(book_id)
        if cached is not None:
            return cached

        try:
            source_id, book_url = decode_book_id(book_id)
        except Exception:
            return {"implemented": True, "bookId": book_id, "chapters": [], "debug": {"error": "invalid book_id format"}}

        result = await self.scheduler.toc(source_id, book_url)
        chapters = result.get("chapters", [])
        debug = result.get("debug", {})

        response = {
            "implemented": True,
            "bookId": book_id,
            "chapters": chapters,
            "debug": debug,
        }
        if not debug.get("error"):
            self.cache.set_toc(book_id, response)
        return response

    async def chapter(self, chapter_id: str, user_agent: str = "") -> dict:
        cached = self.cache.get_chapter(chapter_id)
        if cached is not None:
            return cached

        try:
            source_id, chapter_url = decode_chapter_id(chapter_id)
        except Exception:
            return {"implemented": True, "chapterId": chapter_id, "title": "", "content": "", "debug": {"error": "invalid chapter_id format"}}

        result = await self.scheduler.chapter(source_id, chapter_url)
        title = result.get("title", "")
        content = result.get("content", "")
        debug = result.get("debug", {})

        response = {
            "implemented": True,
            "chapterId": chapter_id,
            "title": title,
            "content": content,
            "debug": debug,
        }
        if not debug.get("error"):
            self.cache.set_chapter(chapter_id, source_id, chapter_url, response)
        return response

    async def test_source(
        self,
        source_id: str,
        keyword: str = "凡人修仙传",
        page: int = 1,
        stage: str = "search",
        proxy_mode_override: str | None = None,
    ) -> dict:
        """Test a single plugin without affecting active pool state."""
        plugin = self.scheduler._plugins.get(source_id)
        if not plugin:
            return {"pass": False, "error": "书源不存在", "stage": stage}

        result: dict[str, Any] = {
            "pass": False,
            "sourceId": source_id,
            "stage": stage,
            "proxyMode": proxy_mode_override or "auto",
            "keyword": keyword,
        }

        ctx = self.scheduler._make_ctx(source_id)
        t0 = time.perf_counter()
        try:
            if stage == "search":
                if "search" not in plugin.capabilities:
                    result["error"] = "插件不支持搜索"
                else:
                    items = await asyncio.wait_for(plugin.source.search(ctx, keyword, page), timeout=15.0)
                    latency_ms = int((time.perf_counter() - t0) * 1000)
                    result["pass"] = True
                    result["itemsCount"] = len(items or [])
                    result["sample"] = [dict(i) if hasattr(i, "items") else i for i in (items or [])[:3]]
                    result["latencyMs"] = latency_ms

            elif stage == "detail":
                if "detail" not in plugin.capabilities:
                    result["error"] = "插件不支持详情"
                else:
                    book_url = plugin.metadata.base_urls[0] if plugin.metadata.base_urls else ""
                    detail = await asyncio.wait_for(plugin.source.detail(ctx, book_url), timeout=15.0)
                    latency_ms = int((time.perf_counter() - t0) * 1000)
                    result["pass"] = True
                    result["data"] = dict(detail) if hasattr(detail, "items") else detail
                    result["latencyMs"] = latency_ms

            elif stage == "toc":
                if "toc" not in plugin.capabilities:
                    result["error"] = "插件不支持目录"
                else:
                    book_url = plugin.metadata.base_urls[0] if plugin.metadata.base_urls else ""
                    if "detail" in plugin.capabilities:
                        detail = await asyncio.wait_for(plugin.source.detail(ctx, book_url), timeout=15.0)
                        if hasattr(detail, "get"):
                            book_url = detail.get("tocUrl", book_url)
                    chapters = await asyncio.wait_for(plugin.source.toc(ctx, book_url), timeout=15.0)
                    latency_ms = int((time.perf_counter() - t0) * 1000)
                    result["pass"] = True
                    result["chaptersCount"] = len(chapters or [])
                    result["latencyMs"] = latency_ms

            elif stage == "content":
                if "chapter" not in plugin.capabilities:
                    result["error"] = "插件不支持正文"
                else:
                    book_url = plugin.metadata.base_urls[0] if plugin.metadata.base_urls else ""
                    if "detail" in plugin.capabilities:
                        detail = await asyncio.wait_for(plugin.source.detail(ctx, book_url), timeout=15.0)
                        if hasattr(detail, "get"):
                            book_url = detail.get("tocUrl", book_url)
                    if "toc" in plugin.capabilities:
                        chapters = await asyncio.wait_for(plugin.source.toc(ctx, book_url), timeout=15.0)
                        if chapters:
                            first_ch = chapters[0]
                            ch_url = first_ch.get("chapterUrl", "") if hasattr(first_ch, "get") else getattr(first_ch, "chapter_url", "")
                            content = await asyncio.wait_for(plugin.source.chapter(ctx, ch_url), timeout=15.0)
                            latency_ms = int((time.perf_counter() - t0) * 1000)
                            result["pass"] = True
                            content_text = content.get("content", "") if hasattr(content, "get") else getattr(content, "content", "")
                            result["contentLength"] = len(content_text)
                            result["latencyMs"] = latency_ms
                        else:
                            result["error"] = "目录为空，无法测试正文"
                    else:
                        result["error"] = "插件不支持目录，无法获取章节URL"
            else:
                result["error"] = f"未知测试阶段: {stage}"

        except asyncio.TimeoutError:
            result["error"] = "timeout"
            result["latencyMs"] = int((time.perf_counter() - t0) * 1000)
        except Exception as e:
            result["error"] = str(e)
            result["latencyMs"] = int((time.perf_counter() - t0) * 1000)
        finally:
            await ctx._fetcher.close()

        self.repo.update_test_result(source_id, result)
        return result
