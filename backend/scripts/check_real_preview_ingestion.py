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
from app.services.library_books import LibraryBooksService
from app.storage.db import initialize_database


GROUP = {
    "candidateId": "real-preview-night-land",
    "name": "夜无疆",
    "author": "辰东",
    "items": [
        {
            "sourceId": "qidian_com_web",
            "sourceName": "起点中文网(Web)",
            "rawBookUrl": "https://m.qidian.com/book/1040765595/",
            "bookUrl": "https://m.qidian.com/book/1040765595/",
            "score": 200,
            "name": "夜无疆",
            "author": "辰东",
        }
    ],
}


async def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="real_preview_ingestion_")
    db_path = Path(tmpdir) / "app.db"
    initialize_database(db_path)

    service = LibraryBooksService(db_path=db_path)
    created = await service.create_or_get_shared_book(
        GROUP,
        added_by_user_id="tester",
        start_chapter_index=740,
        auto_archive_on_complete=False,
    )
    book = created["book"]
    payload = created["payload"]

    processor = AggregateProcessor(db_path=db_path, ai_service=None)
    enqueue = processor.enqueue_book(book["aggregateBookId"], payload)
    result = await processor.run_book_task(book["aggregateBookId"], chapter_limit=3)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT chapter_index, title, status, preview_only, source_word_count, primary_source_chapter_url, content_file_path
            FROM aggregate_chapter_tasks
            WHERE aggregate_book_id = ? AND chapter_index >= 740
            ORDER BY chapter_index ASC
            LIMIT 5
            """,
            (book["aggregateBookId"],),
        ).fetchall()

    chapters = []
    preview_true = 0
    for row in rows:
        file_path = row[6] or ""
        file_text = Path(file_path).read_text(encoding="utf-8") if file_path and Path(file_path).exists() else ""
        item = {
            "chapterIndex": row[0],
            "title": row[1],
            "status": row[2],
            "previewOnly": bool(row[3]),
            "sourceWordCount": int(row[4] or 0),
            "primarySourceChapterUrl": row[5] or "",
            "contentFilePath": file_path,
            "traceHasPreviewOnly": "previewOnly: true" in file_text,
        }
        if item["previewOnly"]:
            preview_true += 1
        chapters.append(item)

    output = {
        "enqueue": enqueue,
        "runResult": result,
        "book": {
            "aggregateBookId": book.get("aggregateBookId", ""),
            "bookStatus": book.get("bookStatus", ""),
            "startChapterIndex": book.get("startChapterIndex", 0),
            "primaryBookUrl": book.get("primaryBookUrl", ""),
        },
        "chapters": chapters,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if preview_true <= 0:
        print("expected at least one real preview-only chapter")
        return 1
    if not any(item["traceHasPreviewOnly"] for item in chapters if item["previewOnly"]):
        print("expected preview trace marker in at least one preview chapter file")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
