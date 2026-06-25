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
from app.storage.db import initialize_database


def seed_book(conn: sqlite3.Connection, aggregate_book_id: str, payload: dict[str, object]) -> None:
    now = "2026-06-25T00:00:00+00:00"
    conn.execute(
        """
        INSERT INTO aggregate_book_tasks (
            aggregate_book_id, canonical_name, canonical_author, name, author,
            aggregate_payload_json, primary_book_id, primary_source_id, primary_source_name,
            primary_book_url, primary_toc_url, added_by_user_id, start_chapter_index,
            total_chapters_at_subscribe, initial_snapshot_last_index, backfill_started,
            auto_archive_on_complete, search_visibility_status, book_status, total_chapters,
            processed_chapters, visible_processed_chapters, failed_chapters, total_tokens,
            status, settings_json, current_policy_version, interval_minutes, error_count,
            last_error, ai_enabled, created_at, updated_at
        ) VALUES (?, '', '', ?, ?, ?, ?, ?, ?, ?, ?, 'tester', 2, 3, 3, 0, 1, 'hidden', 'ongoing', 3, 2, 2, 0, 0, 'active', '{}', 1, 30, 0, '', 1, ?, ?)
        """,
        (
            aggregate_book_id,
            payload["name"],
            payload["author"],
            json.dumps(payload, ensure_ascii=False),
            payload["primaryBookId"],
            payload["primarySourceId"],
            payload["primarySourceName"],
            payload["primaryBookUrl"],
            payload["primaryTocUrl"],
            now,
            now,
        ),
    )
    conn.executemany(
        """
        INSERT INTO aggregate_chapter_tasks (
            chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title, status,
            placeholder, primary_source_chapter_url, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
        """,
        [
            (
                "agg-2",
                aggregate_book_id,
                "qidian_com_web:https://remote/chapter/2",
                2,
                "第2章",
                "processed",
                "https://remote/chapter/2",
                now,
                now,
            ),
            (
                "agg-3",
                aggregate_book_id,
                "qidian_com_web:https://remote/chapter/3",
                3,
                "第3章",
                "processed",
                "https://remote/chapter/3",
                now,
                now,
            ),
        ],
    )
    conn.commit()


class FakeCatalog:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def book_detail(self, book_id: str) -> dict:
        self.calls.append(f"detail:{book_id}")
        return {
            "implemented": True,
            "data": {
                "name": "测试追更书",
                "author": "测试作者",
                "coverUrl": "",
                "intro": "用于验证追更",
                "wordCountText": "100万字",
                "status": "连载",
                "bookUrl": "https://m.qidian.com/book/123456/",
                "tocUrl": "https://m.qidian.com/book/123456/catalog/",
            },
            "debug": {},
        }

    async def toc(self, book_id: str) -> dict:
        self.calls.append(f"toc:{book_id}")
        return {
            "implemented": True,
            "chapters": [
                {
                    "chapterId": "qidian_com_web:https://remote/chapter/1",
                    "chapterUrl": "https://remote/chapter/1",
                    "rawChapterUrl": "https://remote/chapter/1",
                    "title": "第1章",
                },
                {
                    "chapterId": "qidian_com_web:https://remote/chapter/2",
                    "chapterUrl": "https://remote/chapter/2",
                    "rawChapterUrl": "https://remote/chapter/2",
                    "title": "第2章",
                },
                {
                    "chapterId": "qidian_com_web:https://remote/chapter/3",
                    "chapterUrl": "https://remote/chapter/3",
                    "rawChapterUrl": "https://remote/chapter/3",
                    "title": "第3章",
                },
                {
                    "chapterId": "qidian_com_web:https://remote/chapter/4",
                    "chapterUrl": "https://remote/chapter/4",
                    "rawChapterUrl": "https://remote/chapter/4",
                    "title": "第4章",
                },
            ],
            "debug": {},
        }

    async def chapter(self, chapter_id: str) -> dict:
        self.calls.append(f"chapter:{chapter_id}")
        number = chapter_id.rsplit("/", 1)[-1]
        content = ("这是第" + number + "章的完整正文内容，用于验证追更后的全量抓取与落盘。") * 60
        return {
            "implemented": True,
            "chapterId": chapter_id,
            "title": f"第{number}章",
            "content": content,
            "rawChapterUrl": f"https://remote/chapter/{number}",
            "chapterUrl": f"https://remote/chapter/{number}",
            "extra": {"actualWords": len(content)},
            "debug": {},
        }


