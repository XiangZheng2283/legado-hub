from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.aggregate_processor import AggregateProcessor
from app.services.book_catalog import BookCatalog
from app.services.library_books import LibraryBooksService
from app.storage.db import initialize_database


GROUP = {
    "candidateId": "phase1-contract-test",
    "name": "测试书名",
    "author": "测试作者",
    "items": [
        {
            "sourceId": "qidian_com_web",
            "sourceName": "起点中文网(Web)",
            "bookId": "qidian_com_web:https://www.qidian.com/book/1036363626/",
            "rawBookUrl": "https://www.qidian.com/book/1036363626/",
            "bookUrl": "https://www.qidian.com/book/1036363626/",
            "coverUrl": "",
            "intro": "",
            "wordCount": "",
            "status": "",
            "chapterCount": 0,
            "score": 100,
            "lastChapter": "",
            "name": "测试书名",
            "author": "测试作者",
        }
    ],
}


async def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="phase1_")
    db_path = Path(tmpdir) / "phase1.db"
    initialize_database(db_path)
    service = LibraryBooksService(db_path=db_path)
    created = await service.create_or_get_shared_book(
        GROUP,
        added_by_user_id="phase1-user",
        start_chapter_index=12,
        auto_archive_on_complete=True,
    )
    book = created["book"]
    print("book:")
    print(
        json.dumps(
            {
                "aggregateBookId": book.get("aggregateBookId"),
                "primarySourceId": book.get("primarySourceId"),
                "primarySourceName": book.get("primarySourceName"),
                "primaryBookId": book.get("primaryBookId"),
                "primaryBookUrl": book.get("primaryBookUrl"),
                "primaryTocUrl": book.get("primaryTocUrl"),
                "totalChaptersAtSubscribe": book.get("totalChaptersAtSubscribe"),
                "startChapterIndex": book.get("startChapterIndex"),
                "autoArchiveOnComplete": book.get("autoArchiveOnComplete"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT aggregate_payload_json, primary_book_url, primary_toc_url, total_chapters_at_subscribe
            FROM aggregate_book_tasks
            WHERE aggregate_book_id = ?
            """,
            (book["aggregateBookId"],),
        ).fetchone()
    payload = json.loads(row[0] or "{}")
    print("payload:")
    print(
        json.dumps(
            {
                "primarySourceId": payload.get("primarySourceId"),
                "primarySourceName": payload.get("primarySourceName"),
                "primaryBookId": payload.get("primaryBookId"),
                "primaryBookUrl": payload.get("primaryBookUrl"),
                "primaryTocUrl": payload.get("primaryTocUrl"),
                "totalChaptersAtSubscribe": payload.get("totalChaptersAtSubscribe"),
                "supplementSourceConfig": payload.get("supplementSourceConfig", {}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    catalog = BookCatalog()
    toc = await catalog.toc(book["primaryBookId"])
    chapters = [dict(item) for item in toc.get("chapters", []) if isinstance(item, dict)]
    print("toc-count:", len(chapters))

    processor = AggregateProcessor(db_path=db_path)
    register_result = processor.register_toc(book["aggregateBookId"], payload, chapters)
    print("register-toc:")
    print(json.dumps(register_result, ensure_ascii=False, indent=2))

    with sqlite3.connect(db_path) as conn:
        chapter_rows = conn.execute(
            """
            SELECT chapter_id, chapter_index, title, status, placeholder, primary_source_chapter_url
            FROM aggregate_chapter_tasks
            WHERE aggregate_book_id = ?
            ORDER BY chapter_index ASC
            LIMIT 5
            """,
            (book["aggregateBookId"],),
        ).fetchall()
    print("chapter-rows:")
    print(
        json.dumps(
            [
                {
                    "chapterId": row[0],
                    "chapterIndex": row[1],
                    "title": row[2],
                    "status": row[3],
                    "placeholder": bool(row[4]),
                    "primarySourceChapterUrl": row[5],
                }
                for row in chapter_rows
            ],
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
