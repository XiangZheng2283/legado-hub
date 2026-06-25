"""SQLite cache for book, toc, and chapter results.

Search snapshots are stored in ``book_search_cache`` (book-entity-based,
7-day TTL), managed by ``SearchCoordinator``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import DB_PATH
from app.services.novel_file_cache import NovelFileCache


class Cache:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_PATH
        self.file_cache = NovelFileCache(root=self.db_path.parent / "novels")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _is_fresh(self, created_at: str, ttl_seconds: int) -> bool:
        try:
            dt = datetime.fromisoformat(created_at)
            return datetime.now(timezone.utc) - dt < timedelta(seconds=ttl_seconds)
        except Exception:
            return False

    def get_book(self, book_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT response_json, created_at FROM book_cache WHERE book_id=?", (book_id,)
            ).fetchone()
        if row and self._is_fresh(row[1], 86400):
            return json.loads(row[0])
        return None

    def set_book(self, book_id: str, source_id: str, book_url: str, data: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO book_cache (book_id, source_id, book_url, response_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (book_id, source_id, book_url, json.dumps(data, ensure_ascii=False), self._now()),
            )
            conn.commit()

    def get_toc(self, book_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT response_json, created_at FROM toc_cache WHERE book_id=?", (book_id,)
            ).fetchone()
        if row and self._is_fresh(row[1], 3600):
            return json.loads(row[0])
        return None

    def set_toc(self, book_id: str, data: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO toc_cache (book_id, response_json, created_at) VALUES (?, ?, ?)",
                (book_id, json.dumps(data, ensure_ascii=False), self._now()),
            )
            conn.commit()

    def get_chapter(self, chapter_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT response_json, created_at FROM chapter_cache WHERE chapter_id=?", (chapter_id,)
            ).fetchone()
        if row and self._is_fresh(row[1], 86400):
            return json.loads(row[0])
        return None

    def set_chapter(self, chapter_id: str, source_id: str, chapter_url: str, data: dict) -> None:
        with self._conn() as conn:
            file_result = self.file_cache.write_chapter(
                conn=conn,
                chapter_id=chapter_id,
                source_id=source_id,
                chapter_url=chapter_url,
                title=data.get("title", ""),
                content=data.get("content", ""),
                book_id=data.get("bookId", "") or data.get("book_id", ""),
                book_name=data.get("bookName", "") or data.get("book_name", ""),
                author=data.get("author", ""),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO chapter_cache
                (chapter_id, source_id, chapter_url, response_json, book_id, book_name,
                 chapter_title, file_path, content_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chapter_id,
                    source_id,
                    chapter_url,
                    json.dumps(data, ensure_ascii=False),
                    file_result.get("bookId", ""),
                    file_result.get("bookName", ""),
                    file_result.get("chapterTitle", data.get("title", "")),
                    file_result.get("filePath", ""),
                    file_result.get("contentHash", ""),
                    self._now(),
                ),
            )
            conn.commit()



