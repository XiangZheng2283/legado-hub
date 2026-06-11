"""Bookshelf persistence helpers."""

from __future__ import annotations

import json
import sqlite3


def record_bookshelf_items(items: list[dict]) -> None:
    """Record searched or explored books so the console bookshelf can track them."""
    from app.config import DB_PATH

    with sqlite3.connect(DB_PATH) as conn:
        for item in items:
            book_id = item.get("bookId", "")
            if not book_id:
                continue
            source_payload = {
                "sourceId": item.get("sourceId", ""),
                "sourceName": item.get("sourceName", ""),
                "bookUrl": item.get("rawBookUrl") or item.get("bookUrl", ""),
                "lastChapter": item.get("lastChapter", ""),
            }
            conn.execute(
                """
                INSERT OR REPLACE INTO book_records
                (book_id, name, author, merged_sources_json, selected_source_id, last_chapter, last_seen_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), COALESCE((SELECT created_at FROM book_records WHERE book_id=?), datetime('now')))
                """,
                (
                    book_id,
                    item.get("name", ""),
                    item.get("author", ""),
                    json.dumps([source_payload], ensure_ascii=False),
                    item.get("sourceId", ""),
                    item.get("lastChapter", ""),
                    book_id,
                ),
            )
        conn.commit()


