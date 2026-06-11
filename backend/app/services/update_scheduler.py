"""Update tracking and scheduling service."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from app.config import DB_PATH
from app.services.book_catalog import BookCatalog


class UpdateScheduler:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DB_PATH

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def list_tasks(self, limit: int = 100, offset: int = 0) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT book_id, last_check_time, next_check_time, status, error_count, last_error FROM update_tasks ORDER BY next_check_time LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [
            {
                "bookId": r[0],
                "lastCheckTime": r[1],
                "nextCheckTime": r[2],
                "status": r[3],
                "errorCount": r[4],
                "lastError": r[5],
            }
            for r in rows
        ]

    def get_task(self, book_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT book_id, last_check_time, next_check_time, status, error_count, last_error FROM update_tasks WHERE book_id = ?",
                (book_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "bookId": row[0],
            "lastCheckTime": row[1],
            "nextCheckTime": row[2],
            "status": row[3],
            "errorCount": row[4],
            "lastError": row[5],
        }

    def enable_tracking(self, book_id: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        next_check = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO update_tasks
                (book_id, last_check_time, next_check_time, status, error_count, last_error, updated_at)
                VALUES (?, ?, ?, 'active', 0, '', ?)
                """,
                (book_id, now, next_check, now),
            )
            conn.commit()
        return {"bookId": book_id, "status": "active", "nextCheckTime": next_check}

    def disable_tracking(self, book_id: str) -> dict:
        with self._conn() as conn:
            conn.execute(
                "UPDATE update_tasks SET status = 'disabled', updated_at = datetime('now') WHERE book_id = ?",
                (book_id,),
            )
            conn.commit()
        return {"bookId": book_id, "status": "disabled"}

    async def run_check(self, book_id: str) -> dict:
        """Manually run an update check for a book."""
        catalog = BookCatalog()
        task = self.get_task(book_id)
        if not task:
            return {"bookId": book_id, "success": False, "error": "追更任务不存在"}

        now = datetime.now(timezone.utc).isoformat()
        next_check = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()

        try:
            toc = await catalog.toc(book_id)
            chapters = toc.get("chapters", [])
            latest_chapter = chapters[-1].get("title", "") if chapters else ""

            with self._conn() as conn:
                conn.execute(
                    """
                    UPDATE update_tasks
                    SET last_check_time = ?, next_check_time = ?, status = 'active', error_count = 0, last_error = '', updated_at = ?
                    WHERE book_id = ?
                    """,
                    (now, next_check, now, book_id),
                )
                conn.execute(
                    """
                    UPDATE book_records SET last_chapter = ?, last_seen_at = ? WHERE book_id = ?
                    """,
                    (latest_chapter, now, book_id),
                )
                conn.commit()

            return {
                "bookId": book_id,
                "success": True,
                "latestChapter": latest_chapter,
                "chapterCount": len(chapters),
                "nextCheckTime": next_check,
            }
        except Exception as e:
            with self._conn() as conn:
                conn.execute(
                    """
                    UPDATE update_tasks
                    SET last_check_time = ?, next_check_time = ?, status = 'error', error_count = error_count + 1, last_error = ?, updated_at = ?
                    WHERE book_id = ?
                    """,
                    (now, next_check, str(e), now, book_id),
                )
                conn.commit()
            return {"bookId": book_id, "success": False, "error": str(e)}


