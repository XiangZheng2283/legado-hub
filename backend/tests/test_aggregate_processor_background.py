"""Tests for AggregateProcessor background loop, run_due_once, list_due_books,
and _chapters_for_processing.

Covers: restart recovery observability, disabled-reason reporting, due-book
selection, and chapter filtering logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.services.aggregate_processor import AggregateProcessor, ERROR_CODES_NO_RETRY
from app.services.aggregate_settings import RETRY_DELAYS_MINUTES
from app.storage.db import initialize_database


# ── helpers ──────────────────────────────────────────────────────────────────


def _setup_db(
    tmp_path,
    *,
    ai_enabled: bool = True,
    auto_aggregate: bool = True,
    process_on_read: bool = True,
    purify: str = "conservative",
):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    if ai_enabled or not ai_enabled:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO admin_settings (key, value_json) VALUES (?, ?)",
                (
                    "contentWorkflow",
                    json.dumps(
                        {
                            "aiEnabled": ai_enabled,
                            "autoAggregate": auto_aggregate,
                            "processAggregateOnRead": process_on_read,
                            "aggregateCheckIntervalMinutes": 10,
                            "purifyMode": purify,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            conn.commit()
    return db_path


def _insert_book(
    db_path,
    book_id: str,
    *,
    status: str = "active",
    next_check_time: str | None = None,
):
    now = datetime.now(timezone.utc)
    if next_check_time is None:
        next_check_time = (now - timedelta(minutes=1)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO aggregate_book_tasks
               (aggregate_book_id, name, author, primary_book_id, primary_source_id,
                aggregate_payload_json, status, interval_minutes, next_check_time,
                ai_enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 10, ?, 1, ?, ?)""",
            (
                book_id,
                f"Book {book_id}",
                "Author",
                f"src:{book_id}",
                "src",
                json.dumps({"name": f"Book {book_id}", "sources": []}),
                status,
                next_check_time,
                now.isoformat(),
                now.isoformat(),
            ),
        )
        conn.commit()


def _insert_chapter(
    db_path,
    book_id: str,
    index: int = 1,
    *,
    status: str = "pending",
    next_retry_time: str | None = None,
    last_error_code: str = "",
    retry_count: int = 0,
):
    ch_id = f"{book_id}:ch{index}"
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO aggregate_chapter_tasks
               (chapter_id, aggregate_book_id, source_chapter_id, chapter_index,
                title, status, next_retry_time, last_error_code, retry_count,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ch_id,
                book_id,
                f"src:ch{index}",
                index,
                f"Chapter {index}",
                status,
                next_retry_time,
                last_error_code,
                retry_count,
                now,
                now,
            ),
        )
        conn.commit()
    return ch_id


# ── run_due_once: disabled reasons ───────────────────────────────────────────


def test_run_due_once_returns_disabled_when_ai_enabled_false(tmp_path):
    db_path = _setup_db(tmp_path, ai_enabled=False)
    processor = AggregateProcessor(db_path)

    result = asyncio.run(processor.run_due_once())

    assert result["enabled"] is False
    assert result["processedBooks"] == 0
    assert result["dueBooks"] == 0
    assert "aiEnabled=false" in result["reason"]


def test_run_due_once_returns_disabled_when_auto_aggregate_false(tmp_path):
    db_path = _setup_db(tmp_path, auto_aggregate=False)
    processor = AggregateProcessor(db_path)

    result = asyncio.run(processor.run_due_once())

    assert result["enabled"] is False
    assert "autoAggregate=false" in result["reason"]


def test_run_due_once_returns_disabled_when_process_on_read_false(tmp_path):
    db_path = _setup_db(tmp_path, process_on_read=False)
    processor = AggregateProcessor(db_path)

    result = asyncio.run(processor.run_due_once())

    assert result["enabled"] is False
    assert "processAggregateOnRead=false" in result["reason"]


def test_run_due_once_returns_due_books_count(tmp_path):
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book:1")
    _insert_book(db_path, "book:2")
    processor = AggregateProcessor(db_path)

    result = asyncio.run(processor.run_due_once())

    assert result["enabled"] is True
    assert result["dueBooks"] == 2
    assert result["processedBooks"] == 2


# ── list_due_books ───────────────────────────────────────────────────────────


def test_list_due_books_finds_active_and_error(tmp_path):
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book:active", status="active")
    _insert_book(db_path, "book:error", status="error")
    processor = AggregateProcessor(db_path)

    due = processor.list_due_books()

    ids = {item["aggregateBookId"] for item in due}
    assert "book:active" in ids
    assert "book:error" in ids


def test_list_due_books_ignores_paused(tmp_path):
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book:active", status="active")
    _insert_book(db_path, "book:paused", status="paused")
    processor = AggregateProcessor(db_path)

    due = processor.list_due_books()

    ids = {item["aggregateBookId"] for item in due}
    assert "book:active" in ids
    assert "book:paused" not in ids


