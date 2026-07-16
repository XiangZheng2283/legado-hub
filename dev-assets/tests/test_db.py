"""Tests for database initialization."""

import sqlite3
from pathlib import Path

import pytest

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
        "books",
        "chapters",
        "update_tasks",
        "book_cache",
        "toc_cache",
        "chapter_cache",
        "book_records",
        "book_search_cache",
        "search_jobs",
        "search_results",
        "aggregate_book_tasks",
        "user_book_subscriptions",
        "aggregate_chapter_tasks",
        "aggregate_book_sources",
        "aggregate_operation_logs",
        "aggregate_source_snapshots",
        "aggregate_ai_usage",
        "user_sessions",
        "users",
    }
    assert expected.issubset(tables)

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(aggregate_chapter_tasks)")}
        assert "ai_self_score" in columns
        columns = {row[1] for row in conn.execute("PRAGMA table_info(aggregate_ai_usage)")}
        assert "ai_self_score" in columns
        version = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'version'"
        ).fetchone()
        assert version == ("9",)

        foreign_keys = conn.execute(
            "PRAGMA foreign_key_list(user_book_subscriptions)"
        ).fetchall()
        assert {(row[2], row[3], row[4], row[6]) for row in foreign_keys} == {
            ("users", "user_id", "user_id", "CASCADE"),
            ("aggregate_book_tasks", "aggregate_book_id", "aggregate_book_id", "CASCADE"),
        }
        indexes = {
            row[1] for row in conn.execute("PRAGMA index_list(user_book_subscriptions)")
        }
        assert "idx_user_book_subscriptions_user_status" in indexes
        assert "idx_user_book_subscriptions_book" in indexes


def test_initialize_database_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    initialize_database(db_path)
    assert db_path.exists()


def test_upgrade_preserves_users_and_sessions(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash, role) VALUES ('u1', 'reader', 'hash', 'user')"
        )
        conn.execute(
            "INSERT INTO user_sessions (session_id, user_id, expires_at) VALUES ('s1', 'u1', '2099-01-01')"
        )
        conn.execute("DROP TABLE user_book_subscriptions")
        conn.execute("UPDATE schema_meta SET value = '8' WHERE key = 'version'")
        conn.commit()

    initialize_database(db_path)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT username FROM users WHERE user_id = 'u1'").fetchone() == ("reader",)
        assert conn.execute("SELECT user_id FROM user_sessions WHERE session_id = 's1'").fetchone() == ("u1",)
        assert conn.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone() == ("9",)
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'user_book_subscriptions'"
        ).fetchone() == (1,)


def test_subscription_constraints_and_cascade(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash, role) VALUES ('u1', 'reader', 'hash', 'user')"
        )
        conn.execute(
            "INSERT INTO aggregate_book_tasks (aggregate_book_id, name) VALUES ('b1', 'Book')"
        )
        conn.execute(
            "INSERT INTO user_book_subscriptions (user_id, aggregate_book_id) VALUES ('u1', 'b1')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO user_book_subscriptions (user_id, aggregate_book_id, status) VALUES ('u1', 'b2', 'invalid')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO user_book_subscriptions (user_id, aggregate_book_id, start_chapter_index) VALUES ('u1', 'b1', 0)"
            )
        conn.execute("DELETE FROM aggregate_book_tasks WHERE aggregate_book_id = 'b1'")
        assert conn.execute(
            "SELECT 1 FROM user_book_subscriptions WHERE aggregate_book_id = 'b1'"
        ).fetchone() is None
