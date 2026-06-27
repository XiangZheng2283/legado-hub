"""Tests for retry backoff logic and error classification in aggregate processor."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services.aggregate_processor import (
    AggregateProcessor,
    classify_error,
    compute_next_retry_time,
    max_retries_reached,
)
from app.services.shared_book_errors import (
    SharedBookErrorCode,
    SharedBookRetryClass,
    classify_stage1_retry,
)
from app.storage.db import initialize_database


def _setup_db(tmp_path, *, ai_enabled=True):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    if ai_enabled:
        with sqlite3.connect(db_path) as conn:
            try:
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
            except sqlite3.OperationalError:
                pass
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
    assert classify_error(ValueError("empty chapter content")) == SharedBookErrorCode.S1_SOURCE_CONTENT_DEFERRED


def test_classify_error_timeout():
    import httpx
    assert classify_error(httpx.TimeoutException("timeout")) == SharedBookErrorCode.S1_SOURCE_FETCH_FAILED


def test_classify_error_ai_http_401():
    from app.ai.client import AIProviderHTTPError
    assert classify_error(AIProviderHTTPError(401, "Unauthorized")) == SharedBookErrorCode.S1_SOURCE_AUTH_REQUIRED


def test_classify_error_ai_http_429():
    from app.ai.client import AIProviderHTTPError
    assert classify_error(AIProviderHTTPError(429, "Rate limit")) == SharedBookErrorCode.S1_SOURCE_FETCH_FAILED


def test_classify_error_ai_http_400():
    from app.ai.client import AIProviderHTTPError
    assert classify_error(AIProviderHTTPError(400, "Bad request")) == SharedBookErrorCode.S1_SOURCE_CONFIGURATION_INVALID


def test_classify_error_ai_http_500():
    from app.ai.client import AIProviderHTTPError
    assert classify_error(AIProviderHTTPError(500, "Server error")) == SharedBookErrorCode.S1_SOURCE_FETCH_FAILED


def test_classify_error_generic_timeout():
    assert classify_error(TimeoutError("connection timed out")) == SharedBookErrorCode.S1_SOURCE_FETCH_FAILED


def test_classify_error_not_configured():
    from app.ai.client import AIProviderNotConfiguredError
    assert classify_error(AIProviderNotConfiguredError("not configured")) == SharedBookErrorCode.S1_SOURCE_CONFIGURATION_INVALID


def test_classify_error_unknown():
    assert classify_error(RuntimeError("something weird")) == SharedBookErrorCode.S1_SOURCE_FETCH_FAILED


@pytest.mark.parametrize(
    ("error_code", "expected_retry_class"),
    [
        (SharedBookErrorCode.S1_SOURCE_FETCH_FAILED, SharedBookRetryClass.SHORT_RETRY),
        (SharedBookErrorCode.S1_SOURCE_CONTENT_DEFERRED, SharedBookRetryClass.LONG_RETRY_SCAN),
        (SharedBookErrorCode.S1_SOURCE_AUTH_REQUIRED, SharedBookRetryClass.LONG_RETRY_SCAN),
        (SharedBookErrorCode.S1_SOURCE_CONFIGURATION_INVALID, SharedBookRetryClass.NO_RETRY),
    ],
)
def test_stage1_retry_classification(error_code, expected_retry_class):
    assert classify_stage1_retry(error_code) == expected_retry_class


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
    """Stage 1 config errors should not be retried."""
    from app.ai.client import AIProviderHTTPError
    error_code = classify_error(AIProviderHTTPError(400, "Bad model"))
    assert error_code == SharedBookErrorCode.S1_SOURCE_CONFIGURATION_INVALID


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
    """Chapters with a no-retry Stage 1 error must not be re-selected."""
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book-1")
    _insert_chapter(
        db_path, "book-1", "ch-bad",
        status="error", retry_count=0, next_retry_time=None,
        last_error_code=SharedBookErrorCode.S1_SOURCE_CONFIGURATION_INVALID,
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
        last_error_code=SharedBookErrorCode.S1_SOURCE_FETCH_FAILED,
    )

    processor = AggregateProcessor(db_path)
    chapters = processor._chapters_for_processing("book-1")

    ids = [c["chapterId"] for c in chapters]
    assert "ch-future" not in ids


def test_handle_processing_error_short_retry_updates_backoff(tmp_path):
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book-1")
    _insert_chapter(db_path, "book-1", "ch-short", status="pending", retry_count=0)
    processor = AggregateProcessor(db_path)

    result = processor._handle_processing_error(
        TimeoutError("connection timed out"),
        {"chapterId": "ch-short", "aggregateBookId": "book-1"},
        "source:short",
    )

    assert result["errorCode"] == SharedBookErrorCode.S1_SOURCE_FETCH_FAILED
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT retry_count, next_retry_time, last_error_code FROM aggregate_chapter_tasks WHERE chapter_id = ?",
            ("ch-short",),
        ).fetchone()
    assert row[0] == 1
    assert row[1]
    assert row[2] == SharedBookErrorCode.S1_SOURCE_FETCH_FAILED


def test_handle_processing_error_long_retry_defers_to_periodic_scan(tmp_path):
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book-1")
    _insert_chapter(db_path, "book-1", "ch-long", status="pending", retry_count=0)
    processor = AggregateProcessor(db_path)

    result = processor._handle_processing_error(
        ValueError("empty chapter content from all sources"),
        {"chapterId": "ch-long", "aggregateBookId": "book-1"},
        "source:long",
    )

    assert result["errorCode"] == SharedBookErrorCode.S1_SOURCE_CONTENT_DEFERRED
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT retry_count, next_retry_time, last_error_code FROM aggregate_chapter_tasks WHERE chapter_id = ?",
            ("ch-long",),
        ).fetchone()
    assert row[0] == 0
    assert row[1] is None
    assert row[2] == SharedBookErrorCode.S1_SOURCE_CONTENT_DEFERRED
    chapters = processor._chapters_for_processing("book-1")
    assert "ch-long" in [c["chapterId"] for c in chapters]


def test_handle_processing_error_no_retry_excludes_chapter(tmp_path):
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book-1")
    _insert_chapter(db_path, "book-1", "ch-none", status="pending", retry_count=0)
    processor = AggregateProcessor(db_path)

    from app.ai.client import AIProviderNotConfiguredError

    result = processor._handle_processing_error(
        AIProviderNotConfiguredError("not configured"),
        {"chapterId": "ch-none", "aggregateBookId": "book-1"},
        "source:none",
    )

    assert result["errorCode"] == SharedBookErrorCode.S1_SOURCE_CONFIGURATION_INVALID
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT retry_count, next_retry_time, last_error_code FROM aggregate_chapter_tasks WHERE chapter_id = ?",
            ("ch-none",),
        ).fetchone()
    assert row[0] == 0
    assert row[1] is None
    assert row[2] == SharedBookErrorCode.S1_SOURCE_CONFIGURATION_INVALID
    chapters = processor._chapters_for_processing("book-1")
    assert "ch-none" not in [c["chapterId"] for c in chapters]
