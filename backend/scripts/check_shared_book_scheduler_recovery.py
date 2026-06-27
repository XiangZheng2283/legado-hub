#!/usr/bin/env python3
"""Operator verification script for scheduler startup-recovery behavior.

Verifies that:
- startup_recovery_scan runs once before periodic loop
- periodic loop waits for recovery completion
- recovery-processed books are skipped by the first periodic pass
- per-book locks prevent concurrent writes

Run from repo root:
    python backend/scripts/check_shared_book_scheduler_recovery.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.shared_book_lock import SharedBookLockService
from app.services.shared_book_scheduler import SharedBookScheduler
from app.services.shared_book_storage import SharedBookStorage


class FakeProcessor:
    def __init__(self):
        self.run_calls: list[str] = []
        self.due_books: list[dict] = []

    def list_due_books(self, limit: int = 10) -> list[dict]:
        return list(self.due_books[:limit])

    async def run_book_task(self, aggregate_book_id: str) -> dict:
        self.run_calls.append(aggregate_book_id)
        await asyncio.sleep(0)
        return {"bookId": aggregate_book_id, "success": True}


async def main() -> int:
    tmp_root = Path(__file__).resolve().parents[2] / ".tmp" / "scheduler-check"
    storage = SharedBookStorage(tmp_root / "library")
    lock_service = SharedBookLockService(storage=storage, ttl_seconds=5.0)
    processor = FakeProcessor()
    processor.due_books = [
        {"aggregateBookId": "book-recover", "payload": {"name": "恢复书", "author": "作者甲"}},
        {"aggregateBookId": "book-periodic", "payload": {"name": "周期书", "author": "作者乙"}},
    ]

    events: list[str] = []

    def recovery_scanner() -> list[dict]:
        events.append("recovery_scan")
        return [
            {"aggregateBookId": "book-recover", "payload": {"name": "恢复书", "author": "作者甲"}},
        ]

    scheduler = SharedBookScheduler(
        processor=processor,
        lock_service=lock_service,
        recovery_scanner=recovery_scanner,
    )

    original_process = scheduler._process_book

    async def instrumented_process(aggregate_book_id: str, *, trigger: str, payload=None):
        events.append(f"{trigger}:{aggregate_book_id}")
        return await original_process(aggregate_book_id, trigger=trigger, payload=payload)

    scheduler._process_book = instrumented_process

    recovery_result = await scheduler.startup_recovery_scan()
    periodic_result = await scheduler.run_periodic_once(wait_for_recovery=True)

    errors: list[str] = []
    if recovery_result["processedBooks"] != 1:
        errors.append(f"expected 1 recovery book, got {recovery_result['processedBooks']}")
    if periodic_result["processedBooks"] != 1:
        errors.append(f"expected 1 periodic book, got {periodic_result['processedBooks']}")
    if periodic_result.get("skippedStartupRecoveryProcessedBooks", 0) != 1:
        errors.append("recovery-processed book was not skipped by periodic pass")
    if events[:2] != ["recovery_scan", "startup_recovery_scan:book-recover"]:
        errors.append(f"unexpected event order: {events}")
    if "book_update_check:book-periodic" not in events:
        errors.append("periodic book did not run")
    if "book_update_check:book-recover" in events:
        errors.append("recovery book ran again during periodic pass")

    # Lock concurrency check: two workers cannot hold the same book lock.
    lease_a = lock_service.acquire(book_name="并发书", author="作者甲")
    lease_b = lock_service.acquire(book_name="并发书", author="作者甲")
    if lease_a is None or lease_b is not None:
        errors.append("per-book lock allowed concurrent acquisition")
    if lease_a is not None:
        lease_a.release()

    if errors:
        print("FAIL:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("OK: startup recovery ordering, periodic skip, and per-book lock checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
