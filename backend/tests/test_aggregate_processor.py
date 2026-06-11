"""Tests for aggregate virtual-source processing tasks."""

import json
import sqlite3

from app.services.aggregate_processor import AggregateProcessor
from app.services.aggregate_processor import PROCESSING_PLACEHOLDER
from app.services.aggregate_virtual_source import (
    VIRTUAL_SOURCE_ID,
    make_aggregate_book_url,
    make_aggregate_chapter_url,
    primary_book_id_from_payload,
    unpack_aggregate_book_url,
)
from app.source_plugins.id_codec import encode_book_id, encode_chapter_id
from app.storage.db import initialize_database


def _enable_ai_workflow(db_path):
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
                        "returnOnlyAggregateSource": False,
                        "purifyMode": "conservative",
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        conn.commit()


def _group():
    return {
        "candidateId": "candidate-1",
        "name": "聚合样例",
        "author": "作者甲",
        "items": [
            {
                "sourceId": "source_a",
                "sourceName": "Source A",
                "name": "聚合样例",
                "author": "作者甲",
                "bookUrl": "https://a.example/book/1",
                "score": 10,
            }
        ],
    }


def test_aggregate_processor_does_not_enqueue_when_ai_disabled(tmp_path):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    group = _group()
    book_id = encode_book_id(VIRTUAL_SOURCE_ID, make_aggregate_book_url(group))
    payload = unpack_aggregate_book_url(make_aggregate_book_url(group))

    result = AggregateProcessor(db_path).enqueue_book(book_id, payload)

    assert result["queued"] is False
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM aggregate_book_tasks").fetchone()[0]
    assert count == 0


def test_aggregate_processor_enqueues_book_and_registers_chapters(tmp_path):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    _enable_ai_workflow(db_path)
    group = _group()
    book_id = encode_book_id(VIRTUAL_SOURCE_ID, make_aggregate_book_url(group))
    payload = unpack_aggregate_book_url(make_aggregate_book_url(group))
    processor = AggregateProcessor(db_path)

    queued = processor.enqueue_book(book_id, payload)
    registered = processor.register_toc(
        book_id,
        payload,
        [
            {"title": "第一章", "chapterUrl": "https://a.example/book/1/1.html"},
            {"title": "第二章", "chapterUrl": "https://a.example/book/1/2.html"},
        ],
    )

    assert queued["queued"] is True
    assert queued["intervalMinutes"] == 10
    assert registered["registered"] is True
    assert registered["chapterCount"] == 2
    with sqlite3.connect(db_path) as conn:
        task = conn.execute(
            "SELECT status, primary_book_id, interval_minutes FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
            (book_id,),
        ).fetchone()
        chapter_count = conn.execute(
            "SELECT COUNT(*) FROM aggregate_chapter_tasks WHERE aggregate_book_id = ?",
            (book_id,),
        ).fetchone()[0]

    assert task[0] == "active"
    assert task[1].startswith("source_a:")
    assert task[2] == 10
    assert chapter_count == 2


def test_aggregate_chapter_returns_placeholder_until_processed(tmp_path):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    _enable_ai_workflow(db_path)
    group = _group()
    book_id = encode_book_id(VIRTUAL_SOURCE_ID, make_aggregate_book_url(group))
    payload = unpack_aggregate_book_url(make_aggregate_book_url(group))
    processor = AggregateProcessor(db_path)
    processor.enqueue_book(book_id, payload)
    processor.register_toc(
        book_id,
        payload,
        [{"title": "第一章", "chapterUrl": "https://a.example/book/1/1.html"}],
    )
    source_chapter_id = encode_chapter_id("source_a", "https://a.example/book/1/1.html")
    aggregate_chapter_url = make_aggregate_chapter_url(book_id, source_chapter_id, title="第一章", index=1)
    aggregate_chapter_id = encode_chapter_id(VIRTUAL_SOURCE_ID, aggregate_chapter_url)

    pending = processor.aggregate_chapter_response(aggregate_chapter_url, chapter_id=aggregate_chapter_id)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE aggregate_chapter_tasks
            SET status = 'processed', processed_content = ?, content_length = ?
            WHERE chapter_id = ?
            """,
            ("净化后的正文", len("净化后的正文"), aggregate_chapter_id),
        )
        conn.commit()
    processed = processor.aggregate_chapter_response(aggregate_chapter_url, chapter_id=aggregate_chapter_id)

    assert pending["content"] == PROCESSING_PLACEHOLDER
    assert pending["debug"]["status"] == "pending"
    assert processed["content"] == "净化后的正文"
    assert processed["debug"]["status"] == "processed"
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT response_json FROM chapter_cache WHERE chapter_id = ?",
            (aggregate_chapter_id,),
        ).fetchone()
    assert row is None


def test_primary_book_id_from_payload_prefers_official_source(monkeypatch):
    class FakePlugin:
        def __init__(self, official: bool):
            self.metadata = type("M", (), {"is_official_source": lambda self: official})()

    monkeypatch.setattr(
        "app.services.aggregate_virtual_source.PluginLoader.load_all",
        lambda self: {
            "official_a": FakePlugin(True),
            "normal_b": FakePlugin(False),
        },
    )

    payload = {
        "sources": [
            {"bookId": "normal_b:https://b.example/book/1", "sourceId": "normal_b", "score": 999},
            {"bookId": "official_a:https://a.example/book/1", "sourceId": "official_a", "score": 10},
        ]
    }

    assert primary_book_id_from_payload(payload) == "official_a:https://a.example/book/1"






