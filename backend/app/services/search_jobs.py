"""Realtime search job management with stateful jobs and SSE events."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.config import HOST, PORT, SOURCE_POOL_CONFIG_PATH
from app.core.proxy import ProxyConfig
from app.services.cache import Cache
from app.source_plugins.scheduler import PluginScheduler
from app.services.plugin_health_repository import PluginHealthRepository
from app.services.plugin_auth_repository import PluginAuthRepository
from app.services.live_acceptance import candidate_id_for, group_candidates
from app.source_plugins.id_codec import encode_book_id
from app.services.browser_challenge import BrowserChallengeService
from app.source_plugins.errors import normalize_failure


@dataclass
class SearchJob:
    job_id: str
    keyword: str
    page: int
    status: str  # pending, running, completed, cancelled
    created_at: float
    sources: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    result: dict | None = None
    candidate_groups: list[dict] = field(default_factory=list)
    error_count: int = 0
    success_count: int = 0
    completed_count: int = 0
    timeout_count: int = 0
    browser_challenges: list[dict] = field(default_factory=list)
    elapsed_ms: int = 0
    cancel_requested: bool = False


class SearchJobService:
    def __init__(self):
        self._jobs: dict[str, SearchJob] = {}
        self._repo = PluginHealthRepository()
        self._cache = Cache()
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
        self._repo.record_attempt(
            source_id=source_id,
            stage=stage,
            url=url,
            direct_status="success" if success and not proxy_used else ("failed" if not proxy_used else "-"),
            proxy_status="success" if success and proxy_used else ("failed" if proxy_used else "-"),
            proxy_used=proxy_used,
            latency_ms=latency_ms,
            error=error,
        )

    def create_job(self, keyword: str, page: int = 1, limit: int | None = None) -> SearchJob:
        job_id = str(uuid.uuid4())
        config = self._get_search_config()
        max_sources = limit if limit is not None else config.get("max_sources_per_search", 200)
        plugins = self.scheduler._enabled_plugins()
        if max_sources is not None:
            plugins = plugins[:max_sources]
        sources = [{"sourceId": p.metadata.id, "bookSourceName": p.metadata.name, "proxyMode": "auto"} for p in plugins]
        job = SearchJob(
            job_id=job_id,
            keyword=keyword,
            page=page,
            status="pending",
            created_at=time.time(),
            sources=sources,
        )
        self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> SearchJob | None:
        return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job and job.status in ("pending", "running"):
            job.cancel_requested = True
            job.status = "cancelled"
            return True
        return False

    def get_events(self, job_id: str, after_index: int = 0) -> list[dict]:
        job = self._jobs.get(job_id)
        if not job:
            return []
        return job.events[after_index:]

    def get_candidates(self, job_id: str) -> list[dict]:
        job = self._jobs.get(job_id)
        if not job:
            return []
        return job.candidate_groups

    def find_active_job(self, keyword: str, page: int = 1) -> SearchJob | None:
        for job in sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True):
            if job.keyword == keyword and job.page == page and job.status in {"pending", "running"}:
                return job
        return None

    def snapshot(self, job: SearchJob) -> dict:
        items: list[dict] = []
        for group in job.candidate_groups:
            group_items = group.get("items", [])
            if group_items:
                items.append(self._reading_item(dict(group_items[0])))
        if job.result and job.result.get("items") and not items:
            items = job.result.get("items", [])
        return {
            "implemented": True,
            "keyword": job.keyword,
            "page": job.page,
            "jobId": job.job_id,
            "status": job.status,
            "items": items,
            "candidateGroups": job.candidate_groups,
            "debug": {
                "sourceCount": len(job.sources),
                "attemptedCount": job.completed_count,
                "successCount": job.success_count,
                "errorCount": job.error_count,
                "timeoutCount": job.timeout_count,
                "elapsedMs": job.elapsed_ms,
                "browserChallenges": job.browser_challenges,
                "partial": job.status in {"pending", "running"},
            },
        }

    def _reading_item(self, item: dict) -> dict:
        raw_book_url = item.get("rawBookUrl") or item.get("bookUrl", "")
        if raw_book_url and "/api/legado/book/" not in raw_book_url:
            book_id = encode_book_id(item.get("sourceId", ""), raw_book_url)
            item["bookId"] = book_id
            item["rawBookUrl"] = raw_book_url
            item["bookUrl"] = f"http://{HOST}:{PORT}/api/legado/book/{book_id}"
        return item

    def find_candidate(self, job_id: str, candidate_id: str) -> dict | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        for group in job.candidate_groups:
            if group.get("candidateId") == candidate_id:
                items = group.get("items", [])
                return dict(items[0]) if items else None
            for item in group.get("items", []):
                if item.get("candidateId") == candidate_id:
                    return dict(item)
        return None

    def _preflight_browser_verification_error(self, plugin, stage: str = "search") -> dict | None:
        browser = plugin.metadata.browser or {}
        reason = str(browser.get("reason", "")).lower()
        if browser.get("mode") != "required" or "cloudflare" not in reason:
            return None
        if stage == "search" and browser.get("searchFallback") == "search_engine":
            return None
        stored_cookies = PluginAuthRepository().get_cookies(plugin.metadata.id)
        domains = set(plugin.metadata.domains or [])
        for profile in plugin.metadata.domain_profiles:
            domains.update(profile.get("domains", []) or [])
        has_clearance = any("cf_clearance" in (stored_cookies.get(domain) or {}) for domain in domains)
        if has_clearance:
            return None
        browser_url = str(browser.get("verificationUrl", "") or "")
        challenge = BrowserChallengeService().create_for_plugin(
            plugin,
            stage=stage,
            url=browser_url or (plugin.metadata.base_urls[0] if plugin.metadata.base_urls else ""),
            reason="BROWSER_REQUIRED",
            message="该书源需要先完成浏览器验证并保存 Cookie。",
        )
        return {
            **normalize_failure(
                source_id=plugin.metadata.id,
                stage=stage,
                code="BROWSER_REQUIRED",
                message="该书源需要先完成浏览器验证并保存 Cookie。",
                url=challenge.get("openUrl", ""),
                extra={"browserChallenge": challenge, "requiresBrowserVerification": True},
            ),
            "proxyUsed": False,
            "error": "browser verification required",
        }

    async def run_job(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return

        if job.status == "cancelled":
            job.events.append({"type": "cancelled"})
            return

        job.status = "running"
        config = self._get_search_config()
        max_concurrency = config.get("max_concurrency", 6)
        source_batch_size = config.get("source_batch_size", 20)
        overall_timeout = config.get("overall_search_timeout_seconds", 30.0)
        proxy_config = self._get_proxy_config()
        sources = job.sources
        plugins = self.scheduler._enabled_plugins()
        plugin_map = {p.metadata.id: p for p in plugins}

        source_batch_size = int(source_batch_size) if source_batch_size else 20
        if source_batch_size <= 0:
            source_batch_size = 20
        batches = [sources[i : i + source_batch_size] for i in range(0, len(sources), source_batch_size)]
        start_time = time.perf_counter()
        all_items: list[dict] = []
        errors: list[dict] = []

        job.events.append({
            "type": "summary",
            "keyword": job.keyword,
            "page": job.page,
            "sourceCount": len(sources),
            "batchSize": source_batch_size,
            "batchCount": len(batches),
            "maxConcurrency": max_concurrency,
            "overallTimeoutSeconds": overall_timeout,
        })

        if not sources:
            job.status = "cancelled" if job.cancel_requested else "completed"
            job.result = {
                "implemented": True,
                "keyword": job.keyword,
                "page": job.page,
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
            job.events.append({"type": "done", "items": [], "debug": job.result["debug"]})
            return

        async def _search_one(src_info: dict) -> dict:
            sid = src_info["sourceId"]
            plugin = plugin_map.get(sid)
            if not plugin or "search" not in plugin.capabilities:
                return {"source": src_info, "items": [], "error": None, "latencyMs": 0, "proxyUsed": False}
            ctx = self.scheduler._make_ctx(sid)
            source_timeout = self.scheduler.search_timeout_for_plugin(plugin)
            t0 = time.perf_counter()
            try:
                raw_items = await asyncio.wait_for(
                    plugin.source.search(ctx, job.keyword, job.page),
                    timeout=source_timeout,
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                items = []
                for item in raw_items or []:
                    if isinstance(item, dict):
                        item.setdefault("sourceId", sid)
                        item.setdefault("sourceName", plugin.metadata.name)
                        items.append(item)
                self._record_attempt(sid, "search", "", False, True, latency_ms)
                self._repo.record_success(sid, latency_ms)
                return {"source": src_info, "items": items, "error": None, "latencyMs": latency_ms, "proxyUsed": False}
            except asyncio.TimeoutError:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._record_attempt(sid, "search", "", False, False, latency_ms, "timeout")
                if (plugin.metadata.browser or {}).get("mode") in {"required", "optional"}:
                    challenge = BrowserChallengeService().create_for_plugin(
                        plugin,
                        stage="search",
                        reason="BROWSER_REQUIRED",
                        message="source timed out and may require browser verification",
                    )
                    err = {
                        **normalize_failure(
                            source_id=sid,
                            stage="search",
                            code="BROWSER_REQUIRED",
                            message="timeout; browser verification may be required",
                            url=challenge.get("openUrl", ""),
                            extra={"browserChallenge": challenge, "requiresBrowserVerification": True},
                        ),
                        "proxyUsed": False,
                    }
                else:
                    err = {"sourceId": sid, "stage": "search", "url": "", "proxyUsed": False, "error": "timeout"}
                return {"source": src_info, "items": [], "error": err, "latencyMs": latency_ms, "proxyUsed": False}
            except Exception as exc:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._record_attempt(sid, "search", "", False, False, latency_ms, str(exc))
                code = getattr(exc, "code", "PLUGIN_RUNTIME_ERROR")
                url = getattr(exc, "url", "") or ""
                extra: dict[str, Any] = {}
                if code in {"CLOUDFLARE_REQUIRED", "BROWSER_REQUIRED"}:
                    extra["browserChallenge"] = BrowserChallengeService().create_for_plugin(
                        plugin,
                        stage="search",
                        url=url,
                        reason=code,
                        message=str(exc),
                    )
                    extra["requiresBrowserVerification"] = True
                err = {
                    **normalize_failure(source_id=sid, stage="search", code=code, message=str(exc), url=url, extra=extra),
                    "proxyUsed": False,
                    "error": str(exc),
                }
                return {"source": src_info, "items": [], "error": err, "latencyMs": latency_ms, "proxyUsed": False}
            finally:
                await ctx._fetcher.close()

        for batch_index, batch in enumerate(batches, start=1):
            if job.status == "cancelled":
                break

            elapsed = time.perf_counter() - start_time
            if elapsed >= overall_timeout:
                errors.append({"sourceId": "", "stage": "search", "url": "", "error": "overall timeout"})
                job.events.append({"type": "overall_timeout", "elapsedMs": int(elapsed * 1000)})
                break

            for src in batch:
                job.events.append({
                    "type": "source_start",
                    "batchIndex": batch_index,
                    "sourceId": src["sourceId"],
                    "sourceName": src.get("bookSourceName") or src["sourceId"],
                    "proxyMode": src.get("proxyMode", "auto"),
                })

            active_batch = []
            for src in batch:
                plugin = plugin_map.get(src["sourceId"])
                err = self._preflight_browser_verification_error(plugin) if plugin else None
                if not err:
                    active_batch.append(src)
                    continue
                errors.append(err)
                challenge = err.get("extra", {}).get("browserChallenge")
                if challenge:
                    job.browser_challenges.append(challenge)
                job.completed_count += 1
                job.events.append({
                    "type": "source_done",
                    "sourceId": src["sourceId"],
                    "sourceName": src.get("bookSourceName") or src["sourceId"],
                    "status": "error",
                    "resultCount": 0,
                    "latencyMs": 0,
                    "proxyUsed": False,
                    "error": err,
                    "completedCount": job.completed_count,
                    "sourceCount": len(sources),
                })
                job.events.append({
                    "type": "source_verification_required",
                    "sourceId": src["sourceId"],
                    "sourceName": src.get("bookSourceName") or src["sourceId"],
                    "error": err,
                    "completedCount": job.completed_count,
                    "sourceCount": len(sources),
                })

            tasks = [asyncio.create_task(_search_one(src)) for src in active_batch]
            pending = set(tasks)
            while pending:
                if job.cancel_requested or job.status == "cancelled":
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    job.events.append({"type": "cancelled"})
                    pending = set()
                    break
                remaining_timeout = max(0.0, overall_timeout - (time.perf_counter() - start_time))
                poll_timeout = min(0.25, remaining_timeout) if remaining_timeout > 0 else 0
                done, pending = await asyncio.wait(pending, timeout=poll_timeout, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    if time.perf_counter() - start_time < overall_timeout:
                        continue
                    timed_out_count = len(pending)
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    job.timeout_count += timed_out_count
                    errors.append({"sourceId": "", "stage": "search", "url": "", "error": "overall timeout"})
                    job.events.append({"type": "overall_timeout", "elapsedMs": int((time.perf_counter() - start_time) * 1000)})
                    pending = set()
                    break

                for task in done:
                    result = task.result()
                    src = result["source"]
                    items = result["items"]
                    err = result["error"]
                    job.completed_count += 1
                    if err:
                        errors.append(err)
                        challenge = err.get("extra", {}).get("browserChallenge")
                        if challenge:
                            job.browser_challenges.append(challenge)
                        if "timeout" in str(err.get("error", "")).lower():
                            job.timeout_count += 1
                    if items:
                        job.success_count += 1
                        for item in items:
                            item.setdefault("candidateId", candidate_id_for(item))
                            score = 0
                            if job.keyword.lower() in item.get("name", "").lower():
                                score += 100
                            if item.get("author"):
                                score += 10
                            if item.get("lastChapter"):
                                score += 5
                            if item.get("intro"):
                                score += 3
                            item["score"] = score
                        all_items.extend(items)
                        job.candidate_groups = group_candidates(all_items, job.keyword)

                    job.events.append({
                        "type": "source_done",
                        "sourceId": src["sourceId"],
                        "sourceName": src.get("bookSourceName") or src["sourceId"],
                        "status": "error" if err else "success",
                        "resultCount": len(items),
                        "latencyMs": result["latencyMs"],
                        "proxyUsed": result["proxyUsed"],
                        "error": err,
                        "completedCount": job.completed_count,
                        "sourceCount": len(sources),
                    })
                    if err:
                        code = err.get("code", "")
                        if code in {"CLOUDFLARE_REQUIRED", "BROWSER_REQUIRED"}:
                            event_type = "source_verification_required"
                        else:
                            event_type = "source_timeout" if "timeout" in str(err.get("error", "")).lower() else "source_error"
                        job.events.append({
                            "type": event_type,
                            "sourceId": src["sourceId"],
                            "sourceName": src.get("bookSourceName") or src["sourceId"],
                            "error": err,
                            "completedCount": job.completed_count,
                            "sourceCount": len(sources),
                        })
                    elif not items:
                        job.events.append({
                            "type": "source_empty",
                            "sourceId": src["sourceId"],
                            "sourceName": src.get("bookSourceName") or src["sourceId"],
                            "completedCount": job.completed_count,
                            "sourceCount": len(sources),
                        })
                    for item in items:
                        job.events.append({
                            "type": "result",
                            "item": item,
                            "sourceId": src["sourceId"],
                            "sourceName": src.get("bookSourceName") or src["sourceId"],
                        })

            job.events.append({
                "type": "batch_done",
                "batchIndex": batch_index,
                "completedCount": job.completed_count,
                "sourceCount": len(sources),
            })

        candidate_groups = group_candidates(all_items, job.keyword)
        job.candidate_groups = candidate_groups
        for group in candidate_groups:
            job.events.append({"type": "candidate_grouped", "candidate": group})

        merged = self._merge_results(all_items)
        merged.sort(key=lambda x: (-x.get("score", 0), x.get("name", "")))
        base_api = f"http://{HOST}:{PORT}"
        for item in merged:
            raw_book_url = item.get("bookUrl", "")
            if raw_book_url:
                book_id = encode_book_id(item.get("sourceId", ""), raw_book_url)
                item["bookId"] = book_id
                item["rawBookUrl"] = raw_book_url
                item["bookUrl"] = f"{base_api}/api/legado/book/{book_id}"

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        job.elapsed_ms = elapsed_ms
        job.error_count = len(errors)

        response = {
            "implemented": True,
            "keyword": job.keyword,
            "page": job.page,
            "items": merged,
            "candidateGroups": candidate_groups,
            "debug": {
                "sourceCount": len(sources),
                "batchSize": source_batch_size,
                "batchCount": len(batches),
                "attemptedCount": job.completed_count,
                "successCount": job.success_count,
                "errorCount": len(errors),
                "disabledCount": 0,
                "timeoutCount": job.timeout_count,
                "elapsedMs": elapsed_ms,
                "errors": errors,
                "browserChallenges": job.browser_challenges,
                "partialSuccess": job.success_count > 0 and len(errors) > 0,
            },
        }
        self._cache.set_search(job.keyword, job.page, response)
        job.result = response
        if job.status != "cancelled":
            job.status = "completed"
        job.events.append({"type": "done", "items": response["items"], "debug": response["debug"]})

    def _merge_results(self, items: list[dict]) -> list[dict]:
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
            sources_info = ", ".join(f"{g.get('sourceName','')}({g.get('sourceId','')})" for g in group_items)
            intro = best.get("intro", "")
            best["intro"] = f"{intro} [来源: {sources_info}]" if intro else f"[来源: {sources_info}]"
            merged.append(best)
        return merged
