"""Background processing for virtual aggregate books."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.source_plugins.id_codec import decode_chapter_id, encode_chapter_id
from app.services.aggregate_virtual_source import (
    VIRTUAL_SOURCE_ID,
    make_aggregate_chapter_url,
    primary_book_id_from_payload,
    unpack_aggregate_chapter_url,
)
from app.services.novel_file_cache import NovelFileCache

PROCESSING_PLACEHOLDER = "正在聚合处理……请稍后刷新。"


DEFAULT_WORKFLOW = {
    "aiEnabled": False,
    "autoAggregate": True,
    "processAggregateOnRead": True,
    "aggregateCheckIntervalMinutes": 30,
    "returnOnlyAggregateSource": False,
    "purifyMode": "conservative",
}


class AggregateProcessor:
    def __init__(self, db_path: str | Path | None = None):
        from app.config import DB_PATH

        self.db_path = Path(db_path or DB_PATH)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _workflow_settings(self) -> dict:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value_json FROM admin_settings WHERE key = 'contentWorkflow'"
            ).fetchone()
        settings = dict(DEFAULT_WORKFLOW)
        if not row:
            return settings
        try:
            parsed = json.loads(row[0])
            if isinstance(parsed, dict):
                settings.update(parsed)
        except Exception:
            pass
        return settings

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

        primary_book_id = primary_book_id_from_payload(payload)
        if not primary_book_id:
            return {"queued": False, "reason": "aggregate source has no candidates", "bookId": aggregate_book_id}

        now = self._now()
        interval = self.check_interval_minutes()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO aggregate_book_tasks
                (aggregate_book_id, name, author, aggregate_payload_json, primary_book_id, status,
                 interval_minutes, last_check_time, next_check_time, error_count, last_error, created_at, updated_at)
                VALUES (
                  ?, ?, ?, ?, ?, 'active', ?, 
                  COALESCE((SELECT last_check_time FROM aggregate_book_tasks WHERE aggregate_book_id = ?), NULL),
                  ?,
                  COALESCE((SELECT error_count FROM aggregate_book_tasks WHERE aggregate_book_id = ?), 0),
                  COALESCE((SELECT last_error FROM aggregate_book_tasks WHERE aggregate_book_id = ?), ''),
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
                    interval,
                    aggregate_book_id,
                    now,
                    aggregate_book_id,
                    aggregate_book_id,
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
        with self._conn() as conn:
            for index, chapter in enumerate(chapters, start=1):
                raw_url = chapter.get("chapterUrl", "")
                source_chapter_id = chapter.get("chapterId") or (
                    encode_chapter_id(source_id, raw_url) if source_id and raw_url else f"{aggregate_book_id}:{index}"
                )
                aggregate_chapter_url = make_aggregate_chapter_url(
                    aggregate_book_id=aggregate_book_id,
                    source_chapter_id=source_chapter_id,
                    title=chapter.get("title", ""),
                    index=index,
                )
                chapter_id = encode_chapter_id(VIRTUAL_SOURCE_ID, aggregate_chapter_url)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO aggregate_chapter_tasks
                    (chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        chapter_id,
                        aggregate_book_id,
                        source_chapter_id,
                        index,
                        chapter.get("title", ""),
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """
                    UPDATE aggregate_chapter_tasks
                    SET title = ?, source_chapter_id = ?, chapter_index = ?, updated_at = ?
                    WHERE chapter_id = ? AND status != 'processed'
                    """,
                    (chapter.get("title", ""), source_chapter_id, index, now, chapter_id),
                )
                registered += 1
            conn.commit()
        return {"registered": True, "chapterCount": registered}

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
            return {"enabled": False, "processedBooks": 0}
        processed = []
        for item in self.list_due_books(limit=limit):
            processed.append(await self.run_book_task(item["aggregateBookId"]))
        return {"enabled": True, "processedBooks": len(processed), "items": processed}

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
                        error_count = 0, last_error = '', updated_at = ?
                    WHERE aggregate_book_id = ?
                    """,
                    (now, next_check, now, aggregate_book_id),
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

    def _chapters_for_processing(self, aggregate_book_id: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT chapter_id, source_chapter_id, title, status, chapter_index, aggregate_book_id
                FROM aggregate_chapter_tasks
                WHERE aggregate_book_id = ? AND status IN ('pending', 'error')
                ORDER BY COALESCE(chapter_index, 999999), created_at
                """,
                (aggregate_book_id,),
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

    async def _process_chapter(self, catalog, chapter: dict) -> dict:
        now = self._now()
        chapter_id = chapter["chapterId"]
        source_chapter_id = chapter.get("sourceChapterId") or chapter_id
        try:
            result = await catalog.chapter(source_chapter_id)
            content = result.get("content", "")
            if not content:
                raise ValueError("empty chapter content")
            purified = self._purify_content(content)
            with self._conn() as conn:
                conn.execute(
                    """
                    UPDATE aggregate_chapter_tasks
                    SET status = 'processed', content_length = ?, processed_content = ?, last_processed_at = ?,
                        error = '', updated_at = ?
                    WHERE chapter_id = ?
                    """,
                    (len(purified), purified, now, now, chapter_id),
                )
                self._write_aggregate_chapter_file(
                    conn,
                    chapter_id=chapter_id,
                    aggregate_book_id=chapter.get("aggregateBookId", ""),
                    title=chapter.get("title", ""),
                    content=purified,
                    chapter_index=chapter.get("chapterIndex"),
                )
                conn.commit()
            return {"chapterId": chapter_id, "success": True, "contentLength": len(purified)}
        except Exception as exc:
            with self._conn() as conn:
                conn.execute(
                    """
                    UPDATE aggregate_chapter_tasks
                    SET status = 'error', error = ?, updated_at = ?
                    WHERE chapter_id = ?
                    """,
                    (str(exc), now, chapter_id),
                )
                conn.commit()
            return {"chapterId": chapter_id, "success": False, "error": str(exc)}

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
        if row and status == "processed" and row[2]:
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
                "debug": {"aggregate": True, "status": "processed"},
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

    def _purify_content(self, content: str) -> str:
        settings = self._workflow_settings()
        mode = settings.get("purifyMode", "conservative")
        if mode == "off":
            return content
        text = content.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        if mode == "aggressive":
            text = re.sub(r"(?im)^.*(最新网址|最新地址|本章未完|请收藏|手机用户请浏览).*$", "", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

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
        while not stop_event.is_set():
            try:
                await self.run_due_once(limit=5)
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
            except asyncio.TimeoutError:
                continue