async def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="phase1_update_")
    db_path = Path(tmpdir) / "phase1.db"
    initialize_database(db_path)

    aggregate_book_id = "phase1-update-book"
    payload = {
        "name": "测试追更书",
        "author": "测试作者",
        "sources": [
            {
                "sourceId": "qidian_com_web",
                "sourceName": "起点中文网(Web)",
                "bookId": "qidian_com_web:https://m.qidian.com/book/123456/",
                "bookUrl": "https://m.qidian.com/book/123456/",
                "score": 100,
            }
        ],
        "primarySourceId": "qidian_com_web",
        "primarySourceName": "起点中文网(Web)",
        "primaryBookId": "qidian_com_web:https://m.qidian.com/book/123456/",
        "primaryBookUrl": "https://m.qidian.com/book/123456/",
        "primaryTocUrl": "https://m.qidian.com/book/123456/catalog/",
        "startChapterIndex": 2,
        "autoArchiveOnComplete": True,
        "supplementSourceConfig": {},
    }

    with sqlite3.connect(db_path) as conn:
        seed_book(conn, aggregate_book_id, payload)

    processor = AggregateProcessor(db_path=db_path, ai_service=None)
    fake_catalog = FakeCatalog()
    original_book_catalog = sys.modules.get("app.services.book_catalog")
    if original_book_catalog is None:
        import app.services.book_catalog as original_book_catalog  # type: ignore
    else:
        original_book_catalog = sys.modules["app.services.book_catalog"]

    import app.services.book_catalog as book_catalog_module

    original_class = book_catalog_module.BookCatalog
    book_catalog_module.BookCatalog = lambda: fake_catalog  # type: ignore[assignment]
    try:
        result = await processor.run_book_task(aggregate_book_id)
    finally:
        book_catalog_module.BookCatalog = original_class  # type: ignore[assignment]

    print("run-result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT total_chapters, processed_chapters, visible_processed_chapters, status, search_visibility_status
            FROM aggregate_book_tasks
            WHERE aggregate_book_id = ?
            """,
            (aggregate_book_id,),
        ).fetchone()
        new_chapter = conn.execute(
            """
            SELECT chapter_index, status, source_word_count, primary_source_chapter_url
            FROM aggregate_chapter_tasks
            WHERE aggregate_book_id = ? AND chapter_index = 4
            """,
            (aggregate_book_id,),
        ).fetchone()

    state = {
        "totalChapters": row[0],
        "processedChapters": row[1],
        "visibleProcessedChapters": row[2],
        "status": row[3],
        "searchVisibilityStatus": row[4],
        "newChapter": {
            "chapterIndex": new_chapter[0] if new_chapter else None,
            "status": new_chapter[1] if new_chapter else "",
            "sourceWordCount": new_chapter[2] if new_chapter else 0,
            "primarySourceChapterUrl": new_chapter[3] if new_chapter else "",
        },
        "calls": fake_catalog.calls,
    }
    print("state:")
    print(json.dumps(state, ensure_ascii=False, indent=2))

    if not result.get("success"):
        print("expected successful update polling run")
        return 1
    if row[0] != 4:
        print("expected total chapters to advance to 4")
        return 1
    if row[1] < 3:
        print("expected processed chapter count to increase")
        return 1
    if not new_chapter or new_chapter[1] != "processed":
        print("expected new chapter to be processed")
        return 1
    if not new_chapter[3] or "/api/legado/chapter/" in new_chapter[3]:
        print("expected new chapter remote primary source url")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
