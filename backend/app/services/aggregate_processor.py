"""Background processing for virtual aggregate books."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from app.source_plugins.id_codec import decode_chapter_id, encode_chapter_id
from app.services.aggregate_virtual_source import (
    VIRTUAL_SOURCE_ID,
    make_aggregate_chapter_url,
    primary_book_id_from_payload,
    unpack_aggregate_chapter_url,
)
from app.services.aggregate_settings import (
    DEFAULT_CONTENT_WORKFLOW,
    PROCESSING_PLACEHOLDER,
    RETRY_DELAYS_MINUTES,
    WINDOW_CHAPTER_LIMIT,
    AggregateSettingsRepository,
)
from app.services.novel_file_cache import NovelFileCache

DEFAULT_WORKFLOW = DEFAULT_CONTENT_WORKFLOW

# Error codes for chapter processing failures (plan §8.3.1).
ERROR_CODES_NO_RETRY = frozenset({"AI_BAD_REQUEST"})


def classify_error(exc: Exception) -> str:
    """Map an exception to a structured error code for retry decisions."""
    from app.ai.client import AIProviderHTTPError, AIProviderNotConfiguredError

    msg = str(exc).lower()

    # Empty content from source
    if isinstance(exc, ValueError) and "empty" in msg:
        return "SOURCE_EMPTY_CONTENT"

    # Timeout variants
    if isinstance(exc, (TimeoutError,)):
        return "SOURCE_TIMEOUT"
    try:
        import httpx
        if isinstance(exc, httpx.TimeoutException):
            return "SOURCE_TIMEOUT"
    except ImportError:
        pass

    # AI provider HTTP errors
    if isinstance(exc, AIProviderHTTPError):
        code = exc.status_code
        if code == 401:
            return "SOURCE_AUTH_REQUIRED"
        if code == 429:
            return "AI_RATE_LIMITED"
        if code == 400:
            return "AI_BAD_REQUEST"
        if code >= 500:
            return "AI_TIMEOUT"
        return "AI_TIMEOUT"

    if isinstance(exc, AIProviderNotConfiguredError):
        return "AI_BAD_REQUEST"

    # Timeout in message
    if "timeout" in msg or "timed out" in msg:
        return "SOURCE_TIMEOUT"

    if "ai_output_deviation" in msg:
        return "AI_OUTPUT_DEVIATION"

    return "AI_TIMEOUT"


def compute_next_retry_time(retry_count: int) -> str | None:
    """Return an ISO UTC timestamp for the next retry, or None if exhausted."""
    from app.services.aggregate_settings import RETRY_DELAYS_MINUTES

    if retry_count >= len(RETRY_DELAYS_MINUTES):
        return None
    delay = RETRY_DELAYS_MINUTES[retry_count]
    return (datetime.now(timezone.utc) + timedelta(minutes=delay)).isoformat()


def max_retries_reached(retry_count: int) -> bool:
    """True when the chapter has exhausted all automatic retries."""
    from app.services.aggregate_settings import RETRY_DELAYS_MINUTES

    return retry_count >= len(RETRY_DELAYS_MINUTES)


class AggregateProcessor:
    def __init__(self, db_path: str | Path | None = None, *, ai_service: Any = None):
        from app.config import DB_PATH

        self.db_path = Path(db_path or DB_PATH)
        self._ai_service = ai_service
        self._toc_cache: dict[str, dict] = {}

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _workflow_settings(self) -> dict:
        return AggregateSettingsRepository(self.db_path).content_workflow()

    def ai_aggregate_enabled(self) -> bool:
        settings = self._workflow_settings()
        return (
            bool(settings.get("aiEnabled"))
            and bool(settings.get("autoAggregate", True))
            and bool(settings.get("processAggregateOnRead", True))
        )

    def check_interval_minutes(self) -> int:
        settings = self._workflow_settings()
        value = int(settings.get("aggregateCheckIntervalMinutes") or 30)
        return min(max(value, 10), 1440)

    def return_only_aggregate_source(self) -> bool:
        return bool(self._workflow_settings().get("returnOnlyAggregateSource", False))

    def enqueue_book(self, aggregate_book_id: str, payload: dict[str, Any]) -> dict:
        if not self.ai_aggregate_enabled():
            return {"queued": False, "reason": "ai aggregate disabled", "bookId": aggregate_book_id}

        settings = self._workflow_settings()
        source_priority = settings.get("primarySourcePriority") or []
        primary_book_id = primary_book_id_from_payload(payload, source_priority=source_priority)
        if not primary_book_id:
            return {"queued": False, "reason": "aggregate source has no candidates", "bookId": aggregate_book_id}
        primary_source_id = primary_book_id.split(":", 1)[0] if ":" in primary_book_id else ""

        now = self._now()
        interval = self.check_interval_minutes()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO aggregate_book_tasks
                (aggregate_book_id, name, author, aggregate_payload_json, primary_book_id, primary_source_id,
                 status, interval_minutes, last_check_time, next_check_time, error_count, last_error,
                 ai_enabled, created_at, updated_at)
                VALUES (
                  ?, ?, ?, ?, ?, ?, 'active', ?,
                  COALESCE((SELECT last_check_time FROM aggregate_book_tasks WHERE aggregate_book_id = ?), NULL),
                  ?,
                  COALESCE((SELECT error_count FROM aggregate_book_tasks WHERE aggregate_book_id = ?), 0),
                  COALESCE((SELECT last_error FROM aggregate_book_tasks WHERE aggregate_book_id = ?), ''),
                  ?,
                  COALESCE((SELECT created_at FROM aggregate_book_tasks WHERE aggregate_book_id = ?), ?),
                  ?
                )
                """,
                (
                    aggregate_book_id,
                    payload.get("name", ""),
                    payload.get("author", ""),
                    json.dumps(payload, ensure_ascii=False),
                    primary_book_id,
                    primary_source_id,
                    interval,
                    aggregate_book_id,
                    now,
                    aggregate_book_id,
                    aggregate_book_id,
                    int(bool(self._workflow_settings().get("aiEnabled"))),
                    aggregate_book_id,
                    now,
                    now,
                ),
            )
            conn.commit()
        return {
            "queued": True,
            "bookId": aggregate_book_id,
            "primaryBookId": primary_book_id,
            "nextCheckTime": now,
            "intervalMinutes": interval,
        }

    def register_toc(self, aggregate_book_id: str, payload: dict[str, Any], chapters: list[dict]) -> dict:
        if not self.ai_aggregate_enabled():
            return {"registered": False, "reason": "ai aggregate disabled", "chapterCount": 0}

        primary_book_id = primary_book_id_from_payload(payload)
        source_id = primary_book_id.split(":", 1)[0] if ":" in primary_book_id else ""
        now = self._now()
        registered = 0
        new_count = 0
        updated_count = 0

        with self._conn() as conn:
            # ── build current chapter map from DB ──────────────────────
            existing_rows = conn.execute(
                "SELECT chapter_id, source_chapter_id, chapter_index, title FROM aggregate_chapter_tasks WHERE aggregate_book_id = ?",
                (aggregate_book_id,),
            ).fetchall()
            existing_by_source: dict[str, dict] = {}
            for row in existing_rows:
                existing_by_source[row[1]] = {
                    "chapterId": row[0], "sourceChapterId": row[1],
                    "chapterIndex": row[2], "title": row[3],
                }

            incoming_source_ids: set[str] = set()

            for index, chapter in enumerate(chapters, start=1):
                raw_url = chapter.get("chapterUrl", "")
                source_chapter_id = chapter.get("chapterId") or (
                    encode_chapter_id(source_id, raw_url) if source_id and raw_url else f"{aggregate_book_id}:{index}"
                )
                incoming_source_ids.add(source_chapter_id)

                aggregate_chapter_url = make_aggregate_chapter_url(
                    aggregate_book_id=aggregate_book_id,
                    source_chapter_id=source_chapter_id,
                    title=chapter.get("title", ""),
                    index=index,
                )
                chapter_id = encode_chapter_id(VIRTUAL_SOURCE_ID, aggregate_chapter_url)

                existing = existing_by_source.get(source_chapter_id)
                if existing:
                    # Chapter exists — update title/index if changed.
                    needs_update = (
                        existing["title"] != chapter.get("title", "")
                        or existing["chapterIndex"] != index
                    )
                    if needs_update:
                        conn.execute(
                            """UPDATE aggregate_chapter_tasks
                               SET title = ?, chapter_index = ?, updated_at = ?
                               WHERE chapter_id = ? AND status NOT IN ('processed', 'fallback')""",
                            (chapter.get("title", ""), index, now, existing["chapterId"]),
                        )
                        updated_count += 1
                else:
                    # New chapter.
                    conn.execute(
                        """INSERT OR IGNORE INTO aggregate_chapter_tasks
                           (chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title, status, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
                        (chapter_id, aggregate_book_id, source_chapter_id, index, chapter.get("title", ""), now, now),
                    )
                    new_count += 1
                registered += 1

            # ── handle removed chapters ───────────────────────────────
            removed_count = 0
            for src_id, info in existing_by_source.items():
                if src_id not in incoming_source_ids:
                    # Chapter no longer in primary source TOC.
                    status_row = conn.execute(
                        "SELECT status FROM aggregate_chapter_tasks WHERE chapter_id = ?",
                        (info["chapterId"],),
                    ).fetchone()
                    if status_row and status_row[0] not in ("processed", "fallback"):
                        conn.execute(
                            "DELETE FROM aggregate_chapter_tasks WHERE chapter_id = ?",
                            (info["chapterId"],),
                        )
                        removed_count += 1

            # ── update book task stats ────────────────────────────────
            conn.execute(
                """UPDATE aggregate_book_tasks
                   SET total_chapters = ?,
                       processed_chapters = (
                           SELECT COUNT(*) FROM aggregate_chapter_tasks
                           WHERE aggregate_book_id = ? AND status = 'processed'
                       ),
                       failed_chapters = (
                           SELECT COUNT(*) FROM aggregate_chapter_tasks
                           WHERE aggregate_book_id = ? AND status = 'error'
                       ),
                       updated_at = ?
                   WHERE aggregate_book_id = ?""",
                (registered, aggregate_book_id, aggregate_book_id, now, aggregate_book_id),
            )
            conn.commit()
        return {
            "registered": True, "chapterCount": registered,
            "newChapters": new_count, "updatedChapters": updated_count,
            "removedChapters": removed_count,
        }

    def list_due_books(self, limit: int = 10) -> list[dict]:
        now = self._now()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT aggregate_book_id, aggregate_payload_json, primary_book_id, interval_minutes
                FROM aggregate_book_tasks
                WHERE status IN ('active', 'error') AND (next_check_time IS NULL OR next_check_time <= ?)
                ORDER BY COALESCE(next_check_time, created_at)
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        items = []
        for aggregate_book_id, payload_json, primary_book_id, interval_minutes in rows:
            try:
                payload = json.loads(payload_json or "{}")
            except Exception:
                payload = {}
            items.append({
                "aggregateBookId": aggregate_book_id,
                "payload": payload,
                "primaryBookId": primary_book_id,
                "intervalMinutes": interval_minutes or self.check_interval_minutes(),
            })
        return items

    async def run_due_once(self, limit: int = 10) -> dict:
        if not self.ai_aggregate_enabled():
            settings = self._workflow_settings()
            reasons = []
            if not bool(settings.get("aiEnabled")):
                reasons.append("aiEnabled=false")
            if not bool(settings.get("autoAggregate", True)):
                reasons.append("autoAggregate=false")
            if not bool(settings.get("processAggregateOnRead", True)):
                reasons.append("processAggregateOnRead=false")
            return {"enabled": False, "processedBooks": 0, "dueBooks": 0,
                    "reason": "aggregate disabled: " + ", ".join(reasons)}
        due_books = self.list_due_books(limit=limit)
        processed = []
        for item in due_books:
            processed.append(await self.run_book_task(item["aggregateBookId"]))
        return {"enabled": True, "dueBooks": len(due_books),
                "processedBooks": len(processed), "items": processed}

    async def run_book_task(self, aggregate_book_id: str) -> dict:
        from app.services.book_catalog import BookCatalog

        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT aggregate_payload_json, primary_book_id, interval_minutes
                FROM aggregate_book_tasks WHERE aggregate_book_id = ?
                """,
                (aggregate_book_id,),
            ).fetchone()
        if not row:
            return {"bookId": aggregate_book_id, "success": False, "error": "aggregate task not found"}

        payload = json.loads(row[0] or "{}")
        primary_book_id = row[1] or primary_book_id_from_payload(payload)
        interval = int(row[2] or self.check_interval_minutes())
        now = self._now()
        next_check = (datetime.now(timezone.utc) + timedelta(minutes=interval)).isoformat()

        try:
            catalog = BookCatalog()
            self._clear_toc_cache()
            toc = await catalog.toc(primary_book_id)
            chapters = [dict(item) for item in toc.get("chapters", []) if isinstance(item, dict)]
            self.register_toc(aggregate_book_id, payload, chapters)
            chapter_results = []
            for chapter in self._chapters_for_processing(aggregate_book_id):
                chapter_results.append(await self._process_chapter(catalog, chapter))

            latest_chapter = chapters[-1].get("title", "") if chapters else ""
            with self._conn() as conn:
                conn.execute(
                    """
                    UPDATE aggregate_book_tasks
                    SET status = 'active', last_check_time = ?, next_check_time = ?,
                        total_chapters = ?,
                        processed_chapters = (
                            SELECT COUNT(*) FROM aggregate_chapter_tasks
                            WHERE aggregate_book_id = ? AND status = 'processed'
                        ),
                        failed_chapters = (
                            SELECT COUNT(*) FROM aggregate_chapter_tasks
                            WHERE aggregate_book_id = ? AND status = 'error'
                        ),
                        error_count = 0, last_error = '', updated_at = ?
                    WHERE aggregate_book_id = ?
                    """,
                    (now, next_check, len(chapters), aggregate_book_id, aggregate_book_id, now, aggregate_book_id),
                )
                conn.execute(
                    """
                    UPDATE book_records
                    SET last_chapter = ?, last_seen_at = ?
                    WHERE book_id = ?
                    """,
                    (latest_chapter, now, aggregate_book_id),
                )
                conn.commit()
            return {
                "bookId": aggregate_book_id,
                "success": True,
                "chapterCount": len(chapters),
                "processedChapters": len(chapter_results),
                "nextCheckTime": next_check,
            }
        except Exception as exc:
            with self._conn() as conn:
                conn.execute(
                    """
                    UPDATE aggregate_book_tasks
                    SET status = 'error', last_check_time = ?, next_check_time = ?,
                        error_count = error_count + 1, last_error = ?, updated_at = ?
                    WHERE aggregate_book_id = ?
                    """,
                    (now, next_check, str(exc), now, aggregate_book_id),
                )
                conn.commit()
            return {"bookId": aggregate_book_id, "success": False, "error": str(exc), "nextCheckTime": next_check}

    def _chapters_for_processing(self, aggregate_book_id: str, limit: int = WINDOW_CHAPTER_LIMIT) -> list[dict]:
        terminal_codes = tuple(sorted(ERROR_CODES_NO_RETRY))
        placeholders = ",".join("?" for _ in terminal_codes) if terminal_codes else "''"
        now = self._now()
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT chapter_id, source_chapter_id, title, status, chapter_index, aggregate_book_id
                FROM aggregate_chapter_tasks
                WHERE aggregate_book_id = ?
                  AND (
                    status = 'pending'
                    OR (
                      status = 'error'
                      AND (next_retry_time IS NULL OR next_retry_time <= ?)
                      AND (last_error_code IS NULL OR last_error_code NOT IN ({placeholders}))
                      AND (retry_count IS NULL OR retry_count < ?)
                    )
                  )
                ORDER BY COALESCE(chapter_index, 999999), created_at
                LIMIT ?
                """,
                (aggregate_book_id, now, *terminal_codes, len(RETRY_DELAYS_MINUTES), max(0, int(limit))),
            ).fetchall()
        return [
            {
                "chapterId": row[0],
                "sourceChapterId": row[1],
                "title": row[2],
                "status": row[3],
                "chapterIndex": row[4],
                "aggregateBookId": row[5],
            }
            for row in rows
        ]

    # ── helpers for _process_chapter ──────────────────────────────────────

    def _load_aggregate_payload(self, aggregate_book_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT aggregate_payload_json FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
                (aggregate_book_id,),
            ).fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0] or "{}")
        except Exception:
            return {}

    def _is_official_source(self, source_id: str) -> bool:
        from app.source_plugins.loader import PluginLoader
        try:
            plugins = PluginLoader().load_all()
        except Exception:
            return False
        plugin = plugins.get(source_id)
        return bool(plugin and plugin.metadata.is_official_source())

    def _candidate_sources_from_payload(self, payload: dict, primary_source_id: str) -> list[dict]:
        sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
        return [
            s for s in sources
            if isinstance(s, dict) and s.get("sourceId") and s.get("sourceId") != primary_source_id
        ]

    def _get_ai_service(self):
        if self._ai_service is not None:
            return self._ai_service

        # Build production AI service from settings only when enabled & configured.
        workflow = self._workflow_settings()
        if not bool(workflow.get("aiEnabled")):
            return None

        provider_config = AggregateSettingsRepository(self.db_path).ai_provider_config()
        base_url = str(provider_config.get("baseUrl") or "").strip()
        api_key = str(provider_config.get("apiKey") or "").strip()
        model = str(provider_config.get("model") or "").strip()
        if not base_url or not api_key or not model:
            return None

        try:
            from app.ai.client import OpenAICompatibleClient
            from app.services.aggregate_ai_service import AggregateAIService

            lexicon = None
            if bool(workflow.get("sensitiveLexiconEnabled", True)):
                raw_lex_path = workflow.get("sensitiveLexiconPath")
                if raw_lex_path:
                    from app.services.aggregate_settings import resolve_sensitive_lexicon_path

                    lex_path = resolve_sensitive_lexicon_path(raw_lex_path)
                    if not lex_path.exists():
                        logger.warning(
                            "Sensitive lexicon path does not exist: %s (resolved to %s)",
                            raw_lex_path,
                            lex_path,
                        )
                    else:
                        try:
                            from app.ai.lexicon import SensitiveLexiconScanner

                            lexicon = SensitiveLexiconScanner.from_path(lex_path)
                            logger.debug(
                                "Loaded sensitive lexicon from %s: %d words",
                                lex_path,
                                lexicon.word_count,
                            )
                        except Exception as exc:
                            logger.warning(
                                "Failed to load sensitive lexicon from %s: %s",
                                lex_path,
                                exc,
                            )
                            logger.debug("Lexicon load traceback", exc_info=True)

            client = OpenAICompatibleClient(provider_config)
            self._ai_service = AggregateAIService(client=client, lexicon=lexicon)
        except Exception:
            return None

        return self._ai_service

    async def _cached_toc(self, catalog, book_id: str) -> dict:
        if book_id in self._toc_cache:
            return self._toc_cache[book_id]
        toc = await catalog.toc(book_id)
        self._toc_cache[book_id] = toc
        return toc

    def _clear_toc_cache(self) -> None:
        self._toc_cache.clear()

    # ── previous chapter context ─────────────────────────────────────────

    def _load_previous_chapters_context(self, aggregate_book_id: str, before_index: int, count: int = 3) -> str:
        """Load the last *count* processed chapters' content (truncated) for context."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT title, processed_content FROM aggregate_chapter_tasks
                   WHERE aggregate_book_id = ? AND status IN ('processed', 'fallback')
                     AND chapter_index < ? AND processed_content IS NOT NULL AND processed_content != ''
                   ORDER BY chapter_index DESC LIMIT ?""",
                (aggregate_book_id, before_index, count),
            ).fetchall()
        parts = []
        for title, content in rows:
            # Take last ~500 chars of each chapter for continuity context.
            excerpt = (content or "")[-500:]
            parts.append(f"【{title}】\n{excerpt}")
        return "\n\n".join(reversed(parts))

    # ── core chapter processing state machine ────────────────────────────

    async def _process_chapter(self, catalog, chapter: dict) -> dict:
        """Process a single chapter through the 3-path pipeline.

        Path 1: Content is full → purify → optional AI → processed
        Path 2: Content is preview → try candidates → fallback
        Path 3: Content is empty → try candidates → error
        """
        from app.services.aggregate_alignment import (
            build_source_alignment_json,
            classify_source_content,
        )

        chapter_id = chapter["chapterId"]
        source_chapter_id = chapter.get("sourceChapterId") or chapter_id
        aggregate_book_id = chapter.get("aggregateBookId", "")
        title = chapter.get("title", "")
        chapter_index = chapter.get("chapterIndex")

        payload = self._load_aggregate_payload(aggregate_book_id)
        primary_source_id = payload.get("primarySourceId", "")
        if not primary_source_id:
            primary_source_id = source_chapter_id.split(":")[0] if ":" in source_chapter_id else ""

        try:
            result = await catalog.chapter(source_chapter_id)
            content = result.get("content", "")
            is_official = self._is_official_source(primary_source_id)
            classification = classify_source_content(
                content, source_id=primary_source_id, is_official=is_official
            )

            # ── Path 1: full content ────────────────────────────────────
            if classification["classification"] == "full":
                return await self._process_full_content(
                    catalog=catalog, chapter=chapter, content=content,
                    classification=classification, primary_source_id=primary_source_id,
                    payload=payload,
                )

            # ── Path 2: preview content → try candidates ────────────────
            if classification["classification"] == "preview":
                candidate_result = await self._try_candidate_content(
                    catalog, chapter, payload, primary_source_id
                )
                if candidate_result:
                    # Candidate found with full content → treat as full.
                    return await self._process_full_content(
                        catalog=catalog, chapter=chapter,
                        content=candidate_result["content"],
                        classification=classification,
                        primary_source_id=candidate_result["source_id"],
                        payload=payload,
                        fallback_source_id=candidate_result["source_id"],
                    )
                # No candidate → purified preview as fallback.
                purified = self._purify_content(content)
                alignment_json = build_source_alignment_json(
                    selected_content_source="preview_fallback",
                    alignment_passed=False,
                    alignment_reason="no_candidate_for_preview",
                    primary_source_id=primary_source_id,
                )
                self._write_chapter_result(
                    chapter_id=chapter_id, aggregate_book_id=aggregate_book_id,
                    title=title, chapter_index=chapter_index,
                    status="fallback", content=purified,
                    alignment_json=alignment_json,
                    fallback_source_id=primary_source_id,
                )
                return {"chapterId": chapter_id, "success": True,
                        "contentLength": len(purified), "fallback": True}

            # ── Path 3: empty → try candidates ──────────────────────────
            candidate_result = await self._try_candidate_content(
                catalog, chapter, payload, primary_source_id
            )
            if candidate_result:
                return await self._process_full_content(
                    catalog=catalog, chapter=chapter,
                    content=candidate_result["content"],
                    classification=classification,
                    primary_source_id=candidate_result["source_id"],
                    payload=payload,
                    fallback_source_id=candidate_result["source_id"],
                )
            raise ValueError("empty chapter content from all sources")

        except Exception as exc:
            return self._handle_processing_error(exc, chapter, source_chapter_id)

    async def _process_full_content(
        self, *, catalog, chapter: dict, content: str,
        classification: dict, primary_source_id: str, payload: dict,
        fallback_source_id: str = "",
    ) -> dict:
        """Path 1: Content is full. Purify → optional AI → write result."""
        from app.services.aggregate_alignment import build_source_alignment_json

        chapter_id = chapter["chapterId"]
        aggregate_book_id = chapter.get("aggregateBookId", "")
        title = chapter.get("title", "")
        chapter_index = chapter.get("chapterIndex")

        # Step 1: Always purify first.
        purified = self._purify_content(content)

        # Step 2: If AI enabled, try AI processing.
        selected_content = purified
        ai_model = ""
        ai_self_score = 0.0
        ai_prompt_tokens = 0
        ai_completion_tokens = 0
        ai_total_tokens = 0
        ai_latency_ms = 0

        ai_service = self._get_ai_service()
        if ai_service:
            try:
                book_name = self._aggregate_book_name_from_cache(aggregate_book_id)
                prev_ctx = self._load_previous_chapters_context(
                    aggregate_book_id, chapter_index or 999
                )
                if fallback_source_id:
                    # Content came from a candidate source → use third-party AI path.
                    ai_result = await ai_service.process_third_party_primary(
                        book_name=book_name, author="", title=title,
                        content=purified, source_id=primary_source_id,
                        previous_context=prev_ctx,
                    )
                else:
                    # Content from primary source → use official AI path.
                    ai_result = await ai_service.process_official_full(
                        book_name=book_name, author="", title=title,
                        content=purified,
                    )
                if ai_result.get("status") in ("processed", "fallback"):
                    selected_content = ai_result.get("content", purified)
                    ai_model = ai_result.get("aiModel", "")
                    ai_self_score = ai_result.get("selfScore", 0.0)
                    ai_prompt_tokens = ai_result.get("promptTokens", 0)
                    ai_completion_tokens = ai_result.get("completionTokens", 0)
                    ai_total_tokens = ai_result.get("totalTokens", 0)
                    ai_latency_ms = ai_result.get("latencyMs", 0)
            except Exception:
                pass  # AI failed → keep purified content.

        # Step 3: Write result.
        status = "fallback" if fallback_source_id else "processed"
        alignment_json = build_source_alignment_json(
            selected_content_source="official" if not fallback_source_id else "candidate",
            alignment_passed=True,
            alignment_reason="full_content_processed",
            primary_source_id=primary_source_id,
            candidate_source_id=fallback_source_id or "",
        )
        self._write_chapter_result(
            chapter_id=chapter_id, aggregate_book_id=aggregate_book_id,
            title=title, chapter_index=chapter_index,
            status=status, content=selected_content,
            alignment_json=alignment_json,
            ai_model=ai_model,
            deviation_score=ai_self_score if ai_model else 0.0,
            ai_self_score=ai_self_score,
            ai_prompt_tokens=ai_prompt_tokens,
            ai_completion_tokens=ai_completion_tokens,
            ai_total_tokens=ai_total_tokens,
            ai_latency_ms=ai_latency_ms,
            fallback_source_id=fallback_source_id or primary_source_id,
        )
        return {"chapterId": chapter_id, "success": True,
                "contentLength": len(selected_content),
                "fallback": bool(fallback_source_id)}

    async def _try_candidate_content(
        self, catalog, chapter: dict, payload: dict, primary_source_id: str
    ) -> dict | None:
        """Try to get full content from candidate sources.

        Simplified matching: find the same chapter index in candidate's TOC.
        Returns {"content": str, "source_id": str} or None.
        """
        candidates = self._candidate_sources_from_payload(payload, primary_source_id)
        target_index = chapter.get("chapterIndex", 1)
        target_title = chapter.get("title", "")

        for cand in candidates[:3]:
            cand_source_id = cand.get("sourceId", "")
            cand_book_id = cand.get("bookId", "")
            if not cand_source_id or not cand_book_id:
                continue
            try:
                cand_toc = await self._cached_toc(catalog, cand_book_id)
                cand_chapters = [c for c in cand_toc.get("chapters", []) if isinstance(c, dict)]
            except Exception:
                continue

            # Find matching chapter by index or title.
            matched_ch = None
            for ch in cand_chapters:
                if ch.get("index") == target_index:
                    matched_ch = ch
                    break
            if not matched_ch and target_title:
                for ch in cand_chapters:
                    if target_title in (ch.get("title") or ""):
                        matched_ch = ch
                        break
            if not matched_ch:
                continue

            cand_chapter_id = matched_ch.get("chapterId", "")
            if not cand_chapter_id and matched_ch.get("chapterUrl"):
                from app.source_plugins.id_codec import encode_chapter_id
                cand_chapter_id = encode_chapter_id(cand_source_id, matched_ch["chapterUrl"])
            if not cand_chapter_id:
                continue

            try:
                cand_result = await catalog.chapter(cand_chapter_id)
                cand_content = cand_result.get("content", "")
                from app.services.aggregate_alignment import classify_source_content
                is_official = self._is_official_source(cand_source_id)
                cls = classify_source_content(cand_content, source_id=cand_source_id, is_official=is_official)
                if cls["classification"] == "full":
                    return {"content": cand_content, "source_id": cand_source_id}
            except Exception:
                continue

        return None

    def _handle_processing_error(self, exc: Exception, chapter: dict, source_chapter_id: str) -> dict:
        from app.services.aggregate_alignment import build_source_alignment_json

        now = self._now()
        chapter_id = chapter["chapterId"]
        aggregate_book_id = chapter.get("aggregateBookId", "")
        error_code = classify_error(exc)
        alignment_json = build_source_alignment_json(
            selected_content_source="none",
            alignment_passed=False,
            alignment_reason=error_code,
        )
        with self._conn() as conn:
            row = conn.execute(
                "SELECT retry_count FROM aggregate_chapter_tasks WHERE chapter_id = ?",
                (chapter_id,),
            ).fetchone()
            current_retry = (row[0] if row else 0) or 0

            if error_code in ERROR_CODES_NO_RETRY or max_retries_reached(current_retry):
                conn.execute(
                    """UPDATE aggregate_chapter_tasks
                       SET status = 'error', error = ?, last_error_code = ?,
                           source_alignment_json = ?, next_retry_time = NULL, updated_at = ?
                       WHERE chapter_id = ?""",
                    (str(exc), error_code, json.dumps(alignment_json, ensure_ascii=False), now, chapter_id),
                )
            else:
                next_time = compute_next_retry_time(current_retry)
                conn.execute(
                    """UPDATE aggregate_chapter_tasks
                       SET status = 'error', error = ?, last_error_code = ?,
                           retry_count = ?, next_retry_time = ?,
                           source_alignment_json = ?, updated_at = ?
                       WHERE chapter_id = ?""",
                    (str(exc), error_code, current_retry + 1, next_time,
                     json.dumps(alignment_json, ensure_ascii=False), now, chapter_id),
                )
            conn.commit()
        return {"chapterId": chapter_id, "success": False, "error": str(exc), "errorCode": error_code}

    def _write_chapter_result(
        self, *, chapter_id: str, aggregate_book_id: str, title: str,
        chapter_index: int | None, status: str, content: str,
        alignment_json: dict, fallback_source_id: str = "",
        ai_model: str = "", deviation_score: float = 0.0,
        ai_self_score: float = 0.0,
        ai_prompt_tokens: int = 0, ai_completion_tokens: int = 0,
        ai_total_tokens: int = 0, ai_latency_ms: int = 0,
    ) -> None:
        now = self._now()
        with self._conn() as conn:
            conn.execute(
                """UPDATE aggregate_chapter_tasks
                   SET status = ?, content_length = ?, processed_content = ?, last_processed_at = ?,
                       error = '', last_error_code = '', retry_count = 0, next_retry_time = NULL,
                       source_alignment_json = ?, fallback_source_id = ?, ai_model = ?,
                       deviation_score = ?, ai_self_score = ?, ai_prompt_tokens = ?, ai_completion_tokens = ?,
                       ai_total_tokens = ?, ai_latency_ms = ?,
                       updated_at = ?
                   WHERE chapter_id = ?""",
                (status, len(content), content, now,
                 json.dumps(alignment_json, ensure_ascii=False),
                 fallback_source_id, ai_model,
                 deviation_score, ai_self_score, ai_prompt_tokens, ai_completion_tokens,
                 ai_total_tokens, ai_latency_ms,
                 now, chapter_id),
            )
            self._write_aggregate_chapter_file(
                conn, chapter_id=chapter_id, aggregate_book_id=aggregate_book_id,
                title=title, content=content, chapter_index=chapter_index,
            )
            conn.commit()

    def _aggregate_book_name_from_cache(self, aggregate_book_id: str) -> str:
        with self._conn() as conn:
            return self._aggregate_book_name(conn, aggregate_book_id)

    def aggregate_chapter_response(self, chapter_url: str, chapter_id: str = "") -> dict:
        try:
            payload = unpack_aggregate_chapter_url(chapter_url)
        except Exception as exc:
            return {
                "implemented": True,
                "chapterId": chapter_id,
                "title": "",
                "content": PROCESSING_PLACEHOLDER,
                "debug": {"aggregate": True, "status": "pending", "error": str(exc)},
            }
        aggregate_chapter_id = chapter_id or encode_chapter_id(VIRTUAL_SOURCE_ID, chapter_url)
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT title, status, processed_content, error
                FROM aggregate_chapter_tasks
                WHERE chapter_id = ?
                """,
                (aggregate_chapter_id,),
            ).fetchone()
        title = (row[0] if row else "") or payload.get("title", "")
        status = row[1] if row else "pending"
        if row and status in ("processed", "fallback") and row[2]:
            self._write_processed_chapter_if_needed(
                aggregate_chapter_id,
                chapter_url,
                title,
                row[2],
            )
            return {
                "implemented": True,
                "chapterId": aggregate_chapter_id,
                "title": title,
                "content": row[2],
                "debug": {"aggregate": True, "status": status},
            }
        return {
            "implemented": True,
            "chapterId": aggregate_chapter_id,
            "title": title,
            "content": PROCESSING_PLACEHOLDER,
            "debug": {
                "aggregate": True,
                "status": status,
                "sourceChapterId": payload.get("sourceChapterId", ""),
                "error": row[3] if row else "",
            },
        }

    # Ad/watermark patterns to remove (unified list).
    _AD_PATTERNS = re.compile(
        r"(?im)^.*("
        r"最新网址|最新地址|最新域名|最新章节地址|"
        r"本章未完|本章未完.*点击下一页|"
        r"请收藏|请记住本书首发域名|"
        r"手机用户请浏览|手机阅读|"
        r"百度搜索|百度搜|"
        r"天才一秒|笔趣阁|"
        r"一秒记住.*\.com|一秒记住.*\.net|"
        r"亲,.*收藏|加入书签|"
        r"www\.|\.com|\.net|\.org"
        r").*$"
    )
    _CHAPTER_TITLE_RE = re.compile(r"^(#\s*)?第[一二三四五六七八九十百零\d]+章.*$")

    def _purify_content(self, content: str) -> str:
        """Unified content purification.

        Steps:
        1. Basic cleanup: normalize line endings, strip trailing whitespace, compress blank lines.
        2. Ad/watermark removal: remove common ad lines, duplicate title lines.
        3. Integrity check: if cleaned content is too short or shrunk >50%, fall back to basic cleanup only.
        """
        if not content:
            return content

        original_length = len(content)

        # Step 1: Basic cleanup.
        text = content.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        basic_text = text.strip()

        # Step 2: Ad/watermark removal.
        text = self._AD_PATTERNS.sub("", basic_text)

        # Remove duplicate chapter-title lines.
        seen_titles: set[str] = set()
        kept_lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            title_key = stripped.lstrip("#").strip()
            if self._CHAPTER_TITLE_RE.match(stripped) and title_key in seen_titles:
                continue
            if self._CHAPTER_TITLE_RE.match(stripped):
                seen_titles.add(title_key)
            kept_lines.append(line)
        text = "\n".join(kept_lines)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        # Step 3: Integrity check.
        # If cleaned content is too short or shrunk significantly, fall back to basic cleanup.
        if len(text) < 100 or (original_length > 200 and len(text) < original_length * 0.5):
            return basic_text

        return text

    def _write_processed_chapter_if_needed(
        self,
        chapter_id: str,
        chapter_url: str,
        title: str,
        content: str,
    ) -> None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT aggregate_book_id, chapter_index
                FROM aggregate_chapter_tasks
                WHERE chapter_id = ?
                """,
                (chapter_id,),
            ).fetchone()
            if not row:
                return
            self._write_aggregate_chapter_file(
                conn,
                chapter_id=chapter_id,
                aggregate_book_id=row[0] or "",
                title=title,
                content=content,
                chapter_index=row[1],
                chapter_url=chapter_url,
            )
            conn.commit()

    def _write_aggregate_chapter_file(
        self,
        conn: sqlite3.Connection,
        *,
        chapter_id: str,
        aggregate_book_id: str,
        title: str,
        content: str,
        chapter_index: int | None = None,
        chapter_url: str = "",
    ) -> None:
        if not chapter_url:
            try:
                _, chapter_url = decode_chapter_id(chapter_id)
            except Exception:
                chapter_url = ""
        book_name = self._aggregate_book_name(conn, aggregate_book_id)
        file_result = NovelFileCache(root=self.db_path.parent / "novels").write_chapter(
            conn=conn,
            chapter_id=chapter_id,
            source_id=VIRTUAL_SOURCE_ID,
            chapter_url=chapter_url,
            title=title,
            content=content,
            book_id=aggregate_book_id,
            book_name=book_name,
            chapter_index=chapter_index,
        )
        return file_result

    def _aggregate_book_name(self, conn: sqlite3.Connection, aggregate_book_id: str) -> str:
        row = conn.execute(
            "SELECT name FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
            (aggregate_book_id,),
        ).fetchone()
        if row and row[0]:
            return row[0]
        row = conn.execute("SELECT name FROM book_records WHERE book_id = ?", (aggregate_book_id,)).fetchone()
        return row[0] if row and row[0] else ""

    async def run_forever(self, stop_event: asyncio.Event, poll_seconds: int = 60) -> None:
        logger.info("Aggregate processor started, pollSeconds=%d", poll_seconds)
        while not stop_event.is_set():
            try:
                result = await self.run_due_once(limit=5)
                if result.get("processedBooks", 0) > 0:
                    logger.info(
                        "Aggregate run completed: processedBooks=%d, dueBooks=%d",
                        result.get("processedBooks", 0),
                        result.get("dueBooks", 0),
                    )
            except Exception:
                logger.warning("Aggregate run_due_once failed", exc_info=True)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
            except asyncio.TimeoutError:
                continue
        logger.info("Aggregate processor stopped")

