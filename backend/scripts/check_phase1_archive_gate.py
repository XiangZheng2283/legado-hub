from __future__ import annotations

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


def seed_book(
    conn: sqlite3.Connection,
    *,
    aggregate_book_id: str,
    auto_archive_on_complete: bool,
    pre_start_status: str,
    unfinished_statuses: list[str],
) -> None:
    now = "2026-06-25T00:00:00+00:00"
    payload = {
        "name": "归档闸门测试书",
        "author": "测试作者",
        "primarySourceId": "qidian_com_web",
        "primarySourceName": "起点中文网(Web)",
        "primaryBookId": "qidian_com_web:https://m.qidian.com/book/777777/",
        "primaryBookUrl": "https://m.qidian.com/book/777777/",
        "primaryTocUrl": "https://m.qidian.com/book/777777/catalog/",
        "sources": [],
        "startChapterIndex": 2,
        "autoArchiveOnComplete": auto_archive_on_complete,
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
        ) VALUES (?, '', '', '归档闸门测试书', '测试作者', ?, ?, ?, ?, ?, ?, 'tester', 2, 4, 4, 0, ?, 'hidden', 'completed', 4, 0, 0, 0, 0, 'active', '{}', 1, 60, 0, '', 0, ?, ?)
        """,
        (
            aggregate_book_id,
            json.dumps(payload, ensure_ascii=False),
            payload["primaryBookId"],
            payload["primarySourceId"],
            payload["primarySourceName"],
            payload["primaryBookUrl"],
            payload["primaryTocUrl"],
            1 if auto_archive_on_complete else 0,
            now,
            now,
        ),
    )
    rows = []
    statuses = [pre_start_status, *unfinished_statuses]
    for index, status in enumerate(statuses, start=1):
        rows.append(
            (
                f"{aggregate_book_id}-ch-{index}",
                aggregate_book_id,
                f"qidian_com_web:https://remote/chapter/{index}",
                index,
                f"第{index}章",
                status,
                1 if index == 1 and status == "placeholder" else 0,
                f"https://remote/chapter/{index}",
                now,
                now,
            )
        )
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


def book_state(conn: sqlite3.Connection, aggregate_book_id: str) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT status, search_visibility_status, visible_processed_chapters, archived_at
        FROM aggregate_book_tasks
        WHERE aggregate_book_id = ?
        """,
        (aggregate_book_id,),
    ).fetchone()
    return {
        "status": row[0],
        "searchVisibilityStatus": row[1],
        "visibleProcessedChapters": row[2],
        "archivedAt": row[3],
    }


def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="phase1_archive_gate_")
    db_path = Path(tmpdir) / "phase1.db"
    initialize_database(db_path)
    processor = AggregateProcessor(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        seed_book(
            conn,
            aggregate_book_id="book-active-unfinished",
            auto_archive_on_complete=True,
            pre_start_status="placeholder",
            unfinished_statuses=["processed", "pending", "processed"],
        )
        seed_book(
            conn,
            aggregate_book_id="book-archived-finished",
            auto_archive_on_complete=True,
            pre_start_status="processed",
            unfinished_statuses=["processed", "processed", "processed"],
        )
        seed_book(
            conn,
            aggregate_book_id="book-awaiting-finished",
            auto_archive_on_complete=False,
            pre_start_status="processed",
            unfinished_statuses=["processed", "processed", "processed"],
        )

    processor._refresh_shared_book_state("book-active-unfinished")
    processor._refresh_shared_book_state("book-archived-finished")
    processor._refresh_shared_book_state("book-awaiting-finished")

    with sqlite3.connect(db_path) as conn:
        unfinished = book_state(conn, "book-active-unfinished")
        archived = book_state(conn, "book-archived-finished")
        awaiting = book_state(conn, "book-awaiting-finished")

    print("states:")
    print(
        json.dumps(
            {
                "unfinished": unfinished,
                "archived": archived,
                "awaiting": awaiting,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if unfinished["status"] != "active":
        print("expected unfinished completed-book to stay active")
        return 1
    if archived["status"] != "archived":
        print("expected fully processed completed-book to auto archive")
        return 1
    if awaiting["status"] != "active":
        print("expected shared book to stay active when personal auto archive is disabled")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
