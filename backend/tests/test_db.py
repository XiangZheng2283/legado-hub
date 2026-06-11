"""Tests for database initialization."""

import sqlite3
from pathlib import Path

from app.storage.db import initialize_database


def test_initialize_database(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    result = initialize_database(db_path)
    assert Path(result).exists()

    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}

    expected = {
        "schema_meta",
        "source_registry",
        "books",
        "chapters",
        "update_tasks",
        "aggregate_book_tasks",
        "aggregate_chapter_tasks",
    }
    assert expected.issubset(tables)


def test_initialize_database_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    initialize_database(db_path)
    assert db_path.exists()