def test_list_due_books_ignores_future_check_time(tmp_path):
    db_path = _setup_db(tmp_path)
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    _insert_book(db_path, "book:future", status="active", next_check_time=future)
    _insert_book(db_path, "book:now", status="active")
    processor = AggregateProcessor(db_path)

    due = processor.list_due_books()

    ids = {item["aggregateBookId"] for item in due}
    assert "book:now" in ids
    assert "book:future" not in ids


# ── _chapters_for_processing ─────────────────────────────────────────────────


def test_chapters_for_processing_selects_pending(tmp_path):
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book:x")
    ch = _insert_chapter(db_path, "book:x", index=1, status="pending")
    processor = AggregateProcessor(db_path)

    chapters = processor._chapters_for_processing("book:x")

    assert len(chapters) == 1
    assert chapters[0]["chapterId"] == ch


def test_chapters_for_processing_skips_processed(tmp_path):
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book:x")
    _insert_chapter(db_path, "book:x", index=1, status="pending")
    _insert_chapter(db_path, "book:x", index=2, status="processed")
    _insert_chapter(db_path, "book:x", index=3, status="fallback")
    processor = AggregateProcessor(db_path)

    chapters = processor._chapters_for_processing("book:x")

    statuses = {c["status"] for c in chapters}
    assert "processed" not in statuses
    assert "fallback" not in statuses
    assert len(chapters) == 1


def test_chapters_for_processing_selects_retryable_error(tmp_path):
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book:x")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    _insert_chapter(
        db_path, "book:x", index=1, status="error",
        next_retry_time=past, last_error_code="SOURCE_TIMEOUT", retry_count=1,
    )
    processor = AggregateProcessor(db_path)

    chapters = processor._chapters_for_processing("book:x")

    assert len(chapters) == 1
    assert chapters[0]["status"] == "error"


def test_chapters_for_processing_skips_terminal_error(tmp_path):
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book:x")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    terminal_code = sorted(ERROR_CODES_NO_RETRY)[0] if ERROR_CODES_NO_RETRY else "AI_BAD_REQUEST"
    _insert_chapter(
        db_path, "book:x", index=1, status="error",
        next_retry_time=past, last_error_code=terminal_code, retry_count=0,
    )
    processor = AggregateProcessor(db_path)

    chapters = processor._chapters_for_processing("book:x")

    assert len(chapters) == 0


def test_chapters_for_processing_skips_exhausted_retry(tmp_path):
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book:x")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    _insert_chapter(
        db_path, "book:x", index=1, status="error",
        next_retry_time=past, last_error_code="SOURCE_TIMEOUT",
        retry_count=len(RETRY_DELAYS_MINUTES),
    )
    processor = AggregateProcessor(db_path)

    chapters = processor._chapters_for_processing("book:x")

    assert len(chapters) == 0


# ── run_forever logging ──────────────────────────────────────────────────────


def test_run_forever_logs_on_start_stop(tmp_path, caplog):
    db_path = _setup_db(tmp_path)
    processor = AggregateProcessor(db_path)
    stop_event = asyncio.Event()

    async def _run():
        stop_event.set()  # Will exit on first iteration.
        await processor.run_forever(stop_event, poll_seconds=1)

    with caplog.at_level(logging.INFO, logger="app.services.aggregate_processor"):
        asyncio.run(_run())

    messages = [r.message for r in caplog.records]
    assert any("Aggregate processor started" in m for m in messages)
    assert any("Aggregate processor stopped" in m for m in messages)


def test_run_forever_continues_after_run_due_once_exception(tmp_path, caplog):
    db_path = _setup_db(tmp_path)
    processor = AggregateProcessor(db_path)
    stop_event = asyncio.Event()
    call_count = 0

    original_run_due_once = processor.run_due_once

    async def _failing_run_due_once(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            stop_event.set()
        raise RuntimeError("simulated failure")

    processor.run_due_once = _failing_run_due_once

    async def _run():
        await processor.run_forever(stop_event, poll_seconds=0)

    with caplog.at_level(logging.INFO, logger="app.services.aggregate_processor"):
        asyncio.run(_run())

    assert call_count >= 2, "Loop should have continued after first exception"
    assert any("run_due_once failed" in r.message for r in caplog.records)
    assert any("Aggregate processor stopped" in r.message for r in caplog.records)


def test_run_forever_logs_processed_books(tmp_path, caplog):
    db_path = _setup_db(tmp_path)
    _insert_book(db_path, "book:1")
    processor = AggregateProcessor(db_path)
    stop_event = asyncio.Event()

    call_count = 0
    original = processor.run_due_once

    async def _instrumented(*args, **kwargs):
        nonlocal call_count
        result = await original(*args, **kwargs)
        call_count += 1
        if call_count >= 1:
            stop_event.set()
        return result

    processor.run_due_once = _instrumented

    async def _run():
        await processor.run_forever(stop_event, poll_seconds=0)

    with caplog.at_level(logging.INFO, logger="app.services.aggregate_processor"):
        asyncio.run(_run())

    messages = [r.message for r in caplog.records]
    assert any("processedBooks=" in m for m in messages)
