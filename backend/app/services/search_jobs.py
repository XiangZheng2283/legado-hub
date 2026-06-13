"""Realtime search job management with stateful jobs and SSE events."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.config import HOST, PORT, SOURCE_POOL_CONFIG_PATH
from app.core.proxy import ProxyConfig
from app.services.cache import Cache
from app.source_plugins.scheduler import PluginScheduler
from app.services.plugin_health_repository import PluginHealthRepository
from app.services.live_acceptance import candidate_id_for, group_candidates
from app.source_plugins.id_codec import encode_book_id
from app.services.aggregate_virtual_source import aggregate_items_for_groups
from app.services.aggregate_processor import AggregateProcessor
from app.services.bookshelf import record_bookshelf_items
from app.source_plugins.errors import normalize_failure


def _is_official_source_id(source_id: str, scheduler: PluginScheduler | None = None) -> bool:
    if not source_id or scheduler is None:
        return False
    plugin_map = getattr(scheduler, "_plugins", None)
    if isinstance(plugin_map, dict):
        plugin = plugin_map.get(source_id)
        return bool(plugin and plugin.metadata.is_official_source())
    plugins = getattr(scheduler, "plugins", None)
    if isinstance(plugins, list):
        for plugin in plugins:
            if getattr(getattr(plugin, "metadata", None), "id", "") == source_id:
                return bool(plugin.metadata.is_official_source())
    plugin = getattr(scheduler, "plugin", None)
    if plugin and getattr(getattr(plugin, "metadata", None), "id", "") == source_id:
        return bool(plugin.metadata.is_official_source())
    return False


def _scheduler_plugin(source_id: str, scheduler: PluginScheduler | None = None) -> Any:
    if not source_id or scheduler is None:
        return None
    plugin_map = getattr(scheduler, "_plugins", None)
    if isinstance(plugin_map, dict):
        return plugin_map.get(source_id)
    plugins = getattr(scheduler, "plugins", None)
    if isinstance(plugins, list):
        for plugin in plugins:
            if getattr(getattr(plugin, "metadata", None), "id", "") == source_id:
                return plugin
    plugin = getattr(scheduler, "plugin", None)
    if plugin and getattr(getattr(plugin, "metadata", None), "id", "") == source_id:
        return plugin
    return None


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
    elapsed_ms: int = 0
    cancel_requested: bool = False


class SearchJobService:
    def __init__(self):
        self._jobs: dict[str, SearchJob] = {}
        self._repo = PluginHealthRepository()
        self._cache = Cache()
        self.scheduler = PluginScheduler(config=self._get_search_config())

    def _conn(self) -> sqlite3.Connection:
        from app.config import DB_PATH
        from app.storage.db import initialize_database

        initialize_database(DB_PATH)
        return sqlite3.connect(DB_PATH)

    def persist_job(self, job: SearchJob) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO search_jobs
                (job_id, keyword, page, status, created_at, sources_json, result_json,
                 candidate_groups_json, error_count, success_count, completed_count,
                 timeout_count, elapsed_ms, cancel_requested, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    job.job_id,
                    job.keyword,
                    job.page,
                    job.status,
                    job.created_at,
                    json.dumps(job.sources, ensure_ascii=False),
                    json.dumps(job.result, ensure_ascii=False) if job.result is not None else "",
                    json.dumps(job.candidate_groups, ensure_ascii=False),
                    job.error_count,
                    job.success_count,
                    job.completed_count,
                    job.timeout_count,
                    job.elapsed_ms,
                    int(job.cancel_requested),
                ),
            )
            for index, event in enumerate(job.events):
                conn.execute(
                    """
                    INSERT OR REPLACE INTO search_job_events
                    (job_id, event_index, event_json)
                    VALUES (?, ?, ?)
                    """,
                    (job.job_id, index, json.dumps(event, ensure_ascii=False)),
                )
            conn.commit()

    def _load_job(self, job_id: str) -> SearchJob | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT job_id, keyword, page, status, created_at, sources_json, result_json,
                       candidate_groups_json, error_count, success_count, completed_count,
                       timeout_count, elapsed_ms, cancel_requested
                FROM search_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
            if not row:
                return None
            event_rows = conn.execute(
                """
                SELECT event_json
                FROM search_job_events
                WHERE job_id = ?
                ORDER BY event_index ASC
                """,
                (job_id,),
            ).fetchall()
        job = SearchJob(
            job_id=row[0],
            keyword=row[1],
            page=int(row[2] or 1),
            status=row[3],
            created_at=float(row[4] or time.time()),
            sources=json.loads(row[5] or "[]"),
            events=[json.loads(item[0]) for item in event_rows],
            result=json.loads(row[6]) if row[6] else None,
            candidate_groups=json.loads(row[7] or "[]"),
            error_count=int(row[8] or 0),
            success_count=int(row[9] or 0),
            completed_count=int(row[10] or 0),
            timeout_count=int(row[11] or 0),
            elapsed_ms=int(row[12] or 0),
            cancel_requested=bool(row[13]),
        )
        self._jobs[job_id] = job
        return job

    def list_jobs(self, limit: int = 20) -> list[dict]:
        limit = max(1, min(int(limit or 20), 100))
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT job_id, keyword, page, status, created_at, success_count,
                       error_count, completed_count, elapsed_ms, updated_at
                FROM search_jobs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "jobId": row[0],
                "keyword": row[1],
                "page": row[2],
                "status": row[3],
                "createdAt": row[4],
                "successCount": row[5],
                "errorCount": row[6],
                "completedCount": row[7],
                "elapsedMs": row[8],
                "updatedAt": row[9],
            }
            for row in rows
        ]

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
        result: str = "",
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
            result=result,
        )

    @staticmethod
    def _normalize_keyword(keyword: str) -> str:
        """Strip excess whitespace from search keyword."""
        return " ".join(keyword.split())

    def _get_score_filter(self) -> int:
        import sqlite3
        from app.config import DB_PATH
        try:
            with sqlite3.connect(DB_PATH) as conn:
                row = conn.execute(
                    "SELECT value_json FROM admin_settings WHERE key = 'searchScoreFilter'"
                ).fetchone()
            if row:
                val = json.loads(row[0])
                if isinstance(val, int) and val >= 0:
                    return val
        except Exception:
            pass
        return 100

    @staticmethod
    def _positive_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def create_job(self, keyword: str, page: int = 1, limit: int | None = None, source_ids: list[str] | None = None) -> SearchJob:
        job_id = str(uuid.uuid4())
        config = self._get_search_config()
        self.scheduler.config = config
        max_sources = limit if limit is not None else config.get("max_sources_per_search", 200)
        plugins = self.scheduler._enabled_plugins()
        if hasattr(self.scheduler, "_search_priority_plugins"):
            plugins = self.scheduler._search_priority_plugins(plugins)
        if source_ids:
            plugins = [p for p in plugins if p.metadata.id in source_ids]
        if max_sources is not None:
            plugins = plugins[:max_sources]
        sources = [{"sourceId": p.metadata.id, "bookSourceName": p.metadata.name, "proxyMode": "auto"} for p in plugins]
        job = SearchJob(
            job_id=job_id,
            keyword=self._normalize_keyword(keyword),
            page=page,
            status="pending",
            created_at=time.time(),
            sources=sources,
        )
        self._jobs[job_id] = job
        self.persist_job(job)
        return job

    def get_job(self, job_id: str) -> SearchJob | None:
        return self._jobs.get(job_id) or self._load_job(job_id)

    def cancel_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if job and job.status in ("pending", "running"):
            job.cancel_requested = True
            job.status = "cancelled"
            self.persist_job(job)
            return True
        return False

    def get_events(self, job_id: str, after_index: int = 0) -> list[dict]:
        job = self.get_job(job_id)
        if not job:
            return []
        self.persist_job(job)
        return job.events[after_index:]

    def get_candidates(self, job_id: str) -> list[dict]:
        job = self.get_job(job_id)
        if not job:
            return []
        return job.candidate_groups

    def find_active_job(self, keyword: str, page: int = 1) -> SearchJob | None:
        for job in sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True):
            if job.keyword == keyword and job.page == page and job.status in {"pending", "running"}:
                return job
        return None

    def cached_snapshot(
        self,
        keyword: str,
        page: int = 1,
        base_api: str | None = None,
        include_official_sources: bool = True,
    ) -> dict | None:
        cached = self._cache.get_search(keyword, page)
        if not cached:
            return None
        items = []
        for item in cached.get("items", []):
            if not isinstance(item, dict):
                continue
            source_id = item.get("sourceId", "")
            plugin = _scheduler_plugin(source_id, self.scheduler)
            if not include_official_sources and plugin and plugin.metadata.is_official_source():
                continue
            items.append(self._reading_item(dict(item), base_api=base_api))
        candidate_groups = [
            dict(group)
            for group in cached.get("candidateGroups", [])
            if isinstance(group, dict)
        ]
        aggregate_items = aggregate_items_for_groups(
            candidate_groups,
            base_api=base_api or f"http://{HOST}:{PORT}",
        )
        if AggregateProcessor().return_only_aggregate_source():
            items = aggregate_items
        else:
            items.extend(aggregate_items)
        raw_items = [item for item in cached.get("items", []) if isinstance(item, dict)]
        official_debug = self._official_source_debug_info(raw_items, include_official_sources)
        debug = dict(cached.get("debug") or {})
        debug.update(official_debug)
        debug["cacheHit"] = True
        debug["partial"] = False
        return {
            "implemented": True,
            "keyword": keyword,
            "page": page,
            "jobId": "",
            "status": "cached",
            "items": items,
            "candidateGroups": candidate_groups,
            "debug": debug,
        }

    def snapshot(
        self,
        job: SearchJob,
        base_api: str | None = None,
        include_official_sources: bool = True,
    ) -> dict:
        items: list[dict] = []
        if job.result and job.result.get("items"):
            for item in job.result.get("items", []):
                if not isinstance(item, dict):
                    continue
                source_id = item.get("sourceId", "")
                plugin = _scheduler_plugin(source_id, self.scheduler)
                if not include_official_sources and plugin and plugin.metadata.is_official_source():
                    continue
                items.append(self._reading_item(dict(item), base_api=base_api))
        else:
            for group in job.candidate_groups:
                group_items = group.get("items", [])
                for item in group_items:
                    source_id = item.get("sourceId", "") if isinstance(item, dict) else ""
                    plugin = _scheduler_plugin(source_id, self.scheduler) if source_id else None
                    if not include_official_sources and plugin and plugin.metadata.is_official_source():
                        continue
                    items.append(self._reading_item(dict(item), base_api=base_api))
        aggregate_items = aggregate_items_for_groups(job.candidate_groups, base_api=base_api or f"http://{HOST}:{PORT}")
        if AggregateProcessor().return_only_aggregate_source():
            items = aggregate_items
        else:
            items.extend(aggregate_items)
        raw_items: list[dict] = []
        if job.result and job.result.get("items"):
            raw_items = [dict(item) for item in job.result.get("items", []) if isinstance(item, dict)]
        else:
            for group in job.candidate_groups:
                for item in group.get("items", []):
                    if isinstance(item, dict):
                        raw_items.append(dict(item))
        official_debug = self._official_source_debug_info(raw_items, include_official_sources)
        debug = {
            "sourceCount": len(job.sources),
            "attemptedCount": job.completed_count,
            "successCount": job.success_count,
            "errorCount": job.error_count,
            "timeoutCount": job.timeout_count,
            "elapsedMs": job.elapsed_ms,
            "partial": job.status in {"pending", "running"},
        }
        debug.update(official_debug)
        return {
            "implemented": True,
            "keyword": job.keyword,
            "page": job.page,
            "jobId": job.job_id,
            "status": job.status,
            "items": items,
            "candidateGroups": job.candidate_groups,
            "debug": debug,
        }

    def _reading_item(self, item: dict, base_api: str | None = None) -> dict:
        base_api = base_api or f"http://{HOST}:{PORT}"
        raw_book_url = item.get("rawBookUrl") or item.get("bookUrl", "")
        if raw_book_url and "/api/legado/book/" in raw_book_url:
            book_id = raw_book_url.rsplit("/", 1)[-1]
            item["bookId"] = item.get("bookId") or book_id
            item["bookUrl"] = f"{base_api}/api/legado/book/{book_id}"
        elif raw_book_url:
            book_id = encode_book_id(item.get("sourceId", ""), raw_book_url)
            item["bookId"] = book_id
            item["rawBookUrl"] = raw_book_url
            item["bookUrl"] = f"{base_api}/api/legado/book/{book_id}"
        self._apply_reading_display_fields(item)
        return item

    def _apply_reading_display_fields(self, item: dict) -> None:
        source_name = str(
            item.get("sourceName")
            or item.get("bookSourceName")
            or item.get("sourceId")
            or ""
        ).strip()
        item["readingSourceName"] = source_name

        raw_kind = str(item.get("kind") or "").strip()
        if raw_kind in {"搜索提供器", "搜索", "search"}:
            item.setdefault("extra", {})
            if isinstance(item["extra"], dict):
                item["extra"].setdefault("sourceKind", raw_kind)
            raw_kind = ""
        item["kind"] = self._normalize_kind(raw_kind) if raw_kind else ""

        latest = str(item.get("lastChapter") or "").strip()
        display_parts = [source_name]
        if latest:
            display_parts.append(latest)
        item["readingLastChapter"] = " · ".join(part for part in display_parts if part)

    @staticmethod
    def _normalize_kind(kind: str) -> str:
        parts: list[str] = []
        for chunk in kind.replace("｜", "/").replace("|", "/").replace("，", ",").split(","):
            parts.extend(part.strip() for part in chunk.split("/") if part.strip())
        seen: set[str] = set()
        unique: list[str] = []
        for part in parts:
            if part in seen:
                continue
            seen.add(part)
            unique.append(part)
        return ",".join(unique)

    def _score_search_item(self, item: dict, keyword: str) -> dict:
        item.setdefault("candidateId", candidate_id_for(item))
        score = 0
        name = item.get("name", "")
        kw = keyword.lower()
        name_lower = name.lower()
        # Title match
        if kw == name_lower:
            score += 200
        elif kw in name_lower:
            score += 100
        # Field completeness bonus
        if item.get("author"):
            score += 10
        if item.get("lastChapter"):
            score += 5
        if item.get("intro"):
            score += 3
        if item.get("coverUrl"):
            score += 3
        if item.get("kind"):
            score += 2
        if item.get("wordCount"):
            score += 2
        if item.get("updateTime"):
            score += 1
        # Official source priority is handled at the sort/aggregate layer;
        # do not inflate the filterable score here.
        if _is_official_source_id(item.get("sourceId", ""), self.scheduler):
            item.setdefault("extra", {})
            if isinstance(item["extra"], dict):
                item["extra"]["officialSourcePriority"] = True
        item["score"] = score
        return item

    def _source_result_items(self, items: list[dict], include_official_sources: bool = True) -> list[dict]:
        result_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            source_id = item.get("sourceId", "")
            plugin = _scheduler_plugin(source_id, self.scheduler)
            if not include_official_sources and plugin and plugin.metadata.is_official_source():
                continue
            result_items.append(self._reading_item(dict(item)))
        result_items.sort(
            key=lambda item: (
                -item.get("score", 0),
                item.get("name", ""),
                item.get("sourceName", "") or item.get("sourceId", ""),
            )
        )
        return result_items

    def find_candidate(self, job_id: str, candidate_id: str) -> dict | None:
        job = self.get_job(job_id)
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

    async def run_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if not job:
            return

        if job.status == "cancelled":
            job.events.append({"type": "cancelled"})
            self.persist_job(job)
            return

        job.status = "running"
        config = self._get_search_config()
        self.scheduler.config = config
        max_concurrency = self._positive_int(config.get("max_concurrency"), 3)
        source_batch_size = config.get("source_batch_size", 20)
        overall_timeout = config.get("overall_search_timeout_seconds", 60.0)
        proxy_config = self._get_proxy_config()
        sources = job.sources
        plugins = self.scheduler._enabled_plugins()
        plugin_map = {p.metadata.id: p for p in plugins}

        source_batch_size = self._positive_int(source_batch_size, 20)
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
        self.persist_job(job)

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
            self._cache.set_search(job.keyword, job.page, job.result)
            self.persist_job(job)
            return

        async def _search_one(src_info: dict) -> dict:
            sid = src_info["sourceId"]
            plugin = plugin_map.get(sid)
            plugin_proxy_mode = (plugin.metadata.proxy or {}).get("mode", "auto") if plugin else "auto"
            proxy_used = proxy_config.enabled and plugin_proxy_mode != "never"
            if not plugin or "search" not in plugin.capabilities:
                self._record_attempt(sid, "search", "", proxy_used, False, 0, "plugin not found or no search capability")
                return {"source": src_info, "items": [], "error": None, "latencyMs": 0, "proxyUsed": proxy_used}
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
                result = json.dumps([{"name": i.get("name"), "author": i.get("author"), "bookUrl": i.get("bookUrl")} for i in items[:5]], ensure_ascii=False) if items else ""
                self._record_attempt(sid, "search", "", proxy_used, True, latency_ms, result=result)
                self._repo.record_success(sid, latency_ms)
                return {"source": src_info, "items": items, "error": None, "latencyMs": latency_ms, "proxyUsed": proxy_used}
            except asyncio.TimeoutError:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._record_attempt(sid, "search", "", proxy_used, False, latency_ms, "timeout")
                if (plugin.metadata.browser or {}).get("mode") in {"required", "optional"}:
                    err = {
                        **normalize_failure(
                            source_id=sid,
                            stage="search",
                            code="BROWSER_REQUIRED",
                            message="timeout; browser bypass required",
                            url="",
                            extra={"bypassRequired": True, "bypassStrategy": "skip_source_until_bypass_available"},
                        ),
                        "proxyUsed": proxy_used,
                    }
                else:
                    err = {"sourceId": sid, "stage": "search", "url": "", "proxyUsed": proxy_used, "error": "timeout"}
                items = self._cached_search_items_for_source(job.keyword, job.page, sid)
                if items:
                    self._mark_search_cache_items(items, "timeout")
                    return {"source": src_info, "items": items, "error": None, "latencyMs": latency_ms, "proxyUsed": proxy_used}
                return {"source": src_info, "items": [], "error": err, "latencyMs": latency_ms, "proxyUsed": proxy_used}
            except Exception as exc:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._record_attempt(sid, "search", "", proxy_used, False, latency_ms, str(exc))
                code = getattr(exc, "code", "PLUGIN_RUNTIME_ERROR")
                url = getattr(exc, "url", "") or ""
                extra: dict[str, Any] = {}
                if code in {"CLOUDFLARE_REQUIRED", "BROWSER_REQUIRED"}:
                    extra["bypassRequired"] = True
                    extra["bypassStrategy"] = "skip_source_until_bypass_available"
                err = {
                    **normalize_failure(source_id=sid, stage="search", code=code, message=str(exc), url=url, extra=extra),
                    "proxyUsed": proxy_used,
                    "error": str(exc),
                }
                if self._should_fallback_to_cache(err):
                    items = self._cached_search_items_for_source(job.keyword, job.page, sid)
                    if items:
                        self._mark_search_cache_items(items, self._cache_reason(err))
                        return {"source": src_info, "items": items, "error": None, "latencyMs": latency_ms, "proxyUsed": proxy_used}
                return {"source": src_info, "items": [], "error": err, "latencyMs": latency_ms, "proxyUsed": proxy_used}
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
                active_batch.append(src)

            remaining_sources = list(active_batch)
            pending: set[asyncio.Task] = set()

            def start_next_sources() -> None:
                while remaining_sources and len(pending) < max_concurrency:
                    pending.add(asyncio.create_task(_search_one(remaining_sources.pop(0))))

            start_next_sources()
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
                        if "timeout" in str(err.get("error", "")).lower():
                            job.timeout_count += 1
                    if items:
                        job.success_count += 1
                        for item in items:
                            self._score_search_item(item, job.keyword)
                        all_items.extend(items)
                        job.candidate_groups = group_candidates(all_items, job.keyword)

                    # Build formal Chinese log message
                    status_label = "成功"
                    if err:
                        if "timeout" in str(err.get("error", "")).lower():
                            status_label = "超时"
                        else:
                            status_label = "失败"
                    elif not items:
                        status_label = "无结果"

                    job.events.append({
                        "type": "source_done",
                        "sourceId": src["sourceId"],
                        "sourceName": src.get("bookSourceName") or src["sourceId"],
                        "status": "error" if err else "success",
                        "statusLabel": status_label,
                        "resultCount": len(items),
                        "latencyMs": result["latencyMs"],
                        "proxyUsed": result["proxyUsed"],
                        "error": err,
                        "completedCount": job.completed_count,
                        "sourceCount": len(sources),
                        "message": (
                            f"{src.get('bookSourceName') or src['sourceId']} {status_label}"
                            f"，返回 {len(items)} 条结果，耗时 {result['latencyMs']}ms"
                            f"（{job.completed_count}/{len(sources)}）"
                        ),
                    })
                    if err:
                        event_type = "source_timeout" if "timeout" in str(err.get("error", "")).lower() else "source_error"
                        job.events.append({
                            "type": event_type,
                            "sourceId": src["sourceId"],
                            "sourceName": src.get("bookSourceName") or src["sourceId"],
                            "error": err,
                            "completedCount": job.completed_count,
                            "sourceCount": len(sources),
                            "message": (
                                f"{src.get('bookSourceName') or src['sourceId']} {status_label}"
                                f"：{err.get('message', err.get('error', '未知错误'))}"
                            ),
                        })
                    elif not items:
                        job.events.append({
                            "type": "source_empty",
                            "sourceId": src["sourceId"],
                            "sourceName": src.get("bookSourceName") or src["sourceId"],
                            "completedCount": job.completed_count,
                            "sourceCount": len(sources),
                            "message": (
                                f"{src.get('bookSourceName') or src['sourceId']} 无结果"
                                f"（{job.completed_count}/{len(sources)}）"
                            ),
                        })
                    for item in items:
                        job.events.append({
                            "type": "result",
                            "item": item,
                            "sourceId": src["sourceId"],
                            "sourceName": src.get("bookSourceName") or src["sourceId"],
                        })
                    self.persist_job(job)
                start_next_sources()

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

        source_items = self._source_result_items(all_items)
        record_bookshelf_items(source_items)

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        job.elapsed_ms = elapsed_ms
        job.error_count = len(errors)

        response = {
            "implemented": True,
            "keyword": job.keyword,
            "page": job.page,
            "items": source_items,
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
                "partialSuccess": job.success_count > 0 and len(errors) > 0,
            },
        }
        job.result = response
        self._cache.set_search(job.keyword, job.page, response)
        if job.status != "cancelled":
            job.status = "completed"
        job.events.append({"type": "done", "items": response["items"], "debug": response["debug"]})
        self.persist_job(job)

        # Auto-prefetch detail for high-score items (score > 100)
        if source_items:
            asyncio.create_task(self._prefetch_high_score_details(source_items, job.keyword))

    def _cached_search_items_for_source(self, keyword: str, page: int, source_id: str) -> list[dict]:
        cached = self._cache.get_search(keyword, page)
        if not cached:
            return []
        return [
            dict(item)
            for item in cached.get("items", [])
            if isinstance(item, dict) and item.get("sourceId") == source_id
        ]

    def _mark_search_cache_items(self, items: list[dict], reason: str) -> None:
        for item in items:
            item["cacheHit"] = True
            item["cacheReason"] = reason
            item.setdefault("debug", {})
            if isinstance(item["debug"], dict):
                item["debug"]["cacheHit"] = True
                item["debug"]["cacheReason"] = reason

    def _official_source_debug_info(
        self,
        raw_items: list[dict],
        include_official_sources: bool,
    ) -> dict[str, Any]:
        matched: list[str] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            source_id = item.get("sourceId", "")
            plugin = _scheduler_plugin(source_id, self.scheduler)
            if plugin and plugin.metadata.is_official_source():
                matched.append(source_id)
        matched = sorted(set(matched))
        return {
            "officialSourcesHidden": not include_official_sources,
            "officialSourcesMatched": matched,
            "officialSourcesMatchCount": len(matched),
        }

    def _should_fallback_to_cache(self, error: Any) -> bool:
        if not error:
            return False
        if isinstance(error, dict):
            code = str(error.get("code", "") or "")
            message = str(error.get("message", "") or error.get("error", "") or "")
        else:
            code = ""
            message = str(error)
        message_lower = message.lower()
        if code in {"PLUGIN_TIMEOUT", "BROWSER_REQUIRED", "CLOUDFLARE_REQUIRED", "FETCH_NETWORK_ERROR", "FETCH_HTTP_5XX"}:
            return True
        if "timeout" in message_lower or "cloudflare" in message_lower or "browser" in message_lower:
            return True
        if "captcha" in message_lower or "验证码" in message or "风控" in message:
            return True
        if "network" in message_lower:
            return True
        return False

    def _cache_reason(self, error: Any) -> str:
        if isinstance(error, dict):
            code = str(error.get("code", "") or "")
        else:
            code = ""
        mapping = {
            "PLUGIN_TIMEOUT": "timeout",
            "BROWSER_REQUIRED": "browser_required",
            "CLOUDFLARE_REQUIRED": "cloudflare_required",
            "FETCH_NETWORK_ERROR": "network_error",
            "FETCH_HTTP_5XX": "server_error",
        }
        return mapping.get(code, "live_failure")

    def _apply_score_filter(self, items: list[dict]) -> tuple[list[dict], int, int]:
        """Return (filtered_items, threshold, filtered_count)."""
        score_filter = self._get_score_filter()
        filtered_items = [item for item in items if item.get("score", 0) >= score_filter]
        return filtered_items, score_filter, len(items) - len(filtered_items)

    async def _prefetch_high_score_details(self, items: list[dict], keyword: str) -> None:
        """Prefetch book detail for items with score > 100 to warm cache."""
        high_score_items = [item for item in items if item.get("score", 0) > 100]
        if not high_score_items:
            return
        from app.services.catalog import Catalog
        catalog = Catalog()
        for item in high_score_items[:3]:
            book_id = item.get("bookId")
            if not book_id:
                continue
            try:
                await asyncio.wait_for(catalog.book_detail(book_id), timeout=5.0)
            except Exception:
                pass
