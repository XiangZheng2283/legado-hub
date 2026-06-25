"""Host search coordinator: unified realtime search execution.

SearchCoordinator owns the lifecycle of search jobs: task queueing, per-source
concurrency, staged execution (fast / normal / browser), result aggregation,
persistence, and snapshot rendering. It replaces the internal execution logic
that previously lived in SearchJobService while keeping the public surface
compatible with app/api/console.py and app/api/legado.py.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

from app.config import DB_PATH, HOST, PORT
from app.core.app_config import AppConfig
from app.services.aggregate_processor import AggregateProcessor
from app.services.aggregate_virtual_source import aggregate_items_for_groups
from app.services.bookshelf import record_bookshelf_items
from app.services.library_books import library_books_service
from app.services.live_acceptance import candidate_id_for, group_candidates, normalize_text
from app.source_plugins.id_codec import encode_book_id
from app.source_plugins.models import LoadedPlugin
from app.source_plugins.scheduler import get_plugin_scheduler


@dataclass
class SearchJob:
    job_id: str
    keyword: str
    page: int
    status: str  # pending, running, completed, partial, timed_out, failed, cancelled
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
    overall_timeout: bool = False
    stage_boundary: str | None = None
    source_scope: str = ""


BOOK_CACHE_TTL_DAYS = 7


@dataclass
class SearchSession:
    """In-memory search session.  Cleared on process restart."""
    job_id: str
    keyword: str
    page: int
    status: str            # "running" | "completed" | "timed_out" | "failed" | "cancelled"
    created_at: float
    deadline_at: float
    live_items: list[dict] = field(default_factory=list)
    cached_fallback_items: list[dict] = field(default_factory=list)
    aggregate_items: list[dict] = field(default_factory=list)
    candidate_groups: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    completed_sources: int = 0
    success_count: int = 0
    error_count: int = 0
    timeout_count: int = 0
    cancel_requested: bool = False
    sources: list[dict] = field(default_factory=list)
    source_scope: str = ""
    search_mode: str = "source"  # "source" | "aggregate"
    aggregate_phase_started: bool = False
    aggregate_phase_completed: bool = False


class SearchCoordinator:
    """Coordinate search jobs across configured sources with bounded concurrency."""

    MAX_EVENTS_PER_JOB = 500
    PERSIST_INTERVAL_SECONDS = 1.0
    STALE_RUNNING_SECONDS = 90.0

    def __init__(self):
        self.scheduler = get_plugin_scheduler()
        self._jobs: dict[str, SearchJob] = {}
        self._jobs_by_key: dict[tuple[str, int, str], SearchJob] = {}
        self._sessions: dict[str, SearchSession] = {}
        self._lock = asyncio.Lock()

        cfg = AppConfig.get().search
        self._task_sem = asyncio.Semaphore(max(1, cfg.task_concurrency))
        self._global_source_sem = asyncio.Semaphore(max(1, cfg.global_source_concurrency))
        self._browser_sem = asyncio.Semaphore(max(1, cfg.browser_source_concurrency))
        self._site_concurrency = max(1, cfg.site_concurrency)
        self._site_sems: dict[str, asyncio.Semaphore] = {}
        self._site_sems_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------

    @property
    def _cfg(self):
        return AppConfig.get().search

    @staticmethod
    def _normalize_keyword(keyword: str) -> str:
        return " ".join(keyword.split())

    @staticmethod
    def _scope_key(source_ids: list[str] | None) -> str:
        """Stable string key representing the requested source scope."""
        if not source_ids:
            return "__default__"
        return ",".join(sorted({str(s).strip() for s in source_ids if str(s).strip()}))

    @staticmethod
    def _positive_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    # ------------------------------------------------------------------
    # Schema / persistence helpers
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        from app.storage.db import initialize_database

        initialize_database(DB_PATH)
        return sqlite3.connect(DB_PATH)

    def _persist_job(self, job: SearchJob) -> None:
        """Persist high-level job summary only.

        Detailed source-level results live in ``search_results``; book-level
        cache lives in ``book_search_cache``. This keeps ``search_jobs`` a
        lightweight task ledger and avoids duplicating heavy payloads.
        """
        completed_at = time.time() if job.status in {"completed", "partial", "timed_out", "failed", "cancelled"} else None
        scope = job.source_scope or self._scope_key(
            [s.get("sourceId") for s in job.sources if s.get("sourceId")]
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO search_jobs
                (job_id, keyword, normalized_keyword, source_scope, page, status, created_at,
                 completed_at, result_count, source_count, attempted_count,
                 success_count, error_count, timeout_count, elapsed_ms, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    job.job_id,
                    job.keyword,
                    self._normalize_keyword(job.keyword),
                    scope,
                    job.page,
                    job.status,
                    job.created_at,
                    completed_at,
                    len(job.result.get("items", [])) if job.result else 0,
                    len(job.sources),
                    job.completed_count,
                    job.success_count,
                    job.error_count,
                    job.timeout_count,
                    job.elapsed_ms,
                ),
            )
            conn.commit()

    def _persist_source_results(self, job: SearchJob, items: list[dict]) -> None:
        """Write one row per item so search_results is a factual source of truth."""
        if not items:
            return
        with self._conn() as conn:
            for item in items:
                if not isinstance(item, dict):
                    continue
                source_id = item.get("sourceId", "")
                raw_book_url = item.get("rawBookUrl") or item.get("bookUrl", "")
                conn.execute(
                    """
                    INSERT OR REPLACE INTO search_results
                    (job_id, source_id, source_name, book_url, name, author, cover_url,
                     intro, category, word_count, status, last_chapter, score, raw_payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job.job_id,
                        source_id,
                        item.get("sourceName", ""),
                        raw_book_url,
                        item.get("name", ""),
                        item.get("author", ""),
                        item.get("coverUrl", ""),
                        item.get("intro", ""),
                        item.get("kind", ""),
                        item.get("wordCount", ""),
                        item.get("status", ""),
                        item.get("lastChapter", ""),
                        item.get("score", 0),
                        json.dumps(item, ensure_ascii=False),
                    ),
                )
            conn.commit()

    def _persist_book_cache(self, match_mode: str, items: list[dict]) -> None:
        """Write search results into book_search_cache (TTL 7 days)."""
        if not items:
            return
        expires_at = datetime.now(timezone.utc).isoformat().replace(
            "T", " "
        ).split(".")[0]  # not used directly; use SQL below
        with self._conn() as conn:
            for item in items:
                if not isinstance(item, dict):
                    continue
                source_id = item.get("sourceId", "")
                raw_book_url = item.get("rawBookUrl") or item.get("bookUrl", "")
                if not source_id or not raw_book_url:
                    continue
                name = item.get("name", "")
                author = item.get("author", "")
                norm_name = normalize_text(name)
                norm_author = normalize_text(author)
                conn.execute(
                    """
                    INSERT INTO book_search_cache
                    (match_mode, normalized_name, normalized_author, source_id, source_name,
                     raw_book_url, payload_json, score, last_seen_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now', ?))
                    ON CONFLICT(source_id, raw_book_url)
                    DO UPDATE SET
                        match_mode = excluded.match_mode,
                        normalized_name = excluded.normalized_name,
                        normalized_author = excluded.normalized_author,
                        source_name = excluded.source_name,
                        payload_json = excluded.payload_json,
                        score = excluded.score,
                        last_seen_at = datetime('now'),
                        expires_at = datetime('now', ?)
                    """,
                    (
                        match_mode, norm_name, norm_author,
                        source_id, item.get("sourceName", ""),
                        raw_book_url, json.dumps(item, ensure_ascii=False),
                        item.get("score", 0),
                        f"+{BOOK_CACHE_TTL_DAYS} days",
                        f"+{BOOK_CACHE_TTL_DAYS} days",
                    ),
                )
            conn.commit()
        # Opportunistic cleanup: remove expired entries on every write.
        self._cleanup_expired_cache()

    def _query_book_cache(
        self, keyword: str, match_mode: str = "mixed", limit: int = 200
    ) -> list[dict]:
        """Recall cached book results.

        Uses the same normalization as _persist_book_cache (normalize_text:
        lowercase + strip all whitespace) so LIKE queries match correctly.

        match_mode="mixed" searches both name and author.
        """
        normalized = normalize_text(keyword)
        if not normalized:
            return []
        if match_mode == "author":
            where_clause = "normalized_author LIKE '%' || ? || '%'"
        elif match_mode == "title":
            where_clause = "normalized_name LIKE '%' || ? || '%'"
        else:  # mixed
            where_clause = "(normalized_name LIKE '%' || ? || '%' OR normalized_author LIKE '%' || ? || '%')"
        try:
            with self._conn() as conn:
                if match_mode == "mixed":
                    rows = conn.execute(
                        f"""
                        SELECT payload_json, source_id, raw_book_url
                        FROM book_search_cache
                        WHERE {where_clause}
                          AND expires_at > datetime('now')
                        ORDER BY score DESC, last_seen_at DESC
                        LIMIT ?
                        """,
                        (normalized, normalized, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        f"""
                        SELECT payload_json, source_id, raw_book_url
                        FROM book_search_cache
                        WHERE {where_clause}
                          AND expires_at > datetime('now')
                        ORDER BY score DESC, last_seen_at DESC
                        LIMIT ?
                        """,
                        (normalized, limit),
                    ).fetchall()
        except Exception:
            return []
        items: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for (payload_json, source_id, raw_book_url) in rows:
            if not payload_json:
                continue
            dedupe_key = (source_id, raw_book_url)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            try:
                item = json.loads(payload_json)
            except Exception:
                continue
            if isinstance(item, dict):
                items.append(dict(item))
        return items

    def _query_source_cache(
        self, keyword: str, source_id: str, limit: int = 5
    ) -> list[dict]:
        """Site-level cache fallback: query book_search_cache for a specific source."""
        normalized = normalize_text(keyword)
        if not normalized or not source_id:
            return []
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT payload_json
                    FROM book_search_cache
                    WHERE source_id = ?
                      AND (normalized_name LIKE '%' || ? || '%'
                           OR normalized_author LIKE '%' || ? || '%')
                      AND expires_at > datetime('now')
                    ORDER BY score DESC, last_seen_at DESC
                    LIMIT ?
                    """,
                    (source_id, normalized, normalized, limit),
                ).fetchall()
        except Exception:
            return []
        items: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for (payload_json,) in rows:
            if not payload_json:
                continue
            try:
                item = json.loads(payload_json)
            except Exception:
                continue
            if isinstance(item, dict):
                dedupe_key = (
                    str(item.get("sourceId", source_id) or source_id),
                    str(item.get("rawBookUrl") or item.get("bookUrl", "")),
                )
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                items.append(dict(item))
        return items

    def _cleanup_expired_cache(self) -> None:
        """Remove expired entries from book_search_cache."""
        try:
            with self._conn() as conn:
                conn.execute(
                    "DELETE FROM book_search_cache WHERE expires_at < datetime('now')"
                )
                conn.commit()
        except Exception:
            pass

    def _reconstruct_job_result(self, job: SearchJob) -> None:
        """Rebuild a job's full result view from its own result rows.

        Historical job truth is ``search_results`` keyed by ``job_id``.
        """
        # Rebuild from this job's own search_results rows.
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT raw_payload_json FROM search_results
                    WHERE job_id = ?
                    """,
                    (job.job_id,),
                ).fetchall()
        except Exception:
            rows = []

        items: list[dict] = []
        errors: list[dict] = []
        for (raw,) in rows:
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            if item.get("error"):
                errors.append(item["error"])
            else:
                items.append(item)

        if items:
            candidate_groups = group_candidates(items, job.keyword)
            job.candidate_groups = candidate_groups
            job.result = {
                "items": items,
                "candidateGroups": candidate_groups,
                "debug": {
                    "sourceCount": len(job.sources),
                    "attemptedCount": job.completed_count,
                    "successCount": job.success_count,
                    "errorCount": len(errors),
                    "timeoutCount": job.timeout_count,
                    "elapsedMs": job.elapsed_ms,
                    "errors": errors,
                    "partialSuccess": job.success_count > 0 and len(errors) > 0,
                },
            }
            return

        job.result = None
        job.candidate_groups = []

    def _load_job(self, job_id: str) -> SearchJob | None:
        """Load a job from persistence into the in-memory cache.

        Full result data is rebuilt from ``search_results``.
        """
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT job_id, keyword, page, source_scope, status, created_at, completed_at,
                       result_count, source_count, attempted_count, success_count,
                       error_count, timeout_count, elapsed_ms
                FROM search_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if not row:
            return None
        scope = row[3] or "__default__"
        job = SearchJob(
            job_id=row[0],
            keyword=row[1],
            page=int(row[2] or 1),
            status=row[4],
            created_at=float(row[5] or time.time()),
            sources=[],
            result=None,
            candidate_groups=[],
            completed_count=int(row[9] or 0),
            success_count=int(row[10] or 0),
            error_count=int(row[11] or 0),
            timeout_count=int(row[12] or 0),
            elapsed_ms=int(row[13] or 0),
            source_scope=scope,
        )
        self._reconstruct_job_result(job)
        self._jobs[job.job_id] = job
        if job.status in {"pending", "running"}:
            self._jobs_by_key[
                (self._normalize_keyword(job.keyword), job.page, scope)
            ] = job
        return job


    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def submit(
        self,
        keyword: str,
        page: int = 1,
        source_ids: list[str] | None = None,
        limit: int | None = None,
        search_mode: str = "source",
    ) -> SearchJob:
        """Create a search job.  Always starts a live search.

        ``search_mode``:
        - "source" for normal source search
        - "aggregate" for AI aggregate mode (runs source search first, then aggregates)
        - "subscription" for book-card subscription search (includes official sources, no aggregate result mode)
        """
        normalized = self._normalize_keyword(keyword)
        scope = self._scope_key(source_ids)
        key = (normalized, page, scope)

        # Reuse an active session if one exists for the same key AND same mode.
        for session in self._sessions.values():
            if (
                session.status in {"running", "pending"}
                and self._normalize_keyword(session.keyword) == normalized
                and session.page == page
                and session.source_scope == scope
                and session.search_mode == search_mode
            ):
                job = self._jobs.get(session.job_id)
                if job:
                    return job

        # Create fresh job.
        job = self._create_job(keyword, page, source_ids, limit, search_mode)
        self._jobs[job.job_id] = job
        self._jobs_by_key[key] = job
        self._persist_job(job)

        # Create in-memory search session.
        overall_timeout = self._cfg.overall_timeout_seconds
        session = SearchSession(
            job_id=job.job_id,
            keyword=keyword,
            page=page,
            status="running",
            created_at=time.time(),
            deadline_at=time.time() + overall_timeout,
            sources=list(job.sources),
            source_scope=scope,
            search_mode=search_mode,
        )
        self._sessions[job.job_id] = session

        # Always start live search in the background.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            if search_mode == "aggregate":
                loop.call_soon(asyncio.create_task, self._run_aggregate_job(job))
            else:
                loop.call_soon(asyncio.create_task, self._run_job(job))
        return job

    def get_job(self, job_id: str) -> SearchJob | None:
        job = self._jobs.get(job_id)
        if job is not None:
            return job
        return self._load_job(job_id)

    def get_session(self, job_id: str) -> SearchSession | None:
        """Return the in-memory search session for a job."""
        return self._sessions.get(job_id)

    def session_snapshot(
        self,
        job_id: str,
        base_api: str | None = None,
        include_official_sources: bool = True,
    ) -> dict | None:
        """Render a session into the API response shape.

        For source mode: returns live_items + cached_fallback_items.
        For aggregate mode: returns aggregate_items only.
        """
        session = self._sessions.get(job_id)
        if not session:
            return None
        score_threshold = self._score_filter_threshold()

        is_aggregate = session.search_mode == "aggregate"

        if is_aggregate:
            # Aggregate mode: only return aggregate items in result.
            items = [
                self._reading_item(dict(i), base_api=base_api)
                for i in session.aggregate_items
                if isinstance(i, dict) and i.get("score", 0) >= score_threshold
            ]
            candidate_groups = session.candidate_groups or []
        else:
            # Source mode: return source items (live + cached fallback).
            all_source = list(session.live_items) + list(session.cached_fallback_items)
            all_source.sort(key=lambda x: (-x.get("score", 0), x.get("name", "")))
            items = []
            for item in all_source:
                if not isinstance(item, dict):
                    continue
                if item.get("score", 0) < score_threshold:
                    continue
                source_id = item.get("sourceId", "")
                plugin = self._plugin_for(source_id)
                if not include_official_sources and plugin and plugin.metadata.is_official_source():
                    continue
                items.append(self._reading_item(dict(item), base_api=base_api))
            candidate_groups = session.candidate_groups or group_candidates(items, session.keyword)
            injected_items = library_books_service.build_search_injected_items_for_groups(
                candidate_groups,
                base_api=base_api,
                score_bonus=self._cfg.official_source_bonus,
            )
            if not injected_items:
                injected_items = library_books_service.build_search_injected_items_for_keyword(
                    session.keyword,
                    base_api=base_api,
                    score_bonus=self._cfg.official_source_bonus,
                )
            items.extend([self._reading_item(dict(item), base_api=base_api) for item in injected_items])
            items.sort(key=lambda x: (-x.get("score", 0), x.get("name", ""), x.get("sourceName", "") or x.get("sourceId", "")))

        debug = {
            "sourceCount": len(session.sources),
            "attemptedCount": session.completed_sources,
            "successCount": session.success_count,
            "errorCount": session.error_count,
            "timeoutCount": session.timeout_count,
            "liveSearchCompleted": session.status not in {"running", "pending"},
            "timeoutSeconds": self._cfg.overall_timeout_seconds,
            "scoreFilter": score_threshold,
            "searchMode": session.search_mode,
            "aggregatePhaseStarted": session.aggregate_phase_started,
            "aggregatePhaseCompleted": session.aggregate_phase_completed,
        }

        return {
            "implemented": True,
            "keyword": session.keyword,
            "page": session.page,
            "jobId": session.job_id,
            "status": session.status,
            "liveSearchPending": session.status in {"running", "pending"},
            "sourceCount": len(session.sources),
            "completedCount": session.completed_sources,
            "successCount": session.success_count,
            "errorCount": session.error_count,
            "timeoutCount": session.timeout_count,
            "elapsedMs": 0,
            "result": {
                "items": items,
                "candidateGroups": candidate_groups,
                "debug": debug,
            },
            "items": items,
            "candidateGroups": candidate_groups,
            "debug": debug,
        }

    def list_jobs(self, limit: int = 20) -> list[dict]:
        limit = max(1, min(int(limit or 20), 100))
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT job_id, keyword, page, status, created_at,
                           source_count, attempted_count, success_count, error_count,
                           timeout_count, elapsed_ms, updated_at
                    FROM search_jobs
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except Exception:
            return []
        return [
            {
                "jobId": row[0],
                "keyword": row[1],
                "page": row[2],
                "status": row[3],
                "createdAt": row[4],
                "sourceCount": row[5],
                "completedCount": row[6],
                "successCount": row[7],
                "errorCount": row[8],
                "timeoutCount": row[9],
                "elapsedMs": row[10],
                "updatedAt": row[11],
            }
            for row in rows
        ]

    def get_events(self, job_id: str, after_index: int = 0) -> list[dict]:
        job = self.get_job(job_id)
        if not job:
            return []
        return job.events[after_index:]

    def _candidate_sources(self, job: SearchJob):
        """Yield candidate groups from live results and final result."""
        if job.candidate_groups:
            yield job.candidate_groups
        if job.result:
            result_items = job.result.get("candidateGroups") or []
            if result_items:
                yield result_items

    def get_candidates(self, job_id: str) -> list[dict]:
        job = self.get_job(job_id)
        if not job:
            return []
        # Merge candidate groups from all available sources so verification and
        # detail views keep working while a cached job is being refreshed.
        seen_ids: set[str] = set()
        merged: list[dict] = []
        for groups in self._candidate_sources(job):
            for group in groups:
                cid = group.get("candidateId")
                if cid and cid not in seen_ids:
                    seen_ids.add(cid)
                    merged.append(group)
        return merged

    def find_candidate(self, job_id: str, candidate_id: str) -> dict | None:
        job = self.get_job(job_id)
        if not job:
            return None
        for groups in self._candidate_sources(job):
            for group in groups:
                if group.get("candidateId") == candidate_id:
                    items = group.get("items", [])
                    return dict(items[0]) if items else None
                for item in group.get("items", []):
                    if item.get("candidateId") == candidate_id:
                        return dict(item)
        return None

    def find_candidate_group(self, job_id: str, candidate_id: str) -> dict | None:
        job = self.get_job(job_id)
        if not job:
            return None
        for groups in self._candidate_sources(job):
            for group in groups:
                if group.get("candidateId") == candidate_id:
                    return dict(group)
        return None

    def cancel_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if not job or job.status not in {"pending", "running"}:
            return False
        job.cancel_requested = True
        job.status = "cancelled"
        self._emit_event(job, {"type": "cancelled", "reason": "user_request"})
        self._persist_job(job)
        session = self._sessions.get(job_id)
        if session:
            session.cancel_requested = True
            session.status = "cancelled"
        return True

    def find_active_job(
        self, keyword: str, page: int = 1, source_ids: list[str] | None = None
    ) -> SearchJob | None:
        key = (
            self._normalize_keyword(keyword),
            page,
            self._scope_key(source_ids),
        )
        job = self._jobs_by_key.get(key)
        if job and job.status in {"pending", "running"}:
            # Refresh from DB in case a background worker completed it.
            refreshed = self.get_job(job.job_id)
            if refreshed and refreshed.status in {"pending", "running"}:
                if (
                    refreshed.status == "running"
                    and time.time() - refreshed.created_at > self.STALE_RUNNING_SECONDS
                ):
                    refreshed.status = "cancelled"
                    refreshed.cancel_requested = True
                    self._emit_event(
                        refreshed,
                        {
                            "type": "cancelled",
                            "reason": "stale_running_job",
                            "message": "后台任务超时未更新，已自动取消",
                        },
                    )
                    self._persist_job(refreshed)
                    return None
                return refreshed
        return None

    def ensure_running(self, job_id: str) -> None:
        """Start the job task if it exists in memory and is not already running."""
        job = self.get_job(job_id)
        if not job or job.status not in {"pending"}:
            return
        asyncio.create_task(self._run_job(job))

    def run_job(self, job_id: str) -> asyncio.Future[Any] | asyncio.Task[Any]:
        """Explicit entry point used by process-based workers."""
        job = self.get_job(job_id)
        if not job:
            future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
            future.set_result(None)
            return future
        return asyncio.create_task(self._run_job(job))

    # ------------------------------------------------------------------
    # Source selection and classification
    # ------------------------------------------------------------------

    def _plugin_for(self, source_id: str) -> LoadedPlugin | None:
        return self.scheduler._plugins.get(source_id)

    def _create_job(
        self,
        keyword: str,
        page: int,
        source_ids: list[str] | None,
        limit: int | None,
        search_mode: str = "source",
    ) -> SearchJob:
        plugins = self.scheduler._enabled_plugins()
        plugins = self.scheduler._search_priority_plugins(plugins)
        if source_ids:
            ids = set(source_ids)
            plugins = [p for p in plugins if p.metadata.id in ids]
        elif search_mode in {"aggregate", "subscription"}:
            # Aggregate/subscription search always includes all sources
            # (official + third-party).
            pass
        else:
            # Normal search: check global config for official source inclusion.
            include_official = self._cfg.official_source_in_normal_search
            if not include_official:
                plugins = [p for p in plugins if not p.metadata.is_official_source()]
        if limit is not None:
            plugins = plugins[: max(1, int(limit))]
        if search_mode == "subscription":
            plugins = sorted(plugins, key=lambda p: 0 if p.metadata.is_official_source() else 1)
        sources = [
            {"sourceId": p.metadata.id, "bookSourceName": p.metadata.name, "proxyMode": "auto"}
            for p in plugins
        ]
        scope = self._scope_key(source_ids)
        return SearchJob(
            job_id=str(uuid.uuid4()),
            keyword=self._normalize_keyword(keyword),
            page=page,
            status="pending",
            created_at=time.time(),
            sources=sources,
            source_scope=scope,
        )

    def resolve_sources(
        self,
        source_ids: list[str] | None = None,
        limit: int | None = None,
        search_mode: str = "source",
    ) -> list[dict]:
        """Return the source list that would be used for a fresh search.

        Mirrors the filtering logic in ``_create_job()``:
        - ``search_mode in {"aggregate", "subscription"}``: includes all sources.
        - ``search_mode="source"``: respects ``officialSourceInNormalSearch`` config.

        Currently unused — kept for potential future use.  Do NOT re-add
        callers without passing ``search_mode``.
        """
        plugins = self.scheduler._enabled_plugins()
        plugins = self.scheduler._search_priority_plugins(plugins)
        if source_ids:
            ids = set(source_ids)
            plugins = [p for p in plugins if p.metadata.id in ids]
        elif search_mode in {"aggregate", "subscription"}:
            pass  # Aggregate/subscription: include all sources.
        else:
            include_official = self._cfg.official_source_in_normal_search
            if not include_official:
                plugins = [p for p in plugins if not p.metadata.is_official_source()]
        if limit is not None:
            plugins = plugins[: max(1, int(limit))]
        if search_mode == "subscription":
            plugins = sorted(plugins, key=lambda p: 0 if p.metadata.is_official_source() else 1)
        return [
            {"sourceId": p.metadata.id, "bookSourceName": p.metadata.name, "proxyMode": "auto"}
            for p in plugins
        ]

    def _classify_sources(self, sources: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
        fast: list[dict] = []
        normal: list[dict] = []
        browser: list[dict] = []
        for src in sources:
            plugin = self._plugin_for(src.get("sourceId", ""))
            if plugin is None:
                fast.append(src)
                continue
            meta = plugin.metadata
            is_browser = (meta.browser or {}).get("mode") in {"required", "optional"}
            is_search_provider = meta.uses_search_provider("search")
            proxy_required = bool((meta.proxy or {}).get("required"))
            if is_browser or is_search_provider:
                browser.append(src)
            elif proxy_required:
                normal.append(src)
            else:
                fast.append(src)
        return fast, normal, browser

    # ------------------------------------------------------------------
    # Concurrency helpers
    # ------------------------------------------------------------------

    def _site_key(self, plugin: LoadedPlugin | None) -> str:
        if plugin and plugin.metadata.domains:
            return plugin.metadata.domains[0]
        return plugin.metadata.id if plugin else ""

    async def _acquire_site_sem(self, plugin: LoadedPlugin | None) -> asyncio.Semaphore:
        key = self._site_key(plugin)
        sem = self._site_sems.get(key)
        if sem is None:
            async with self._site_sems_lock:
                sem = self._site_sems.get(key)
                if sem is None:
                    sem = asyncio.Semaphore(self._site_concurrency)
                    self._site_sems[key] = sem
        return sem

    # ------------------------------------------------------------------
    # Execution core
    # ------------------------------------------------------------------

    def _schedule_aggregate_preprocessing(self, aggregate_items: list[dict]) -> None:
        """Best-effort: enqueue top aggregate items for background chapter processing.

        Processes the first 3 chapters of the top 3 aggregate items.
        Fire-and-forget — does not block the search return.
        """
        PREPROCESS_ITEMS = 3
        PREPROCESS_CHAPTERS = 3

        async def _preprocess():
            from app.services.catalog import Catalog
            from app.services.aggregate_processor import AggregateProcessor
            processor = AggregateProcessor()
            catalog = Catalog()
            for agg_item in aggregate_items[:PREPROCESS_ITEMS]:
                try:
                    book_id = agg_item.get("bookId", "")
                    if not book_id:
                        continue
                    payload_str = agg_item.get("rawBookUrl", "")
                    if not payload_str:
                        continue
                    from app.services.aggregate_virtual_source import unpack_aggregate_book_url
                    payload = unpack_aggregate_book_url(payload_str)
                    enqueue_result = processor.enqueue_book(book_id, payload)
                    if not enqueue_result.get("queued"):
                        continue
                    # Fetch TOC and register chapters.
                    toc_result = await catalog.toc(book_id)
                    chapters = toc_result.get("chapters", [])
                    if chapters:
                        processor.register_toc(book_id, payload, chapters)
                    # Process first N chapters.
                    for ch in chapters[:PREPROCESS_CHAPTERS]:
                        try:
                            await processor._process_chapter(catalog, ch)
                        except Exception:
                            continue
                except Exception:
                    continue

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_preprocess())
        except RuntimeError:
            pass

    async def _run_aggregate_job(self, job: SearchJob) -> None:
        """Run aggregate mode: source search first, then AI aggregation.

        Phase 1: normal source search (same as _run_job).
        Phase 2: aggregate the source results into AI aggregate items.
        """
        session = self._sessions.get(job.job_id)
        if session:
            session.aggregate_phase_started = False
            session.aggregate_phase_completed = False

        # Phase 1: run the normal source search.
        async with self._task_sem:
            await self._run_job_inner(job)

        # Phase 2: aggregate the source results.
        session = self._sessions.get(job.job_id)
        if not session or job.cancel_requested:
            return

        session.aggregate_phase_started = True
        self._emit_event(
            job,
            {
                "type": "aggregate_start",
                "message": "开始 AI 聚合阶段",
                "sourceItemCount": len(session.live_items) + len(session.cached_fallback_items),
            },
        )

        try:
            all_source_items = session.live_items + session.cached_fallback_items
            candidate_groups = group_candidates(all_source_items, job.keyword)
            base_api = f"http://{HOST}:{PORT}"
            aggregate_items = aggregate_items_for_groups(
                candidate_groups,
                base_api=base_api,
                plugins=getattr(self.scheduler, "_plugins", None),
            )
            # Tag aggregate items.
            for item in aggregate_items:
                if isinstance(item, dict):
                    item["displayType"] = "aggregate"
                    item["resultKind"] = "aggregate"
                    item.pop("freshness", None)
                    item.pop("resultSource", None)
                    item.pop("cacheHit", None)

            session.aggregate_items = aggregate_items
            session.aggregate_phase_completed = True

            self._emit_event(
                job,
                {
                    "type": "aggregate_done",
                    "message": f"AI 聚合完成，生成 {len(aggregate_items)} 条聚合结果",
                    "aggregateItemCount": len(aggregate_items),
                },
            )

            # Best-effort preprocessing: enqueue top aggregate items for
            # background chapter processing so users see fewer PLACEHOLDERs.
            try:
                self._schedule_aggregate_preprocessing(aggregate_items)
            except Exception:
                pass  # preprocessing failure should never block the search
        except Exception as exc:
            session.aggregate_phase_completed = True
            self._emit_event(
                job,
                {
                    "type": "aggregate_error",
                    "message": f"AI 聚合失败: {exc}",
                    "error": str(exc),
                },
            )

    async def _run_job(self, job: SearchJob) -> None:
        async with self._task_sem:
            await self._run_job_inner(job)

    async def _run_job_inner(self, job: SearchJob) -> None:
        if job.status == "cancelled":
            self._persist_job(job)
            return

        job.status = "running"
        start_time = time.perf_counter()
        job._start_time = start_time  # type: ignore[attr-defined]

        # Update session status.
        session = self._sessions.get(job.job_id)
        if session:
            session.status = "running"

        all_items: list[dict] = []
        errors: list[dict] = []
        last_persist = start_time

        sources = job.sources
        fast_sources, normal_sources, browser_sources = self._classify_sources(sources)

        self._emit_event(
            job,
            {
                "type": "stage_start",
                "stage": "fast",
                "sourceCount": len(fast_sources),
            },
        )

        # Fast stage: bounded by first_result_timeout_seconds.
        fast_deadline = start_time + self._cfg.first_result_timeout_seconds
        fast_items, fast_errors, fast_remaining = await self._run_stage(
            job,
            fast_sources,
            stage_name="fast",
            timeout=self._cfg.fast_source_timeout_seconds,
            deadline=min(fast_deadline, start_time + self._cfg.overall_timeout_seconds),
            browser=False,
        )
        all_items.extend(fast_items)
        errors.extend(fast_errors)
        last_persist = await self._maybe_persist(job, all_items, errors, start_time, last_persist)
        if job.overall_timeout or job.cancel_requested:
            await self._finalize_job(job, all_items, errors, start_time)
            return

        # Normal stage: non-browser sources plus any fast sources that did not
        # finish within the fast stage deadline.
        normal_sources = normal_sources + fast_remaining
        self._emit_event(
            job,
            {
                "type": "stage_start",
                "stage": "normal",
                "sourceCount": len(normal_sources),
            },
        )
        overall_deadline = start_time + self._cfg.overall_timeout_seconds
        normal_items, normal_errors, normal_remaining = await self._run_stage(
            job,
            normal_sources,
            stage_name="normal",
            timeout=self._cfg.source_timeout_seconds,
            deadline=overall_deadline,
            browser=False,
        )
        all_items.extend(normal_items)
        errors.extend(normal_errors)
        last_persist = await self._maybe_persist(
            job, all_items, errors, start_time, last_persist
        )
        if job.overall_timeout or job.cancel_requested:
            await self._finalize_job(job, all_items, errors, start_time)
            return

        # Browser / search-provider stage, plus any normal sources that did not
        # finish in time.
        browser_sources = browser_sources + normal_remaining
        self._emit_event(
            job,
            {
                "type": "stage_start",
                "stage": "browser",
                "sourceCount": len(browser_sources),
            },
        )
        browser_items, browser_errors, _browser_remaining = await self._run_stage(
            job,
            browser_sources,
            stage_name="browser",
            timeout=self._cfg.browser_search_timeout_seconds,
            deadline=overall_deadline,
            browser=True,
        )
        all_items.extend(browser_items)
        errors.extend(browser_errors)

        await self._finalize_job(job, all_items, errors, start_time)

    def _stage_boundary_event_type(
        self, job: SearchJob, deadline: float, stage_name: str
    ) -> tuple[str, str]:
        """Return (event_type, stop_reason) for a deadline reached in _run_stage.

        A stage_boundary event means this individual stage's time budget was
        reached; the job continues with the remaining sources in later stages.
        An overall_timeout event means the whole job's overall timeout was
        reached and the job will stop.
        """
        overall_deadline = job._start_time + self._cfg.overall_timeout_seconds
        if abs(deadline - overall_deadline) < 0.001:
            return "overall_timeout", "overall_deadline"
        return "stage_boundary", f"{stage_name}_boundary"

    def _emit_stage_boundary_event(
        self,
        job: SearchJob,
        stage_name: str,
        deadline: float,
    ) -> None:
        event_type, reason = self._stage_boundary_event_type(job, deadline, stage_name)
        if event_type == "overall_timeout":
            job.overall_timeout = True
        else:
            job.stage_boundary = stage_name
        self._emit_event(
            job,
            {
                "type": event_type,
                "stage": stage_name,
                "reason": reason,
                "elapsedMs": int((time.perf_counter() - job._start_time) * 1000),
            },
        )

    async def _run_stage(
        self,
        job: SearchJob,
        sources: list[dict],
        stage_name: str,
        timeout: float,
        deadline: float,
        browser: bool,
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Run one stage.  Returns (items, errors, remaining_sources).

        If the stage hits its own deadline (not the overall job deadline), the
        unprocessed sources are returned so the caller can feed them into the
        next stage.  Only the overall job deadline is allowed to stop the whole
        search.
        """
        items: list[dict] = []
        errors: list[dict] = []
        if not sources or job.cancel_requested:
            return items, errors, []

        if time.perf_counter() >= deadline:
            self._emit_stage_boundary_event(job, stage_name, deadline)
            return items, errors, list(sources)

        remaining = list(sources)
        pending: set[asyncio.Task] = set()
        task_to_source: dict[asyncio.Task, dict] = {}

        async def run_one(src_info: dict) -> dict:
            plugin = self._plugin_for(src_info.get("sourceId", ""))
            async with self._global_source_sem:
                site_sem = await self._acquire_site_sem(plugin)
                async with site_sem:
                    if browser:
                        async with self._browser_sem:
                            return await self._search_one(src_info, job.keyword, job.page, timeout)
                    return await self._search_one(src_info, job.keyword, job.page, timeout)

        def start_next() -> None:
            while remaining and len(pending) < self._cfg.global_source_concurrency:
                src_info = remaining.pop(0)
                task = asyncio.create_task(run_one(src_info))
                pending.add(task)
                task_to_source[task] = src_info

        start_next()
        while pending:
            if job.cancel_requested:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                pending = set()
                break

            now = time.perf_counter()
            if now >= deadline:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                remaining.extend(task_to_source.pop(task, {}) for task in pending)
                pending = set()
                self._emit_stage_boundary_event(job, stage_name, deadline)
                break

            remaining_timeout = deadline - now
            done, pending = await asyncio.wait(
                pending,
                return_when=asyncio.FIRST_COMPLETED,
                timeout=max(0.0, remaining_timeout),
            )
            if not done:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                remaining.extend(task_to_source.pop(task, {}) for task in pending)
                pending = set()
                self._emit_stage_boundary_event(job, stage_name, deadline)
                break

            for task in done:
                task_to_source.pop(task, None)
                result = task.result()
                self._process_source_result(job, result, items, errors)
            start_next()

        # Completed or cancelled: any unstarted sources are returned so later
        # stages can still attempt them unless the overall deadline has already
        # been reached (caller checks job.overall_timeout).
        return items, errors, remaining

    async def _search_one(
        self, src_info: dict, keyword: str, page: int, timeout: float
    ) -> dict:
        """Run a single source search with dual timeout (single-request model).

        Uses asyncio.shield so the original network request is NOT cancelled
        at soft timeout — it continues running in the background.  Only one
        actual request is made per source.

        t=0:       start task
        t=soft:    if no result yet → cache fallback, but task keeps running
        t=hard:    if still no result → cancel task, keep cache fallback
        t<hard:    if real result arrives → override cache, freshness=live
        """
        source_id = src_info.get("sourceId", "")
        soft = self._cfg.source_soft_timeout_seconds
        hard = min(timeout, self._cfg.source_hard_timeout_seconds)

        task = asyncio.create_task(
            self.scheduler.search_one(source_id, keyword, page)
        )

        # Phase 1: wait up to soft timeout.
        try:
            result = await asyncio.wait_for(asyncio.shield(task), timeout=soft)
            result["source"] = src_info
            return result
        except asyncio.TimeoutError:
            pass  # soft timeout, continue — task is NOT cancelled
        except Exception as exc:
            return self._error_result(src_info, exc)

        # Soft timeout reached: try cache fallback.
        cache_items = self._query_source_cache(keyword, source_id)
        if cache_items:
            for ci in cache_items:
                ci.setdefault("sourceId", source_id)
                ci.setdefault("sourceName", src_info.get("bookSourceName", ""))
                ci["displayType"] = "source"
                ci["freshness"] = "cached"
                self._score_search_item(ci, keyword)

        # Phase 2: wait remaining time for the SAME task.
        remaining = max(0, hard - soft)
        if remaining <= 0:
            task.cancel()
            if cache_items:
                return {"source": src_info, "items": cache_items, "_cache_fallback": True}
            return self._timeout_result(src_info, hard)

        try:
            result = await asyncio.wait_for(asyncio.shield(task), timeout=remaining)
            # Real result arrived: override cache fallback.
            result["source"] = src_info
            return result
        except asyncio.TimeoutError:
            task.cancel()
            if cache_items:
                return {"source": src_info, "items": cache_items, "_cache_fallback": True}
            return self._timeout_result(src_info, hard)
        except Exception as exc:
            task.cancel()
            if cache_items:
                return {"source": src_info, "items": cache_items, "_cache_fallback": True}
            return self._error_result(src_info, exc)

    def _timeout_result(self, src_info: dict, timeout: float) -> dict:
        source_id = src_info.get("sourceId", "")
        return {
            "source": src_info,
            "items": [],
            "error": {
                "sourceId": source_id,
                "stage": "search",
                "code": "PLUGIN_TIMEOUT",
                "message": "timeout",
                "url": "",
                "proxyUsed": False,
            },
            "latencyMs": int(timeout * 1000),
            "proxyUsed": False,
        }

    def _error_result(self, src_info: dict, exc: Exception) -> dict:
        source_id = src_info.get("sourceId", "")
        return {
            "source": src_info,
            "items": [],
            "error": {
                "sourceId": source_id,
                "stage": "search",
                "code": getattr(exc, "code", "PLUGIN_RUNTIME_ERROR"),
                "message": str(exc),
                "url": getattr(exc, "url", "") or "",
                "proxyUsed": False,
            },
            "latencyMs": 0,
            "proxyUsed": False,
        }

    def _process_source_result(
        self,
        job: SearchJob,
        result: dict,
        all_items: list[dict],
        errors: list[dict],
    ) -> None:
        src_info = result.get("source") or {"sourceId": result.get("error", {}).get("sourceId", "")}
        source_id = src_info.get("sourceId", "") if isinstance(src_info, dict) else ""
        source_name = src_info.get("bookSourceName", "") if isinstance(src_info, dict) else ""
        items = [dict(item) for item in result.get("items", []) if isinstance(item, dict)]
        err = result.get("error")
        is_cache_fallback = result.get("_cache_fallback", False)

        job.completed_count += 1
        if err:
            errors.append(err)
            if "timeout" in str(err.get("error", "")).lower() or err.get("code") == "PLUGIN_TIMEOUT":
                job.timeout_count += 1

        if items:
            job.success_count += 1
            for item in items:
                item.setdefault("sourceId", source_id)
                item.setdefault("sourceName", source_name)
                # If items came from _search_one cache fallback, they already
                # have displayType/freshness set. Otherwise tag as live.
                if not is_cache_fallback:
                    item.setdefault("displayType", "source")
                    item.setdefault("freshness", "live")
                self._score_search_item(item, job.keyword)
                self._emit_event(
                    job,
                    {
                        "type": "result",
                        "sourceId": source_id,
                        "sourceName": source_name,
                        "item": item,
                    },
                )
            all_items.extend(items)
            job.candidate_groups = group_candidates(all_items, job.keyword)

            # Push items into session.
            session = self._sessions.get(job.job_id)
            if session:
                live_only = [i for i in items if i.get("freshness") == "live"]
                cached_only = [i for i in items if i.get("freshness") == "cached"]
                session.live_items.extend(live_only)
                session.cached_fallback_items.extend(cached_only)
                session.candidate_groups = job.candidate_groups

        status_label = "成功"
        if err:
            status_label = "超时" if "timeout" in str(err.get("error", "")).lower() else "失败"
        elif not items:
            status_label = "无结果"
        if is_cache_fallback and items:
            status_label = "缓存补位"

        self._emit_event(
            job,
            {
                "type": "source_complete",
                "sourceId": source_id,
                "sourceName": source_name,
                "status": "error" if err else ("cache_fallback" if is_cache_fallback else "success"),
                "statusLabel": status_label,
                "resultCount": len(items),
                "latencyMs": result.get("latencyMs", 0),
                "proxyUsed": result.get("proxyUsed", False),
                "error": err,
                "completedCount": job.completed_count,
                "sourceCount": len(job.sources),
                "message": (
                    f"{source_name or source_id} {status_label}"
                    f"，返回 {len(items)} 条结果，耗时 {result.get('latencyMs', 0)}ms"
                    f"（{job.completed_count}/{len(job.sources)}）"
                ),
            },
        )

    async def _maybe_persist(
        self,
        job: SearchJob,
        all_items: list[dict],
        errors: list[dict],
        start_time: float,
        last_persist: float,
    ) -> float:
        now = time.perf_counter()
        if now - last_persist >= self.PERSIST_INTERVAL_SECONDS:
            self._update_partial_result(job, all_items, errors, start_time)
            self._persist_job(job)
            # Sync session counters.
            session = self._sessions.get(job.job_id)
            if session:
                session.completed_sources = job.completed_count
                session.success_count = job.success_count
                session.error_count = job.error_count
                session.timeout_count = job.timeout_count
            return now
        return last_persist

    def _update_partial_result(
        self,
        job: SearchJob,
        all_items: list[dict],
        errors: list[dict],
        start_time: float,
    ) -> None:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        source_items = self._source_result_items(list(all_items))
        job.result = {
            "implemented": True,
            "keyword": job.keyword,
            "page": job.page,
            "items": source_items,
            "candidateGroups": job.candidate_groups,
            "debug": {
                "sourceCount": len(job.sources),
                "attemptedCount": job.completed_count,
                "successCount": job.success_count,
                "errorCount": len(errors),
                "timeoutCount": job.timeout_count,
                "elapsedMs": elapsed_ms,
                "runningSnapshot": True,
            },
        }

    async def _finalize_job(
        self,
        job: SearchJob,
        all_items: list[dict],
        errors: list[dict],
        start_time: float,
    ) -> None:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        job.elapsed_ms = elapsed_ms
        job.error_count = len(errors)

        source_items = self._source_result_items(all_items)
        record_bookshelf_items(source_items)

        stop_reason = "all_done"
        if job.cancel_requested or job.status == "cancelled":
            stop_reason = "cancelled"
        elif job.completed_count >= len(job.sources):
            stop_reason = "all_done"
        elif job.overall_timeout:
            stop_reason = "overall_deadline"
        elif job.success_count > 0:
            # Should not normally be reached: leftover sources are carried forward
            # until completed or overall_timeout.  Keep as a safe fallback with a
            # clear reason rather than inventing a new terminal status.
            stop_reason = "early_stop_with_results"
        elif job.timeout_count > 0:
            stop_reason = "source_timeout"
        elif len(errors) > 0:
            stop_reason = "source_error"

        response = {
            "implemented": True,
            "keyword": job.keyword,
            "page": job.page,
            "items": source_items,
            "candidateGroups": job.candidate_groups,
            "debug": {
                "sourceCount": len(job.sources),
                "attemptedCount": job.completed_count,
                "successCount": job.success_count,
                "errorCount": len(errors),
                "timeoutCount": job.timeout_count,
                "elapsedMs": elapsed_ms,
                "errors": errors,
                "stopReason": stop_reason,
                "stageBoundary": job.stage_boundary,
                "overallTimeout": job.overall_timeout,
            },
        }
        job.result = response

        if job.cancel_requested or job.status == "cancelled":
            job.status = "cancelled"
        elif job.completed_count >= len(job.sources):
            job.status = "completed"
        elif job.overall_timeout:
            job.status = "timed_out"
        elif job.success_count > 0:
            # Defensive fallback: the job produced valid results but stopped
            # before every source reached a terminal state for an unexpected
            # reason.  Treat it as completed since it is not a failure.
            job.status = "completed"
        elif len(errors) > 0 or job.timeout_count > 0:
            job.status = "failed"
        else:
            job.status = "failed"

        # Once the job is terminal, clear transient state.
        # (cached_snapshot field removed in this refactor)

        self._emit_event(
            job,
            {
                "type": "done",
                "status": job.status,
                "stopReason": stop_reason,
                "elapsedMs": elapsed_ms,
                "debug": response["debug"],
            },
        )
        self._persist_job(job)
        self._persist_source_results(job, source_items)
        self._persist_book_cache("mixed", source_items)

        # Finalize the in-memory session.
        session = self._sessions.get(job.job_id)
        if session:
            session.status = job.status
            session.completed_sources = job.completed_count
            session.success_count = job.success_count
            session.error_count = job.error_count
            session.timeout_count = job.timeout_count

        self._jobs_by_key.pop(
            (
                self._normalize_keyword(job.keyword),
                job.page,
                job.source_scope or self._scope_key(
                    [s.get("sourceId") for s in job.sources if s.get("sourceId")]
                ),
            ),
            None,
        )

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _emit_event(self, job: SearchJob, event: dict) -> None:
        job.events.append(event)
        if len(job.events) > self.MAX_EVENTS_PER_JOB:
            job.events = job.events[-self.MAX_EVENTS_PER_JOB :]

    # ------------------------------------------------------------------
    # Scoring and item normalization
    # ------------------------------------------------------------------

    def _score_search_item(self, item: dict, keyword: str) -> dict:
        """Score a search result with mixed name+author matching.

        Weights (per document):
        - exact title match: +200
        - title contains: +100
        - exact author match: +80
        - author contains: +40
        - both title+author hit: +50 bonus
        - cached fallback penalty: -30
        """
        item.setdefault("candidateId", candidate_id_for(item))
        item.setdefault("fetchedAt", datetime.now(timezone.utc).isoformat())
        score = 0
        name = normalize_text(item.get("name", ""))
        author = normalize_text(item.get("author", ""))
        kw = normalize_text(keyword)

        title_hit = False
        author_hit = False

        if kw:
            if kw == name:
                score += 200
                title_hit = True
            elif kw in name:
                score += 100
                title_hit = True
            if author:
                if kw == author:
                    score += 80
                    author_hit = True
                elif kw in author:
                    score += 40
                    author_hit = True

        # Both title and author hit: extra bonus
        if title_hit and author_hit:
            score += 50

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

        # Cached fallback items get a penalty so they sort below live results.
        if item.get("freshness") == "cached":
            score = max(0, score - 30)

        # Official source bonus.
        if self._is_official_source_id(item.get("sourceId", "")):
            score += self._cfg.official_source_bonus
            item.setdefault("extra", {})
            if isinstance(item["extra"], dict):
                item["extra"].setdefault("officialSourcePriority", True)
        item["score"] = score
        return item

    def _source_result_items(self, items: list[dict]) -> list[dict]:
        base_api = f"http://{HOST}:{PORT}"
        source_items = [dict(item) for item in items if isinstance(item, dict)]
        source_items.sort(
            key=lambda item: (
                -item.get("score", 0),
                item.get("name", ""),
                item.get("sourceName", "") or item.get("sourceId", ""),
            )
        )
        now = datetime.now(timezone.utc).isoformat()
        for item in source_items:
            item.setdefault("fetchedAt", now)
            source_id = item.get("sourceId", "")
            raw_book_url = item.get("rawBookUrl") or item.get("bookUrl", "")
            if raw_book_url and "/api/legado/book/" not in raw_book_url:
                book_id = encode_book_id(source_id, raw_book_url)
                item["bookId"] = book_id
                item["rawBookUrl"] = raw_book_url
                item["bookUrl"] = f"{base_api}/api/legado/book/{book_id}"
        return source_items

    # ------------------------------------------------------------------
    # Snapshot rendering (used by console/legado APIs)
    # ------------------------------------------------------------------

    def _score_filter_threshold(self) -> int:
        try:
            val = AppConfig.get().search.score_filter
            if isinstance(val, int) and val >= 0:
                return val
        except Exception:
            pass
        return 100

    def _filter_items_by_score(self, items: list[dict]) -> list[dict]:
        threshold = self._score_filter_threshold()
        return [item for item in items if item.get("score", 0) >= threshold]

    def _filter_candidate_groups(self, groups: list[dict]) -> list[dict]:
        threshold = self._score_filter_threshold()
        filtered: list[dict] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            items = [
                item for item in group.get("items", [])
                if isinstance(item, dict) and item.get("score", 0) >= threshold
            ]
            if not items:
                continue
            filtered.append({**group, "items": items})
        return filtered

    # ------------------------------------------------------------------
    # Snapshot rendering (used by snapshot() below)
    # ------------------------------------------------------------------

    def snapshot(
        self,
        job: SearchJob,
        base_api: str | None = None,
        include_official_sources: bool = True,
    ) -> dict:
        score_threshold = self._score_filter_threshold()
        candidate_groups = self._filter_candidate_groups(job.candidate_groups)
        raw_items: list[dict] = []
        if job.result and job.result.get("items"):
            raw_items = [
                dict(item) for item in job.result.get("items", [])
                if isinstance(item, dict) and item.get("score", 0) >= score_threshold
            ]
        if not raw_items and candidate_groups:
            for group in candidate_groups:
                for item in group.get("items", []):
                    if isinstance(item, dict):
                        raw_items.append(dict(item))

        items: list[dict] = []
        for item in raw_items:
            source_id = item.get("sourceId", "")
            plugin = self._plugin_for(source_id)
            if not include_official_sources and plugin and plugin.metadata.is_official_source():
                continue
            reading_item = self._reading_item(item, base_api=base_api)
            reading_item["resultSource"] = "live"
            reading_item["cacheHit"] = False
            items.append(reading_item)

        injected_items = library_books_service.build_search_injected_items_for_groups(
            candidate_groups,
            base_api=base_api,
            score_bonus=self._cfg.official_source_bonus,
        )
        if not injected_items:
            injected_items = library_books_service.build_search_injected_items_for_keyword(
                job.keyword,
                base_api=base_api,
                score_bonus=self._cfg.official_source_bonus,
            )
        for item in injected_items:
            reading_item = self._reading_item(dict(item), base_api=base_api)
            reading_item["resultSource"] = "library"
            reading_item["cacheHit"] = False
            items.append(reading_item)

        official_debug = self._official_source_debug_info(raw_items, include_official_sources)
        debug = {
            "sourceCount": len(job.sources),
            "attemptedCount": job.completed_count,
            "successCount": job.success_count,
            "errorCount": job.error_count,
            "timeoutCount": job.timeout_count,
            "elapsedMs": job.elapsed_ms,
            "partial": job.status in {"pending", "running"},
            "scoreFilter": score_threshold,
        }
        debug.update(official_debug)
        return {
            "implemented": True,
            "keyword": job.keyword,
            "page": job.page,
            "jobId": job.job_id,
            "status": job.status,
            "items": items,
            "candidateGroups": candidate_groups,
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

    def _is_official_source_id(self, source_id: str) -> bool:
        plugin = self._plugin_for(source_id)
        return bool(plugin and plugin.metadata.is_official_source())

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
            plugin = self._plugin_for(source_id)
            if plugin and plugin.metadata.is_official_source():
                matched.append(source_id)
        matched = sorted(set(matched))
        return {
            "officialSourcesHidden": not include_official_sources,
            "officialSourcesMatched": matched,
            "officialSourcesMatchCount": len(matched),
        }
