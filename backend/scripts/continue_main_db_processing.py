#!/usr/bin/env python3
"""Continue processing the active shared book in the main database.

This is a manual pump for the background aggregate processor; it is useful for
proving the main-db pipeline without waiting for the periodic scheduler.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Make app.* importable from scripts/
BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT / "backend"))

from app.services.aggregate_processor import AggregateProcessor
from app.storage.db import initialize_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("continue_main_db_processing")


async def run_rounds(db_path: Path, rounds: int, chapters_per_round: int) -> None:
    initialize_database(db_path)
    processor = AggregateProcessor(db_path=db_path)

    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    book_row = cur.execute(
        "SELECT aggregate_book_id, name, status, search_visibility_status, "
        "processed_chapters, total_chapters "
        "FROM aggregate_book_tasks WHERE status = 'active' LIMIT 1"
    ).fetchone()
    if book_row is None:
        logger.error("No active aggregate book found in %s", db_path)
        return

    book_id = book_row["aggregate_book_id"]
    pending = cur.execute(
        "SELECT COUNT(*) FROM aggregate_chapter_tasks "
        "WHERE aggregate_book_id = ? AND status = 'pending'",
        (book_id,),
    ).fetchone()[0]
    logger.info(
        "Book %s | status=%s visible=%s processed=%s pending=%s total=%s",
        book_id,
        book_row["status"],
        book_row["search_visibility_status"],
        book_row["processed_chapters"],
        pending,
        book_row["total_chapters"],
    )

    for r in range(1, rounds + 1):
        logger.info("=== round %s/%s ===", r, rounds)
        await processor.run_book_task(book_id)

        book_row = cur.execute(
            "SELECT processed_chapters, failed_chapters, "
            "visible_processed_chapters, status, search_visibility_status "
            "FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
            (book_id,),
        ).fetchone()
        pending = cur.execute(
            "SELECT COUNT(*) FROM aggregate_chapter_tasks "
            "WHERE aggregate_book_id = ? AND status = 'pending'",
            (book_id,),
        ).fetchone()[0]
        logger.info(
            "After round %s: processed=%s pending=%s failed=%s visible=%s status=%s",
            r,
            book_row["processed_chapters"],
            pending,
            book_row["failed_chapters"],
            book_row["visible_processed_chapters"],
            book_row["status"],
        )
        if book_row["status"] != "active":
            logger.info("Book status changed to %s, stopping.", book_row["status"])
            break

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=str(BACKEND_ROOT / "backend" / "data" / "app.db"))
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--chapters-per-round", type=int, default=20)
    args = parser.parse_args()

    asyncio.run(run_rounds(Path(args.db_path), args.rounds, args.chapters_per_round))


if __name__ == "__main__":
    main()
