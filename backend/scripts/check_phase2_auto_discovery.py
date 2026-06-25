from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.aggregate_processor import AggregateProcessor
from app.source_plugins.id_codec import decode_book_id
from app.storage.db import initialize_database


def seed_book(conn: sqlite3.Connection, aggregate_book_id: str) -> None:
    now = "2026-06-25T00:00:00+00:00"
    payload = {
        "name": "自动补源测试书",
        "author": "测试作者",
        "primarySourceId": "qidian_com_web",
        "primarySourceName": "起点中文网(Web)",
        "primaryBookId": "qidian_com_web:https://m.qidian.com/book/333333/",
        "primaryBookUrl": "https://m.qidian.com/book/333333/",
        "primaryTocUrl": "https://m.qidian.com/book/333333/catalog/",
        "sources": [
            {
                "sourceId": "qidian_com_web",
                "sourceName": "起点中文网(Web)",
                "bookId": "qidian_com_web:https://m.qidian.com/book/333333/",
                "bookUrl": "https://m.qidian.com/book/333333/",
                "score": 200,
            }
        ],
        "startChapterIndex": 5,
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
        ) VALUES (?, '', '', '自动补源测试书', '测试作者', ?, ?, ?, ?, ?, ?, 'tester', 5, 5, 5, 0, 1, 'hidden', 'ongoing', 5, 0, 0, 0, 0, 'active', ?, 1, 60, 0, '', 0, ?, ?)
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
        ) VALUES (?, 'qidian_com_web', ?, '起点中文网(Web)', ?, 'primary', 200, 1, ?, '', 5, ?, ?)
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
        ) VALUES (?, ?, ?, 5, '第五章 雨幕', 'pending', 0, 'https://remote/official/5', ?, ?)
        """,
        (
            "agg-phase2-auto-5",
            aggregate_book_id,
            "qidian_com_web:https://remote/official/5",
            now,
            now,
        ),
    )
    conn.commit()


class FakeCatalog:
    async def chapter(self, chapter_id: str) -> dict:
        if chapter_id == "qidian_com_web:https://remote/official/5":
            preview = "雨幕压低了整条街的声音，卢米安在门檐下停住脚步，只看见灯火被拉成一条模糊的线。" * 2
            return {
                "implemented": True,
                "chapterId": chapter_id,
                "title": "第五章 雨幕",
                "content": preview,
                "rawChapterUrl": "https://remote/official/5",
                "chapterUrl": "https://remote/official/5",
                "isPaid": True,
                "extra": {"previewOnly": True, "actualWords": 2200},
                "debug": {},
            }
        if chapter_id == "third_party_a:https://third.party/chapter/right":
            content = (
                "第五章 雨幕\n"
                "雨幕压低了整条街的声音，卢米安在门檐下停住脚步，只看见灯火被拉成一条模糊的线。"
                "风从巷子尽头穿过来，带着潮湿木头和煤灰的味道。"
                "这章后续正文继续补全。"
            ) * 18
            return {
                "implemented": True,
                "chapterId": chapter_id,
                "title": "第5章 雨幕",
                "content": content,
                "rawChapterUrl": "https://third.party/chapter/right",
                "chapterUrl": "https://third.party/chapter/right",
                "extra": {"actualWords": len(content)},
                "debug": {},
            }
        raise ValueError(f"unexpected chapter id: {chapter_id}")

    async def toc(self, book_id: str) -> dict:
        source_id, raw_url = decode_book_id(book_id)
        if source_id != "third_party_a" or raw_url != "https://third.party/book/333333/":
            raise ValueError(f"unexpected toc book id: {book_id}")
        return {
            "implemented": True,
            "chapters": [
                {
                    "index": 5,
                    "title": "第5章 雨幕",
                    "chapterId": "third_party_a:https://third.party/chapter/right",
                    "chapterUrl": "https://third.party/chapter/right",
                    "rawChapterUrl": "https://third.party/chapter/right",
                }
            ],
            "debug": {},
        }


class FakeScheduler:
    def __init__(self) -> None:
        self.config = {"max_concurrency": 3}
        self._plugin = SimpleNamespace(
            metadata=SimpleNamespace(id="third_party_a", name="第三方 A", is_official_source=lambda: False),
            capabilities=["search"],
        )

    def _enabled_plugins(self):
        return [self._plugin]

    def _search_priority_plugins(self, plugins):
        return plugins

    async def search_one(self, source_id: str, keyword: str, page: int):
        return {
            "items": [
                {
                    "sourceId": "third_party_a",
                    "sourceName": "第三方 A",
                    "name": "自动补源测试书",
                    "author": "测试作者",
                    "rawBookUrl": "https://third.party/book/333333/",
                    "bookUrl": "https://third.party/book/333333/",
                    "score": 180,
                    "lastChapter": "第5章 雨幕",
                }
            ]
        }


async def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="phase2_auto_discovery_")
    db_path = Path(tmpdir) / "phase2.db"
    initialize_database(db_path)

    aggregate_book_id = "phase2-auto-book"
    with sqlite3.connect(db_path) as conn:
        seed_book(conn, aggregate_book_id)

    processor = AggregateProcessor(db_path=db_path, ai_service=None)
    chapter_queue = processor._chapters_for_processing(aggregate_book_id, limit=1)
    if not chapter_queue:
        print("missing-processable-chapter")
        return 1

    with patch("app.source_plugins.scheduler.get_plugin_scheduler", return_value=FakeScheduler()):
        result = await processor._process_chapter(FakeCatalog(), chapter_queue[0])
    print("process-result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT fallback_source_id, processed_content, source_alignment_json
            FROM aggregate_chapter_tasks
            WHERE chapter_id = 'agg-phase2-auto-5'
            """
        ).fetchone()
        discovered = conn.execute(
            """
            SELECT source_id, source_book_id, role
            FROM aggregate_book_sources
            WHERE aggregate_book_id = ? AND source_id = 'third_party_a'
            """,
            (aggregate_book_id,),
        ).fetchone()

    alignment = json.loads(row[2] or "{}")
    state = {
        "fallbackSourceId": row[0],
        "hasCompletedContent": "这章后续正文继续补全" in (row[1] or ""),
        "alignmentPassed": alignment.get("alignmentPassed"),
        "alignmentReason": alignment.get("alignmentReason", ""),
        "discoveredSource": {
            "sourceId": discovered[0] if discovered else "",
            "sourceBookId": discovered[1] if discovered else "",
            "role": discovered[2] if discovered else "",
        },
    }
    print("state:")
    print(json.dumps(state, ensure_ascii=False, indent=2))

    if row[0] != "third_party_a":
        print("expected auto-discovered candidate source to complete preview chapter")
        return 1
    if not state["hasCompletedContent"]:
        print("expected content to come from auto-discovered candidate")
        return 1
    if not discovered:
        print("expected discovered source to be persisted")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
