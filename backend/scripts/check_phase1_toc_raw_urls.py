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
    "candidateId": "phase1-toc-raw-url-test",
    "name": "测试书名",
    "author": "测试作者",
    "items": [
        {
            "sourceId": "qidian_com_web",
            "sourceName": "起点中文网(Web)",
            "bookId": "qidian_com_web:https://www.qidian.com/book/1036363626/",
            "rawBookUrl": "https://www.qidian.com/book/1036363626/",
            "bookUrl": "https://www.qidian.com/book/1036363626/",
            "score": 100,
            "name": "测试书名",
            "author": "测试作者",
        }
    ],
}


async def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="phase1_toc_raw_")
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
    payload = created["payload"]

    catalog = BookCatalog()
    toc = await catalog.toc(book["primaryBookId"])
    chapters = [dict(item) for item in toc.get("chapters", []) if isinstance(item, dict)]
    if not chapters:
        print("missing-toc-chapters")
        return 1

    first = chapters[0]
    print("toc-first:")
    print(
        json.dumps(
            {
                "chapterId": first.get("chapterId", ""),
                "chapterUrl": first.get("chapterUrl", ""),
                "rawChapterUrl": first.get("rawChapterUrl", ""),
                "title": first.get("title", ""),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    processor = AggregateProcessor(db_path=db_path)
    register_result = processor.register_toc(book["aggregateBookId"], payload, chapters)
    print("register-toc:")
    print(json.dumps(register_result, ensure_ascii=False, indent=2))

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT chapter_index, title, primary_source_chapter_url
            FROM aggregate_chapter_tasks
            WHERE aggregate_book_id = ?
            ORDER BY chapter_index ASC
            LIMIT 1
            """,
            (book["aggregateBookId"],),
        ).fetchone()

    if not row:
        print("missing-chapter-row")
        return 1

    chapter_row = {
        "chapterIndex": row[0],
        "title": row[1],
        "primarySourceChapterUrl": row[2],
    }
    print("chapter-row:")
    print(json.dumps(chapter_row, ensure_ascii=False, indent=2))

    if not first.get("rawChapterUrl"):
        print("expected toc rawChapterUrl")
        return 1
    if "/api/legado/chapter/" in first.get("rawChapterUrl", ""):
        print("toc rawChapterUrl should stay remote")
        return 1
    if not chapter_row["primarySourceChapterUrl"]:
        print("expected DB primarySourceChapterUrl")
        return 1
    if "/api/legado/chapter/" in chapter_row["primarySourceChapterUrl"]:
        print("DB primarySourceChapterUrl should stay remote")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
