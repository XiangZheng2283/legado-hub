"""Tests for shared-book discovery visibility counting in AggregateProcessor."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services.aggregate_processor import AggregateProcessor


def test_visible_processed_count_excludes_preview_chapters():
    db_path = Path(":memory:")
    processor = AggregateProcessor(db_path=":memory:")

    with sqlite3.connect(":memory:") as conn:
        conn.execute(
            """
            CREATE TABLE aggregate_book_tasks (
                aggregate_book_id TEXT PRIMARY KEY,
                start_chapter_index INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE aggregate_chapter_tasks (
                chapter_id TEXT PRIMARY KEY,
                aggregate_book_id TEXT,
                chapter_index INTEGER,
                status TEXT,
                preview_only INTEGER
            )
            """
        )
        conn.execute(
            "INSERT INTO aggregate_book_tasks VALUES (?, ?)",
            ("book-1", 1),
        )
        rows = [
            ("ch-1", "book-1", 1, "processed", 0),
            ("ch-2", "book-1", 2, "fallback", 0),
            ("ch-3", "book-1", 3, "fallback", 1),  # preview breaks the continuous readable run
            ("ch-4", "book-1", 4, "processed", 0),
        ]
        conn.executemany(
            "INSERT INTO aggregate_chapter_tasks VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        count = processor._visible_processed_count(conn, "book-1", 1)
        assert count == 2, "preview-only chapter must stop the readable count"
