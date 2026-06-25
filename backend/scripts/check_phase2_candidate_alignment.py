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
        "name": "第三方补全测试书",
        "author": "测试作者",
        "primarySourceId": "qidian_com_web",
        "primarySourceName": "起点中文网(Web)",
        "primaryBookId": "qidian_com_web:https://m.qidian.com/book/555555/",
        "primaryBookUrl": "https://m.qidian.com/book/555555/",
        "primaryTocUrl": "https://m.qidian.com/book/555555/catalog/",
        "sources": [
            {
                "sourceId": "qidian_com_web",
                "sourceName": "起点中文网(Web)",
                "bookId": "qidian_com_web:https://m.qidian.com/book/555555/",
                "bookUrl": "https://m.qidian.com/book/555555/",
                "score": 200,
            },
            {
                "sourceId": "third_party_a",
                "sourceName": "第三方 A",
                "bookId": "third_party_a:https://third.party/book/555555/",
                "bookUrl": "https://third.party/book/555555/",
                "score": 150,
            },
        ],
        "startChapterIndex": 12,
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
        ) VALUES (?, '', '', '第三方补全测试书', '测试作者', ?, ?, ?, ?, ?, ?, 'tester', 12, 12, 12, 0, 1, 'hidden', 'ongoing', 12, 0, 0, 0, 0, 'active', ?, 1, 60, 0, '', 0, ?, ?)
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
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, '', 12, ?, ?)
        """,
        [
            (
                aggregate_book_id,
                "qidian_com_web",
                "qidian_com_web:https://m.qidian.com/book/555555/",
                "起点中文网(Web)",
                "https://m.qidian.com/book/555555/",
                "primary",
                200,
                now,
                now,
                now,
            ),
            (
                aggregate_book_id,
                "third_party_a",
                "third_party_a:https://third.party/book/555555/",
                "第三方 A",
                "https://third.party/book/555555/",
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
        ) VALUES (?, ?, ?, 12, '第十二章 暗流', 'pending', 0, 'https://remote/official/12', ?, ?)
        """,
        (
            "agg-phase2-12",
            aggregate_book_id,
            "qidian_com_web:https://remote/official/12",
            now,
            now,
        ),
    )
    conn.commit()


class FakeCatalog:
    async def chapter(self, chapter_id: str) -> dict:
        if chapter_id == "qidian_com_web:https://remote/official/12":
            preview = "卢米安推开门，暗流在村庄边缘无声扩散。旧日回声贴着墙壁爬行，像是在等待谁先开口。" * 2
            return {
                "implemented": True,
                "chapterId": chapter_id,
                "title": "第十二章 暗流",
                "content": preview,
                "rawChapterUrl": "https://remote/official/12",
                "chapterUrl": "https://remote/official/12",
                "isPaid": True,
                "extra": {"previewOnly": True, "actualWords": 2600},
                "debug": {},
            }
        if chapter_id == "third_party_a:https://third.party/chapter/wrong":
            return {
                "implemented": True,
                "chapterId": chapter_id,
                "title": "第十二章 暗流",
                "content": "完全不相关的正文，讲的是另一条线，和预览内容对不上。" * 80,
                "rawChapterUrl": "https://third.party/chapter/wrong",
                "chapterUrl": "https://third.party/chapter/wrong",
                "extra": {"actualWords": 3200},
                "debug": {},
            }
        if chapter_id == "third_party_a:https://third.party/chapter/right":
            content = (
                "第十二章 暗流\n"
                "卢米安推开门，暗流在村庄边缘无声扩散。旧日回声贴着墙壁爬行，像是在等待谁先开口。"
                "他停在门槛前，听见院子里木桶轻轻碰撞，紧接着看见远处的火光被雾气折成两截。"
                "这章后续正文继续展开。"
            ) * 18
            return {
                "implemented": True,
                "chapterId": chapter_id,
                "title": "第12章 暗流",
                "content": content,
                "rawChapterUrl": "https://third.party/chapter/right",
                "chapterUrl": "https://third.party/chapter/right",
                "extra": {"actualWords": len(content)},
                "debug": {},
            }
        raise ValueError(f"unexpected chapter id: {chapter_id}")

    async def toc(self, book_id: str) -> dict:
        if book_id != "third_party_a:https://third.party/book/555555/":
            raise ValueError(f"unexpected toc book id: {book_id}")
        return {
            "implemented": True,
            "chapters": [
                {
                    "index": 12,
                    "title": "第12章 暗潮",
                    "chapterId": "third_party_a:https://third.party/chapter/wrong",
                    "chapterUrl": "https://third.party/chapter/wrong",
                    "rawChapterUrl": "https://third.party/chapter/wrong",
                },
                {
                    "index": 12,
                    "title": "第12章 暗流",
                    "chapterId": "third_party_a:https://third.party/chapter/right",
                    "chapterUrl": "https://third.party/chapter/right",
                    "rawChapterUrl": "https://third.party/chapter/right",
                },
            ],
            "debug": {},
        }


async def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="phase2_align_")
    db_path = Path(tmpdir) / "phase2.db"
    initialize_database(db_path)

    aggregate_book_id = "phase2-align-book"
    with sqlite3.connect(db_path) as conn:
        seed_book(conn, aggregate_book_id)

    processor = AggregateProcessor(db_path=db_path, ai_service=None)
    chapter_queue = processor._chapters_for_processing(aggregate_book_id, limit=1)
    if not chapter_queue:
        print("missing-processable-chapter")
        return 1

    result = await processor._process_chapter(FakeCatalog(), chapter_queue[0])
    print("process-result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT status, preview_only, fallback_source_id, processed_content, policy_snapshot_json, source_alignment_json
            FROM aggregate_chapter_tasks
            WHERE chapter_id = 'agg-phase2-12'
            """
        ).fetchone()

    snapshot = json.loads(row[4] or "{}")
    alignment = json.loads(row[5] or "{}")
    modification_trail = snapshot.get("modificationTrail", []) if isinstance(snapshot, dict) else []
    candidate_step = next(
        (item for item in modification_trail if isinstance(item, dict) and item.get("step") == "candidate_completion"),
        {},
    )
    state = {
        "status": row[0],
        "previewOnly": bool(row[1]),
        "fallbackSourceId": row[2],
        "selectedContentSource": snapshot.get("selectedContentSource", ""),
        "alignmentPassed": alignment.get("alignmentPassed"),
        "alignmentReason": alignment.get("alignmentReason", ""),
        "titleSimilarity": alignment.get("titleSimilarity", 0),
        "previewSimilarity": alignment.get("previewSimilarity", 0),
        "headPreviewSimilarity": alignment.get("headPreviewSimilarity", 0),
        "hasCompletedContent": "这章后续正文继续展开" in (row[3] or ""),
        "candidateStep": candidate_step,
    }
    print("state:")
    print(json.dumps(state, ensure_ascii=False, indent=2))

    if not result.get("success"):
        print("expected successful candidate completion")
        return 1
    if row[0] != "fallback":
        print("expected candidate completion to persist as fallback")
        return 1
    if row[2] != "third_party_a":
        print("expected matched candidate source to be persisted")
        return 1
    if not alignment.get("alignmentPassed"):
        print("expected candidate alignment to pass")
        return 1
    if candidate_step.get("candidateSourceId") != "third_party_a":
        print("expected trace to record candidate completion source")
        return 1
    if not state["hasCompletedContent"]:
        print("expected completed content to come from aligned candidate")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
