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


class FakePreviewCatalog:
    async def chapter(self, chapter_id: str) -> dict:
        preview_text = "这是 VIP 预览章，仅提供部分正文内容。" * 18
        return {
            "implemented": True,
            "chapterId": chapter_id,
            "title": "第12章",
            "content": preview_text,
            "rawChapterUrl": "https://remote/preview/12",
            "chapterUrl": "https://remote/preview/12",
            "isPaid": True,
            "extra": {
                "previewOnly": True,
                "actualWords": 3200,
            },
            "debug": {},
        }


def seed_book(conn: sqlite3.Connection, aggregate_book_id: str) -> None:
    now = "2026-06-25T00:00:00+00:00"
    payload = {
        "name": "预览章测试书",
        "author": "测试作者",
        "sources": [
            {
                "sourceId": "qidian_com_web",
                "sourceName": "起点中文网(Web)",
                "bookId": "qidian_com_web:https://m.qidian.com/book/888888/",
                "bookUrl": "https://m.qidian.com/book/888888/",
                "score": 100,
            }
        ],
        "primarySourceId": "qidian_com_web",
        "primarySourceName": "起点中文网(Web)",
        "primaryBookId": "qidian_com_web:https://m.qidian.com/book/888888/",
        "primaryBookUrl": "https://m.qidian.com/book/888888/",
        "primaryTocUrl": "https://m.qidian.com/book/888888/catalog/",
        "startChapterIndex": 12,
        "autoArchiveOnComplete": True,
    }
    settings = {
        "aiAggregateEnabled": False,
        "aiPurifyEnabled": True,
        "autoTrackUpdates": True,
        "updateIntervalMinutes": 60,
        "supplementSourceConfig": {},
    }
    conn.execute(
        """
        INSERT INTO aggregate_book_tasks (
            aggregate_book_id, canonical_name, canonical_author, name, author, aggregate_payload_json,
            primary_book_id, primary_source_id, primary_source_name, primary_book_url, primary_toc_url,
            added_by_user_id, start_chapter_index, total_chapters_at_subscribe, initial_snapshot_last_index,
            backfill_started, auto_archive_on_complete, search_visibility_status, book_status, total_chapters,
            processed_chapters, visible_processed_chapters, failed_chapters, total_tokens, status,
            settings_json, current_policy_version, interval_minutes, error_count, last_error, ai_enabled,
            created_at, updated_at
        ) VALUES (?, '', '', '预览章测试书', '测试作者', ?, ?, ?, ?, ?, ?, 'tester', 12, 12, 12, 0, 1, 'hidden', 'ongoing', 12, 0, 0, 0, 0, 'active', ?, 1, 60, 0, '', 0, ?, ?)
        """,
        (
            aggregate_book_id,
            json.dumps(payload, ensure_ascii=False),
            payload["primaryBookId"],
            payload["primarySourceId"],
            payload["primarySourceName"],
            payload["primaryBookUrl"],
            payload["primaryTocUrl"],
            json.dumps(settings, ensure_ascii=False),
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO aggregate_book_sources (
            aggregate_book_id, source_id, source_book_id, source_name, source_book_url,
            role, score, enabled, last_seen_at, last_chapter_title, chapter_count, created_at, updated_at
        ) VALUES (?, 'qidian_com_web', ?, '起点中文网(Web)', ?, 'primary', 100, 1, ?, '', 12, ?, ?)
        """,
        (
            aggregate_book_id,
            payload["primaryBookId"],
            payload["primaryBookUrl"],
            now,
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO aggregate_chapter_tasks (
            chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title, status, placeholder,
            primary_source_chapter_url, created_at, updated_at
        ) VALUES (?, ?, ?, 12, '第12章', 'pending', 0, 'https://remote/preview/12', ?, ?)
        """,
        (
            "agg-preview-12",
            aggregate_book_id,
            "qidian_com_web:https://remote/preview/12",
            now,
            now,
        ),
    )
    conn.commit()


async def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="phase1_preview_")
    db_path = Path(tmpdir) / "phase1.db"
    initialize_database(db_path)

    aggregate_book_id = "phase1-preview-book"
    with sqlite3.connect(db_path) as conn:
        seed_book(conn, aggregate_book_id)

    processor = AggregateProcessor(db_path=db_path, ai_service=None)
    chapter_queue = processor._chapters_for_processing(aggregate_book_id, limit=1)
    if not chapter_queue:
        print("missing-processable-chapter")
        return 1

    print("chapter-queue:")
    print(json.dumps(chapter_queue, ensure_ascii=False, indent=2))

    result = await processor._process_chapter(FakePreviewCatalog(), chapter_queue[0])
    print("process-result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT status, source_word_count, preview_only, primary_source_chapter_url,
                   content_file_path, processed_content, policy_snapshot_json
            FROM aggregate_chapter_tasks
            WHERE chapter_id = 'agg-preview-12'
            """
        ).fetchone()

    chapter_file = Path(row[4]) if row and row[4] else None
    file_text = chapter_file.read_text(encoding="utf-8") if chapter_file and chapter_file.exists() else ""
    snapshot = json.loads(row[6] or "{}")
    state = {
        "status": row[0],
        "sourceWordCount": row[1],
        "previewOnly": bool(row[2]),
        "primarySourceChapterUrl": row[3],
        "contentFilePath": row[4],
        "contentLength": len(row[5] or ""),
        "traceHasPreviewOnly": "previewOnly: true" in file_text,
        "traceHasPreviewFallback": "selectedContentSource: preview_fallback" in file_text,
        "snapshotPreviewOnly": bool(snapshot.get("previewOnly")),
        "snapshotSelectedContentSource": snapshot.get("selectedContentSource", ""),
    }
    print("state:")
    print(json.dumps(state, ensure_ascii=False, indent=2))

    if not result.get("success"):
        print("expected preview fallback processing success")
        return 1
    if row[0] != "fallback":
        print("expected preview chapter to land as fallback")
        return 1
    if not bool(row[2]):
        print("expected preview_only to be persisted")
        return 1
    if row[1] != 3200:
        print("expected source word count to keep actual words")
        return 1
    if not row[4]:
        print("expected preview chapter file to be written")
        return 1
    if not state["traceHasPreviewOnly"] or not state["traceHasPreviewFallback"]:
        print("expected trace block preview markers")
        return 1
    if state["snapshotSelectedContentSource"] != "preview_fallback":
        print("expected preview fallback selected content source")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
