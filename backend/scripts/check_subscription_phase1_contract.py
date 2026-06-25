from __future__ import annotations

import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "backend" / "data" / "app.db"


def main() -> int:
    if not DB_PATH.exists():
        print(f"missing-db: {DB_PATH}")
        return 1

    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT aggregate_book_id, name, author, primary_source_id, primary_source_name,
                   primary_book_url, primary_toc_url, total_chapters_at_subscribe,
                   start_chapter_index, auto_archive_on_complete, settings_json
            FROM aggregate_book_tasks
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            print("missing-book-row")
            return 1

        settings = json.loads(row[10] or "{}") if row[10] else {}
        print("book-row:")
        print(
            json.dumps(
                {
                    "aggregateBookId": row[0],
                    "name": row[1],
                    "author": row[2],
                    "primarySourceId": row[3],
                    "primarySourceName": row[4],
                    "primaryBookUrl": row[5],
                    "primaryTocUrl": row[6],
                    "totalChaptersAtSubscribe": row[7],
                    "startChapterIndex": row[8],
                    "autoArchiveOnComplete": bool(row[9]),
                    "supplementSourceConfig": settings.get("supplementSourceConfig", {}),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        chapter_rows = conn.execute(
            """
            SELECT chapter_id, chapter_index, title, status, source_word_count, preview_only, primary_source_chapter_url
            FROM aggregate_chapter_tasks
            WHERE aggregate_book_id = ?
            ORDER BY chapter_index ASC
            LIMIT 5
            """,
            (row[0],),
        ).fetchall()
        print("chapter-sample:")
        print(
            json.dumps(
                [
                    {
                        "chapterId": item[0],
                        "chapterIndex": item[1],
                        "title": item[2],
                        "status": item[3],
                        "sourceWordCount": item[4],
                        "previewOnly": bool(item[5]),
                        "primarySourceChapterUrl": item[6],
                    }
                    for item in chapter_rows
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
