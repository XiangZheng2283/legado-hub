"""Tests for retry backoff logic and error classification in aggregate processor."""

import json
import sqlite3

import pytest

from app.services.aggregate_processor import (
    AggregateProcessor,
    classify_error,
    compute_next_retry_time,
    max_retries_reached,
)
from app.storage.db import initialize_database


def _setup_db(tmp_path, *, ai_enabled=True):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    if ai_enabled:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO admin_settings (key, value_json) VALUES (?, ?)",
                (
                    "contentWorkflow",
                    json.dumps(
                        {
                            "aiEnabled": True,
                            "autoAggregate": True,
                            "processAggregateOnRead": True,
                            "aggregateCheckIntervalMinutes": 10,
                            "purifyMode": "conservative",
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            conn.commit()
    return db_path


def _insert_chapter(db_path, aggregate_book_id, chapter_id, *, status="pending", retry_count=0, next_retry_time=None, last_error_code=""):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO aggregate_chapter_tasks
            (chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title, status,
             retry_count, next_retry_time, last_error_code, created_at, updated_at)
            VALUES (?, ?, ?, 1, 'test', ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (chapter_id, aggregate_book_id, chapter_id, status, retry_count, next_retry_time, last_error_code),
        )
        conn.commit()


def _insert_book(db_path, aggregate_book_id):
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO aggregate_book_tasks
            (aggregate_book_id, name, author, status, ai_enabled, created_at, updated_at)
            VALUES (?, 'test', 'test', 'active', 1, datetime('now'), datetime('now'))
            """,
            (aggregate_book_id,),
        )
        conn.commit()


# ── error classification ─────────────────────────────────────────────────────


def test_classify_error_empty_content():
    assert classify_error(ValueError("empty chapter content")) == "SOURCE_EMPTY_CONTENT"


def test_classify_error_timeout():
    import httpx
    assert classify_error(httpx.TimeoutException("timeout")) == "SOURCE_TIMEOUT"


def test_classify_error_ai_http_401():
    from app.ai.client import AIProviderHTTPError
    assert classify_error(AIProviderHTTPError(401, "Unauthorized")) == "SOURCE_AUTH_REQUIRED"


def test_classify_error_ai_http_429():
    from app.ai.client import AIProviderHTTPError
    assert classify_error(AIProviderHTTPError(429, "Rate limit")) == "AI_RATE_LIMITED"


def test_classify_error_ai_http_400():
    from app.ai.client import AIProviderHTTPError
    assert classify_error(AIProviderHTTPError(400, "Bad request")) == "AI_BAD_REQUEST"


def test_classify_error_ai_http_500():
    from app.ai.client import AIProviderHTTPError
    assert classify_error(AIProviderHTTPError(500, "Server error")) == "AI_TIMEOUT"


def test_classify_error_generic_timeout():
    assert classify_error(TimeoutError("connection timed out")) == "SOURCE_TIMEOUT"


def test_classify_error_not_configured():
    from app.ai.client import AIProviderNotConfiguredError
    assert classify_error(AIProviderNotConfiguredError("not configured")) == "AI_BAD_REQUEST"


def test_classify_error_unknown():
    assert classify_error(RuntimeError("something weird")) == "AI_TIMEOUT"


# ── retry delay computation ──────────────────────────────────────────────────


def test_compute_next_retry_time_first_retry():
    result = compute_next_retry_time(0)
    assert result is not None
    # Should be roughly 5 minutes from now
    assert "T" in result  # ISO format


def test_compute_next_retry_time_increments():
    times = [compute_next_retry_time(i) for i in range(5)]
    # Each should be later than the previous
    assert times == sorted(times)


def test_compute_next_retry_time_none_when_exhausted():
    result = compute_next_retry_time(5)
    assert result is None


# ── max retries check ────────────────────────────────────────────────────────


def test_max_retries_not_reached():
    assert max_retries_reached(0) is False
    assert max_retries_reached(4) is False


def test_max_retries_reached():
    assert max_retries_reached(5) is True
    assert max_retries_reached(10) is True


# ── no-retry error codes ─────────────────────────────────────────────────────


def test_ai_bad_request_skips_retry():
    """AI_BAD_REQUEST should not be retried — it's a config error."""
    from app.ai.client import AIProviderHTTPError
    error_code = classify_error(AIProviderHTTPError(400, "Bad model"))
    assert error_code == "AI_BAD_REQUEST"


# ── terminal error chapters excluded from queue ──────────────────────────────


def test_chapter_with_exhausted_retries_not_selected(tmp_path):
    """Chapters with retry_count >= 5 and next_retry_time=NULL must not be re-selected."""
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book-1")
    _insert_chapter(db_path, "book-1", "ch-1", status="error", retry_count=5, next_retry_time=None)

    processor = AggregateProcessor(db_path)
    chapters = processor._chapters_for_processing("book-1")

    ids = [c["chapterId"] for c in chapters]
    assert "ch-1" not in ids


def test_chapter_with_ai_bad_request_not_selected(tmp_path):
    """Chapters with last_error_code='AI_BAD_REQUEST' must not be re-selected."""
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book-1")
    _insert_chapter(
        db_path, "book-1", "ch-bad",
        status="error", retry_count=0, next_retry_time=None,
        last_error_code="AI_BAD_REQUEST",
    )

    processor = AggregateProcessor(db_path)
    chapters = processor._chapters_for_processing("book-1")

    ids = [c["chapterId"] for c in chapters]
    assert "ch-bad" not in ids


def test_pending_chapter_still_selected(tmp_path):
    """Pending chapters must still be selected normally."""
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book-1")
    _insert_chapter(db_path, "book-1", "ch-pending", status="pending")

    processor = AggregateProcessor(db_path)
    chapters = processor._chapters_for_processing("book-1")

    ids = [c["chapterId"] for c in chapters]
    assert "ch-pending" in ids


def test_retryable_error_with_future_retry_time_not_selected(tmp_path):
    """A retryable error whose next_retry_time is in the future must not be selected."""
    from datetime import datetime, timedelta, timezone
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book-1")
    _insert_chapter(
        db_path, "book-1", "ch-future",
        status="error", retry_count=1, next_retry_time=future,
        last_error_code="AI_RATE_LIMITED",
    )

    processor = AggregateProcessor(db_path)
    chapters = processor._chapters_for_processing("book-1")

    ids = [c["chapterId"] for c in chapters]
    assert "ch-future" not in ids
