"""Realtime search job management with stateful jobs and SSE events."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.config import HOST, PORT
from app.engine.proxy import ProxyConfig
from app.rules.models import SearchResultItem, SourceError
from app.services.cache import Cache
from app.services.legado_engine_runner import LegadoEngineRunner
from app.services.source_repository import SourceRepository


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
    error_count: int = 0
    success_count: int = 0
    completed_count: int = 0
    timeout_count: int = 0
    elapsed_ms: int = 0
    cancel_requested: bool = False


class SearchJobService:
    def __init__(self):
        self._jobs: dict[str, SearchJob] = {}
        self._repo = SourceRepository()
        self._cache = Cache()

    def _get_proxy_config(self) -> ProxyConfig:
        import json as _json
        from pathlib import Path
        pool_path = Path(__file__).resolve().parent.parent.parent / "config" / "source_pool.json"
        if pool_path.exists():
            data = _json.loads(pool_path.read_text(encoding="utf-8"))
            return ProxyConfig.from_dict(data.get("proxy", {}))
        return ProxyConfig()

    def _get_search_config(self) -> dict:
        import json as _json
        from pathlib import Path
        pool_path = Path(__file__).resolve().parent.parent.parent / "config" / "source_pool.json"
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
        repo = SourceRepository()
        self._repo = repo
        sources = repo.get_sources(enabled_only=True, limit=max_sources)
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
        if job and job.status == "completed":
            job.cancel_requested = True
            job.status = "cancelled"
            return True
        return False

    def get_events(self, job_id: str, after_index: int = 0) -> list[dict]:
        job = self._jobs.get(job_id)
        if not job:
            return []
        return job.events[after_index:]

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
        source_timeout = config.get("source_timeout_seconds", 8.0)
        overall_timeout = config.get("overall_search_timeout_seconds", 30.0)
        user_agent = config.get("default_user_agent", "")
        proxy_config = self._get_proxy_config()
        sources = job.sources

        source_batch_size = int(source_batch_size) if source_batch_size else 20
        if source_batch_size <= 0:
            source_batch_size = 20
        batches = [sources[i : i + source_batch_size] for i in range(0, len(sources), source_batch_size)]
        start_time = time.perf_counter()
        all_items: list[SearchResultItem] = []
        errors: list[SourceError] = []

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
            proxy_mode = src_info.get("proxyMode", "auto")
            executor = LegadoEngineRunner(
                user_agent=user_agent,
                timeout=source_timeout,
                proxy_url=proxy_config.url if proxy_config.enabled else "",
                proxy_mode=proxy_mode,
                proxy_config=proxy_config,
            )
            t0 = time.perf_counter()
            try:
                source = self._repo.load_raw_source(sid)
                if not source:
                    err = SourceError(sourceId=sid, stage="search", url="", proxyUsed=False, error="无法加载书源")
                    self._record_attempt(sid, "search", "", False, False, 0, "无法加载书源")
                    return {"source": src_info, "items": [], "error": err, "latencyMs": 0, "proxyUsed": False}

                items, err = await asyncio.wait_for(
                    executor.search(source, sid, job.keyword, job.page),
                    timeout=source_timeout,
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                meta = executor.get_last_meta()
                proxy_used = meta.get("proxyUsed", False)
                if err:
                    self._record_attempt(sid, "search", err.url or "", proxy_used, False, latency_ms, err.error)
                    if any(k in err.error.lower() for k in ["unsupported", "missing", "parse", "invalid"]):
                        self._repo.record_failure(sid, "search", err.error, is_hard_failure=True)
                    return {"source": src_info, "items": [], "error": err, "latencyMs": latency_ms, "proxyUsed": proxy_used}
                self._record_attempt(sid, "search", "", proxy_used, True, latency_ms)
                self._repo.record_success(sid, latency_ms)
                return {"source": src_info, "items": items, "error": None, "latencyMs": latency_ms, "proxyUsed": proxy_used}
            except asyncio.TimeoutError:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._record_attempt(sid, "search", "", False, False, latency_ms, "timeout")
                err = SourceError(sourceId=sid, stage="search", url="", proxyUsed=False, error="timeout")
                return {"source": src_info, "items": [], "error": err, "latencyMs": latency_ms, "proxyUsed": False}
            except Exception as exc:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._record_attempt(sid, "search", "", False, False, latency_ms, str(exc))
                err = SourceError(sourceId=sid, stage="search", url="", proxyUsed=False, error=str(exc))
                return {"source": src_info, "items": [], "error": err, "latencyMs": latency_ms, "proxyUsed": False}
            finally:
                await executor.close()

        for batch_index, batch in enumerate(batches, start=1):
            if job.status == "cancelled":
                break

            elapsed = time.perf_counter() - start_time
            if elapsed >= overall_timeout:
                errors.append(SourceError(sourceId="", stage="search", url="", error="overall timeout"))
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

            tasks = [asyncio.create_task(_search_one(src)) for src in batch]
            pending = set(tasks)
            while pending:
                remaining_timeout = max(0.1, overall_timeout - (time.perf_counter() - start_time))
                done, pending = await asyncio.wait(pending, timeout=remaining_timeout, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    job.timeout_count += len(pending)
                    errors.append(SourceError(sourceId="", stage="search", url="", error="overall timeout"))
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
                        if "timeout" in err.error.lower():
                            job.timeout_count += 1
                    if items:
                        job.success_count += 1
                        for item in items:
                            score = 0
                            if job.keyword.lower() in item.name.lower():
                                score += 100
                            if item.author:
                                score += 10
                            if item.lastChapter:
                                score += 5
                            if item.intro:
                                score += 3
                            item.score = score
                        all_items.extend(items)

                    job.events.append({
                        "type": "source_done",
                        "sourceId": src["sourceId"],
                        "sourceName": src.get("bookSourceName") or src["sourceId"],
                        "status": "error" if err else "success",
                        "resultCount": len(items),
                        "latencyMs": result["latencyMs"],
                        "proxyUsed": result["proxyUsed"],
                        "error": err.model_dump() if err else None,
                        "completedCount": job.completed_count,
                        "sourceCount": len(sources),
                    })
                    for item in items:
                        job.events.append({
                            "type": "result",
                            "item": item.model_dump(),
                            "sourceId": src["sourceId"],
                            "sourceName": src.get("bookSourceName") or src["sourceId"],
                        })

            job.events.append({
                "type": "batch_done",
                "batchIndex": batch_index,
                "completedCount": job.completed_count,
                "sourceCount": len(sources),
            })

        merged = self._merge_results(all_items)
        merged.sort(key=lambda x: (-x.score, x.name))
        base_api = f"http://{HOST}:{PORT}"
        for item in merged:
            item.bookUrl = f"{base_api}/api/legado/book/{item.bookId}"

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        job.elapsed_ms = elapsed_ms
        job.error_count = len(errors)

        response = {
            "implemented": True,
            "keyword": job.keyword,
            "page": job.page,
            "items": [item.model_dump() for item in merged],
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
                "errors": [err.model_dump() for err in errors if err],
                "partialSuccess": job.success_count > 0 and len(errors) > 0,
            },
        }
        self._cache.set_search(job.keyword, job.page, response)
        job.result = response
        if job.status != "cancelled":
            job.status = "completed"
        job.events.append({"type": "done", "items": response["items"], "debug": response["debug"]})

    def _merge_results(self, items: list[SearchResultItem]) -> list[SearchResultItem]:
        groups: dict[tuple[str, str], list[SearchResultItem]] = {}
        for item in items:
            key = (item.name.strip(), item.author.strip())
            if key not in groups:
                groups[key] = []
            groups[key].append(item)

        merged: list[SearchResultItem] = []
        for key, group_items in groups.items():
            if len(group_items) == 1:
                merged.append(group_items[0])
                continue
            best = max(group_items, key=lambda x: x.score)
            sources_info = ", ".join(f"{g.sourceName}({g.sourceId})" for g in group_items)
            best.intro = f"{best.intro} [来源: {sources_info}]" if best.intro else f"[来源: {sources_info}]"
            merged.append(best)
        return merged
