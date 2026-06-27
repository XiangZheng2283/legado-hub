#!/usr/bin/env python3
"""Operator verification script for source-map refresh-before-bootstrap rule.

Checks that:
- enqueue_initial_subscription produces source-map-refresh before bootstrap
- bootstrap is deferred until source-map refresh completes
- discovery threshold gating works via LibraryBooksService

Run from repo root:
    python backend/scripts/check_shared_book_source_map_refresh.py
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.library_books import LibraryBooksService
from app.services.shared_book_scheduler import SharedBookScheduler
from app.storage.db import initialize_database


class FakeProcessor:
    def __init__(self):
        self.run_calls: list[str] = []
        self.bootstrap_calls: list[str] = []
        self.due_books: list[dict] = []

    def list_due_books(self, limit: int = 10) -> list[dict]:
        return list(self.due_books[:limit])

    async def run_book_task(self, aggregate_book_id: str) -> dict:
        self.run_calls.append(aggregate_book_id)
        await asyncio.sleep(0)
        return {"bookId": aggregate_book_id, "success": True}

    async def bootstrap_book_until_visible(self, aggregate_book_id: str, max_rounds: int = 20) -> dict:
        self.bootstrap_calls.append(aggregate_book_id)
        await asyncio.sleep(0)
        return {"bookId": aggregate_book_id, "success": True, "visible": True}


class FakeSourceMapService:
    def __init__(self):
        self.refresh_calls: list[tuple[str, dict | None, bool]] = []
        self.completed: set[str] = set()
        self.refresh_started = asyncio.Event()
        self.release_refresh = asyncio.Event()

    def should_refresh(self, aggregate_book_id: str, *, payload=None):
        return (aggregate_book_id not in self.completed, "missing_health")

    async def refresh_for_book(self, aggregate_book_id: str, *, payload=None, force: bool = False):
        self.refresh_calls.append((aggregate_book_id, payload, force))
        self.refresh_started.set()
        await self.release_refresh.wait()
        self.completed.add(aggregate_book_id)
        return {"bookId": aggregate_book_id, "success": True, "refreshed": True}


async def main() -> int:
    errors: list[str] = []

    # 1. Scheduler ordering check.
    processor = FakeProcessor()
    source_map_service = FakeSourceMapService()
    scheduler = SharedBookScheduler(
        processor=processor,
        recovery_scanner=lambda: [],
        source_map_service=source_map_service,
    )
    scheduler._recovery_complete.set()

    scheduler.enqueue_initial_subscription(
        "book-subscribe",
        payload={"name": "订阅书", "author": "作者甲"},
        book_name="订阅书",
        author="作者甲",
    )

    # First pass: source-map refresh is blocked, bootstrap must be deferred.
    first_task = asyncio.create_task(
        scheduler.run_periodic_once(wait_for_recovery=True, include_due_books=False)
    )
    await source_map_service.refresh_started.wait()
    await asyncio.sleep(0.05)

    if processor.bootstrap_calls:
        errors.append(f"bootstrap ran before source-map refresh completed: {processor.bootstrap_calls}")

    # Release refresh: source-map refresh completes, then bootstrap runs (same or next pass).
    source_map_service.release_refresh.set()
    second_result = await first_task

    second_triggers = [item["trigger"] for item in second_result.get("items", [])]
    if second_triggers not in (["book_source_map_refresh"], ["book_source_map_refresh", "book_bootstrap"]):
        errors.append(f"unexpected triggers after releasing refresh: {second_triggers}")

    if second_triggers == ["book_source_map_refresh"]:
        third_result = await scheduler.run_periodic_once(wait_for_recovery=True, include_due_books=False)
        third_triggers = [item["trigger"] for item in third_result.get("items", [])]
        if third_triggers != ["book_bootstrap"]:
            errors.append(f"expected book_bootstrap in follow-up pass, got {third_triggers}")

    if "book_bootstrap" not in second_triggers and "book_bootstrap" not in (third_triggers if "third_result" in dir() else []):
        errors.append("book_bootstrap never ran after source-map refresh completed")

    # 2. Discovery threshold gating check.
    db_path = Path(__file__).resolve().parents[2] / ".tmp" / "source-map-check" / "library.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    initialize_database(db_path)
    service = LibraryBooksService(db_path=db_path)

    with service._conn() as conn:
        conn.execute(
            """
            INSERT INTO aggregate_book_tasks (
                aggregate_book_id, canonical_name, canonical_author, name, author,
                aggregate_payload_json, primary_book_id, primary_source_id,
                search_visibility_status, processed_chapters, visible_processed_chapters,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            ("book-below", service._canonical_name("测试小说"), service._canonical_author("作者甲"),
             "测试小说", "作者甲", "src-a:book-1", "src-a", "visible", 49, 49, "active"),
        )
        conn.execute(
            """
            INSERT INTO aggregate_book_tasks (
                aggregate_book_id, canonical_name, canonical_author, name, author,
                aggregate_payload_json, primary_book_id, primary_source_id,
                search_visibility_status, processed_chapters, visible_processed_chapters,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            ("book-above", service._canonical_name("测试小说2"), service._canonical_author("作者甲"),
             "测试小说2", "作者甲", "src-a:book-2", "src-a", "visible", 50, 50, "active"),
        )
    conn.commit()

    below_items = service.build_search_injected_items_for_keyword("测试小说", min_readable_chapters=50)
    above_items = service.build_search_injected_items_for_keyword("测试小说2", min_readable_chapters=50)

    if any(item["aggregateBookId"] == "book-below" for item in below_items):
        errors.append("book with 49 readable chapters passed discovery threshold of 50")
    if not any(item["aggregateBookId"] == "book-above" for item in above_items):
        errors.append("book with 50 readable chapters did not pass discovery threshold of 50")

    if errors:
        print("FAIL:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("OK: source-map refresh ordering and discovery threshold checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
