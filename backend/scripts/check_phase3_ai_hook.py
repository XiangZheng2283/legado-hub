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


class FakeAIService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def process_official_full(self, *, book_name: str, author: str, title: str, content: str) -> dict:
        self.calls.append(
            {
                "kind": "official_full",
                "bookName": book_name,
                "author": author,
                "title": title,
                "contentLength": len(content),
            }
        )
        return {
            "status": "processed",
            "content": content + "\n[AI-PURIFIED]",
            "aiModel": "fake-phase3-model",
            "selfScore": 0.99,
            "promptTokens": 128,
            "completionTokens": 256,
            "totalTokens": 384,
            "latencyMs": 42,
        }


class FakeCatalog:
    async def chapter(self, chapter_id: str) -> dict:
        content = ("这是用于 AI 净化挂点验证的完整正文内容，长度足够判定为全文，"
                   "同时要与源站总字数接近，避免被识别成预览。") * 40
        return {
            "implemented": True,
            "chapterId": chapter_id,
            "title": "第12章",
            "content": content,
            "rawChapterUrl": "https://remote/chapter/12",
            "chapterUrl": "https://remote/chapter/12",
            "extra": {"actualWords": len(content)},
            "debug": {},
        }


def seed_book(conn: sqlite3.Connection, aggregate_book_id: str) -> None:
    now = "2026-06-25T00:00:00+00:00"
    payload = {
        "name": "AI 挂点测试书",
        "author": "测试作者",
        "sources": [
            {
                "sourceId": "qidian_com_web",
                "sourceName": "起点中文网(Web)",
                "bookId": "qidian_com_web:https://m.qidian.com/book/999999/",
                "bookUrl": "https://m.qidian.com/book/999999/",
                "score": 100,
            }
        ],
        "primarySourceId": "qidian_com_web",
        "primarySourceName": "起点中文网(Web)",
        "primaryBookId": "qidian_com_web:https://m.qidian.com/book/999999/",
        "primaryBookUrl": "https://m.qidian.com/book/999999/",
        "primaryTocUrl": "https://m.qidian.com/book/999999/catalog/",
        "startChapterIndex": 12,
        "autoArchiveOnComplete": True,
    }
    settings = {
        "aiAggregateEnabled": True,
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
        ) VALUES (?, '', '', 'AI 挂点测试书', '测试作者', ?, ?, ?, ?, ?, ?, 'tester', 12, 12, 12, 0, 1, 'hidden', 'ongoing', 12, 0, 0, 0, 0, 'active', ?, 1, 60, 0, '', 1, ?, ?)
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
        ) VALUES (?, ?, ?, 12, '第12章', 'pending', 0, 'https://remote/chapter/12', ?, ?)
        """,
        (
            "agg-ai-12",
            aggregate_book_id,
            "qidian_com_web:https://remote/chapter/12",
            now,
            now,
        ),
    )
    conn.commit()


async def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="phase3_ai_")
    db_path = Path(tmpdir) / "phase3.db"
    initialize_database(db_path)

    aggregate_book_id = "phase3-ai-book"
    with sqlite3.connect(db_path) as conn:
        seed_book(conn, aggregate_book_id)

    ai_service = FakeAIService()
    processor = AggregateProcessor(db_path=db_path, ai_service=ai_service)
    chapter_queue = processor._chapters_for_processing(aggregate_book_id, limit=1)
    if not chapter_queue:
        print("missing-processable-chapter")
        return 1

    print("chapter-queue:")
    print(json.dumps(chapter_queue, ensure_ascii=False, indent=2))

    result = await processor._process_chapter(FakeCatalog(), chapter_queue[0])
    print("process-result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("ai-calls:")
    print(json.dumps(ai_service.calls, ensure_ascii=False, indent=2))

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT status, ai_model, ai_total_tokens, processed_content, policy_snapshot_json
            FROM aggregate_chapter_tasks
            WHERE chapter_id = 'agg-ai-12'
            """
        ).fetchone()

    snapshot = json.loads(row[4] or "{}")
    state = {
        "status": row[0],
        "aiModel": row[1],
        "aiTotalTokens": row[2],
        "hasAiMarker": "[AI-PURIFIED]" in (row[3] or ""),
        "traceSelectedContentSource": snapshot.get("selectedContentSource", ""),
        "traceFinalContentHash": snapshot.get("finalContentHash", ""),
        "tracePreviewOnly": snapshot.get("previewOnly", None),
    }
    print("state:")
    print(json.dumps(state, ensure_ascii=False, indent=2))

    if not result.get("success"):
        print("expected successful AI hook processing")
        return 1
    if len(ai_service.calls) != 1:
        print("expected exactly one AI call")
        return 1
    if row[1] != "fake-phase3-model":
        print("expected ai_model to be persisted")
        return 1
    if row[2] != 384:
        print("expected ai_total_tokens to be persisted")
        return 1
    if not state["hasAiMarker"]:
        print("expected processed content to include AI marker")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
