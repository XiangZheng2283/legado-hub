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


def seed_book(conn: sqlite3.Connection, aggregate_book_id: str) -> None:
    now = "2026-06-25T00:00:00+00:00"
    payload = {
        "name": "第三方拒绝测试书",
        "author": "测试作者",
        "primarySourceId": "qidian_com_web",
        "primarySourceName": "起点中文网(Web)",
        "primaryBookId": "qidian_com_web:https://m.qidian.com/book/444444/",
        "primaryBookUrl": "https://m.qidian.com/book/444444/",
        "primaryTocUrl": "https://m.qidian.com/book/444444/catalog/",
        "sources": [
            {
                "sourceId": "qidian_com_web",
                "sourceName": "起点中文网(Web)",
                "bookId": "qidian_com_web:https://m.qidian.com/book/444444/",
                "bookUrl": "https://m.qidian.com/book/444444/",
                "score": 200,
            },
            {
                "sourceId": "third_party_a",
                "sourceName": "第三方 A",
                "bookId": "third_party_a:https://third.party/book/444444/",
                "bookUrl": "https://third.party/book/444444/",
                "score": 150,
            },
        ],
        "startChapterIndex": 8,
        "autoArchiveOnComplete": True,
    }
    settings = {
        "aiAggregateEnabled": False,
        "aiPurifyEnabled": False,
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
        ) VALUES (?, '', '', '第三方拒绝测试书', '测试作者', ?, ?, ?, ?, ?, ?, 'tester', 8, 8, 8, 0, 1, 'hidden', 'ongoing', 8, 0, 0, 0, 0, 'active', ?, 1, 60, 0, '', 0, ?, ?)
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
    conn.executemany(
        """
        INSERT INTO aggregate_book_sources (
            aggregate_book_id, source_id, source_book_id, source_name, source_book_url,
            role, score, enabled, last_seen_at, last_chapter_title, chapter_count, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, '', 8, ?, ?)
        """,
        [
            (
                aggregate_book_id,
                "qidian_com_web",
                "qidian_com_web:https://m.qidian.com/book/444444/",
                "起点中文网(Web)",
                "https://m.qidian.com/book/444444/",
                "primary",
                200,
                now,
                now,
                now,
            ),
            (
                aggregate_book_id,
                "third_party_a",
                "third_party_a:https://third.party/book/444444/",
                "第三方 A",
                "https://third.party/book/444444/",
                "candidate",
                150,
                now,
                now,
                now,
            ),
        ],
    )
    conn.execute(
        """
        INSERT INTO aggregate_chapter_tasks (
            chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title, status, placeholder,
            primary_source_chapter_url, created_at, updated_at
        ) VALUES (?, ?, ?, 8, '第八章 旧井', 'pending', 0, 'https://remote/official/8', ?, ?)
        """,
        (
            "agg-phase2-reject-8",
            aggregate_book_id,
            "qidian_com_web:https://remote/official/8",
            now,
            now,
        ),
    )
    conn.commit()


class FakeRejectCatalog:
    async def chapter(self, chapter_id: str) -> dict:
        if chapter_id == "qidian_com_web:https://remote/official/8":
            preview = "旧井边的冷风像刀背一样擦过砖缝，卢米安只看到水面上碎掉的月光和一团说不清的影子。" * 2
            return {
                "implemented": True,
                "chapterId": chapter_id,
                "title": "第八章 旧井",
                "content": preview,
                "rawChapterUrl": "https://remote/official/8",
                "chapterUrl": "https://remote/official/8",
                "isPaid": True,
                "extra": {"previewOnly": True, "actualWords": 2400},
                "debug": {},
            }
        if chapter_id == "third_party_a:https://third.party/chapter/wrong":
            content = "第8章 旧井\n这是一章完全不相干的内容，虽然标题看着像，但正文与预览毫无对应。" * 40
            return {
                "implemented": True,
                "chapterId": chapter_id,
                "title": "第8章 旧井",
                "content": content,
                "rawChapterUrl": "https://third.party/chapter/wrong",
                "chapterUrl": "https://third.party/chapter/wrong",
                "extra": {"actualWords": len(content)},
                "debug": {},
            }
        raise ValueError(f"unexpected chapter id: {chapter_id}")

    async def toc(self, book_id: str) -> dict:
        return {
            "implemented": True,
            "chapters": [
                {
                    "index": 8,
                    "title": "第8章 旧井",
                    "chapterId": "third_party_a:https://third.party/chapter/wrong",
                    "chapterUrl": "https://third.party/chapter/wrong",
                    "rawChapterUrl": "https://third.party/chapter/wrong",
                }
            ],
            "debug": {},
        }


async def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="phase2_reject_")
    db_path = Path(tmpdir) / "phase2.db"
    initialize_database(db_path)

    aggregate_book_id = "phase2-reject-book"
    with sqlite3.connect(db_path) as conn:
        seed_book(conn, aggregate_book_id)

    processor = AggregateProcessor(db_path=db_path, ai_service=None)
    chapter_queue = processor._chapters_for_processing(aggregate_book_id, limit=1)
    if not chapter_queue:
        print("missing-processable-chapter")
        return 1

    result = await processor._process_chapter(FakeRejectCatalog(), chapter_queue[0])
    print("process-result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT fallback_source_id, preview_only, processed_content, source_alignment_json
            FROM aggregate_chapter_tasks
            WHERE chapter_id = 'agg-phase2-reject-8'
            """
        ).fetchone()

    alignment = json.loads(row[3] or "{}")
    state = {
        "fallbackSourceId": row[0],
        "previewOnly": bool(row[1]),
        "hasForeignTail": "完全不相干的内容" in (row[2] or ""),
        "alignmentReason": alignment.get("alignmentReason", ""),
        "alignmentPassed": alignment.get("alignmentPassed"),
    }
    print("state:")
    print(json.dumps(state, ensure_ascii=False, indent=2))

    if row[0] != "qidian_com_web":
        print("expected mismatched candidate to be rejected")
        return 1
    if not bool(row[1]):
        print("expected chapter to remain preview fallback")
        return 1
    if state["hasForeignTail"]:
        print("expected mismatched candidate content to be rejected")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
