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
    "candidateId": "phase1-chapter-test",
    "name": "宿命之环",
    "author": "爱潜水的乌贼",
    "items": [
        {
            "sourceId": "qidian_com_web",
            "sourceName": "起点中文网(Web)",
            "rawBookUrl": "https://m.qidian.com/book/1036370336/",
            "bookUrl": "https://m.qidian.com/book/1036370336/",
            "coverUrl": "https://bookcover.yuewen.com/qdbimg/349573/1036370336/180",
            "intro": "诡秘世界第二部。1368之年，七月之末，深红将从天而降。",
            "wordCount": "377.04万字",
            "status": "完本",
            "chapterCount": 1195,
            "score": 221,
            "lastChapter": "番外：科尔杜村日常",
            "name": "宿命之环",
            "author": "爱潜水的乌贼",
        }
    ],
}


async def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="phase1_chapter_")
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
    processor = AggregateProcessor(db_path=db_path)
    register_result = processor.register_toc(book["aggregateBookId"], payload, chapters)

    queue = processor._chapters_for_processing(book["aggregateBookId"], limit=5)
    print("queue:")
    print(json.dumps(queue, ensure_ascii=False, indent=2))
    if not queue:
        print("no-processable-chapter")
        return 1
    chapter = queue[0]
    result = await processor._process_chapter(catalog, chapter)
    print("process-result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT chapter_id, title, status, source_word_count, preview_only,
                   primary_source_chapter_url, content_file_path, processed_content
            FROM aggregate_chapter_tasks
            WHERE chapter_id = ?
            """,
            (chapter["chapterId"],),
        ).fetchone()

    print("chapter-row:")
    chapter_row = {
        "chapterId": row[0],
        "title": row[1],
        "status": row[2],
        "sourceWordCount": row[3],
        "previewOnly": bool(row[4]),
        "primarySourceChapterUrl": row[5],
        "contentFilePath": row[6],
        "contentLength": len(row[7] or ""),
    }
    print(json.dumps(chapter_row, ensure_ascii=False, indent=2))

    chapter_file = Path(row[6]) if row and row[6] else None
    if chapter_file and chapter_file.exists():
        text = chapter_file.read_text(encoding="utf-8")
        tail = text[-2000:]
        print("trace-tail:")
        print(tail)
    else:
        print("missing-chapter-file")
        return 1

    if chapter_row["sourceWordCount"] <= 0:
        print("expected positive sourceWordCount")
        return 1
    if not chapter_row["primarySourceChapterUrl"]:
        print("expected non-empty primarySourceChapterUrl")
        return 1
    if "sourceWordCount: 0" in tail:
        print("trace tail still has zero sourceWordCount")
        return 1
    if 'primarySourceChapterUrl: ""' in tail:
        print("trace tail still has empty primarySourceChapterUrl")
        return 1

    print("register-toc:")
    print(json.dumps(register_result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
