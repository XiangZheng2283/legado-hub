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


def seed_book(conn: sqlite3.Connection, aggregate_book_id: str, total_chapters: int) -> None:
    now = "2026-06-25T00:00:00+00:00"
    payload = {
        "name": "Bootstrap 窗口测试书",
        "author": "测试作者",
        "primarySourceId": "qidian_com_web",
        "primarySourceName": "起点中文网(Web)",
        "primaryBookId": "qidian_com_web:https://m.qidian.com/book/666666/",
        "primaryBookUrl": "https://m.qidian.com/book/666666/",
        "primaryTocUrl": "https://m.qidian.com/book/666666/catalog/",
        "sources": [],
        "startChapterIndex": 1,
        "autoArchiveOnComplete": True,
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
        ) VALUES (?, '', '', 'Bootstrap 窗口测试书', '测试作者', ?, ?, ?, ?, ?, ?, 'tester', 1, ?, ?, 0, 1, 'hidden', 'ongoing', ?, 0, 0, 0, 0, 'active', '{}', 1, 60, 0, '', 0, ?, ?)
        """,
        (
            aggregate_book_id,
            json.dumps(payload, ensure_ascii=False),
            payload["primaryBookId"],
            payload["primarySourceId"],
            payload["primarySourceName"],
            payload["primaryBookUrl"],
            payload["primaryTocUrl"],
            total_chapters,
            total_chapters,
            total_chapters,
            now,
            now,
        ),
    )
    rows = [
        (
            f"{aggregate_book_id}-ch-{index}",
            aggregate_book_id,
            f"qidian_com_web:https://remote/chapter/{index}",
            index,
            f"第{index}章",
            "pending",
            0,
            f"https://remote/chapter/{index}",
            now,
            now,
        )
        for index in range(1, total_chapters + 1)
    ]
    conn.executemany(
        """
        INSERT INTO aggregate_chapter_tasks (
            chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title, status,
            placeholder, primary_source_chapter_url, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()


class ProbeProcessor(AggregateProcessor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: list[int] = []

    async def run_book_task(self, aggregate_book_id: str, chapter_limit: int = 5) -> dict:
        self.calls.append(int(chapter_limit))
        with self._conn() as conn:
            pending_rows = conn.execute(
                """
                SELECT chapter_id
                FROM aggregate_chapter_tasks
                WHERE aggregate_book_id = ? AND status = 'pending'
                ORDER BY chapter_index ASC
                LIMIT ?
                """,
                (aggregate_book_id, chapter_limit),
            ).fetchall()
            for (chapter_id,) in pending_rows:
                conn.execute(
                    """
                    UPDATE aggregate_chapter_tasks
                    SET status = 'processed', placeholder = 0, updated_at = ?
                    WHERE chapter_id = ?
                    """,
                    (self._now(), chapter_id),
                )
            conn.commit()
        self._refresh_shared_book_state(aggregate_book_id)
        return {
            "bookId": aggregate_book_id,
            "success": True,
            "processedChapters": len(pending_rows),
            "chapterLimit": chapter_limit,
        }


async def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="phase1_bootstrap_window_")
    db_path = Path(tmpdir) / "phase1.db"
    initialize_database(db_path)

    aggregate_book_id = "phase1-bootstrap-book"
    with sqlite3.connect(db_path) as conn:
        seed_book(conn, aggregate_book_id, total_chapters=65)

    processor = ProbeProcessor(db_path=db_path)
    result = await processor.bootstrap_book_until_visible(aggregate_book_id, max_rounds=1)
    print("bootstrap-result:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("calls:")
    print(json.dumps(processor.calls, ensure_ascii=False, indent=2))

    with sqlite3.connect(db_path) as conn:
        processed = conn.execute(
            """
            SELECT COUNT(*)
            FROM aggregate_chapter_tasks
            WHERE aggregate_book_id = ? AND status = 'processed'
            """,
            (aggregate_book_id,),
        ).fetchone()[0]

    print("processed:", processed)
    if not processor.calls or processor.calls[0] < 50:
        print("expected bootstrap window to be widened to at least 50")
        return 1
    if processed < 50:
        print("expected first bootstrap round to process at least 50 chapters")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
