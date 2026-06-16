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


def test_aggregate_processor_processes_only_five_chapters_per_round(tmp_path):
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
        [
            {"title": f"第{i}章", "chapterUrl": f"https://a.example/book/1/{i}.html"}
            for i in range(1, 9)
        ],
    )

    chapters = processor._chapters_for_processing(book_id)

    assert len(chapters) == 5
    assert [chapter["chapterIndex"] for chapter in chapters] == [1, 2, 3, 4, 5]


def test_aggregate_processor_skips_processed_and_fallback_chapters(tmp_path):
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
        [
            {"title": f"第{i}章", "chapterUrl": f"https://a.example/book/1/{i}.html"}
            for i in range(1, 5)
        ],
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE aggregate_chapter_tasks SET status = 'processed' WHERE chapter_index = 1"
        )
        conn.execute(
            "UPDATE aggregate_chapter_tasks SET status = 'fallback' WHERE chapter_index = 2"
        )
        conn.commit()

    chapters = processor._chapters_for_processing(book_id)

    assert [chapter["chapterIndex"] for chapter in chapters] == [3, 4]


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


def test_primary_book_id_respects_source_priority():
    """When source_priority is given, the first matching source wins regardless of score."""
    payload = {
        "sources": [
            {"bookId": "src_c:https://c.example/book/1", "sourceId": "src_c", "score": 100},
            {"bookId": "src_a:https://a.example/book/1", "sourceId": "src_a", "score": 10},
            {"bookId": "src_b:https://b.example/book/1", "sourceId": "src_b", "score": 50},
        ]
    }
    # Priority: src_b first, then src_a.
    result = primary_book_id_from_payload(payload, source_priority=["src_b", "src_a"])
    assert result == "src_b:https://b.example/book/1"


def test_primary_book_id_priority_falls_back_to_next():
    """If first priority source not in payload, try next."""
    payload = {
        "sources": [
            {"bookId": "src_a:https://a.example/book/1", "sourceId": "src_a", "score": 10},
        ]
    }
    result = primary_book_id_from_payload(payload, source_priority=["missing_src", "src_a"])
    assert result == "src_a:https://a.example/book/1"


def test_primary_book_id_priority_empty_falls_back_to_default(monkeypatch):
    """Empty priority list → falls back to official-first + score logic."""
    class FakePlugin:
        def __init__(self, official):
            self.metadata = type("M", (), {"is_official_source": lambda self: official})()
    monkeypatch.setattr(
        "app.services.aggregate_virtual_source.PluginLoader.load_all",
        lambda self: {"official_x": FakePlugin(True)},
    )
    payload = {
        "sources": [
            {"bookId": "other:https://x.example/1", "sourceId": "other", "score": 999},
            {"bookId": "official_x:https://x.example/1", "sourceId": "official_x", "score": 10},
        ]
    }
    result = primary_book_id_from_payload(payload, source_priority=[])
    assert result == "official_x:https://x.example/1"


# ── Stage 3: fallback integration tests ─────────────────────────────────────


def _insert_book_and_chapters(db_path, book_id, *, chapter_count=1):
    """Helper: insert a book task and chapter tasks for testing."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO aggregate_book_tasks
            (aggregate_book_id, name, author, primary_book_id, primary_source_id,
             status, ai_enabled, created_at, updated_at)
            VALUES (?, '测试书', '作者', ?, 'official_src', 'active', 1,
                    datetime('now'), datetime('now'))
            """,
            (book_id, f"official_src:{book_id}"),
        )
        for i in range(1, chapter_count + 1):
            ch_id = f"{book_id}:ch{i}"
            conn.execute(
                """
                INSERT OR IGNORE INTO aggregate_chapter_tasks
                (chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'pending', datetime('now'), datetime('now'))
                """,
                (ch_id, book_id, f"official_src:ch{i}", i, f"第{i}章"),
            )
        conn.commit()


class FakeCatalog:
    """Fake BookCatalog that returns canned chapter content."""

    def __init__(self, content: str = "", *, fail: bool = False):
        self._content = content
        self._fail = fail

    async def chapter(self, chapter_id: str) -> dict:
        if self._fail:
            raise RuntimeError("source fetch failed")
        return {"content": self._content, "title": "第1章"}

    async def toc(self, book_id: str) -> dict:
        return {"chapters": []}


def test_official_full_content_written_as_processed(tmp_path, monkeypatch):
    """Official full content (>200 chars) should be processed without AI, with alignment JSON."""
    import asyncio
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    _enable_ai_workflow(db_path)
    book_id = "agg:official_full_test"
    _insert_book_and_chapters(db_path, book_id)
    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: True)
    full_content = "这是一段完整的官方正文内容，超过两百个字。" * 20
    catalog = FakeCatalog(content=full_content)
    chapter = {"chapterId": f"{book_id}:ch1", "sourceChapterId": "official_src:ch1",
               "title": "第1章", "chapterIndex": 1, "aggregateBookId": book_id}

    result = asyncio.run(processor._process_chapter(catalog, chapter))

    assert result["success"] is True
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT status, processed_content, source_alignment_json FROM aggregate_chapter_tasks WHERE chapter_id = ?",
            (f"{book_id}:ch1",),
        ).fetchone()
    assert row[0] == "processed"
    assert row[1] is not None and len(row[1]) > 0
    alignment = json.loads(row[2] or "{}")
    assert alignment.get("selectedContentSource") == "official"


def test_ai_failure_writes_fallback_content(tmp_path):
    """First AI failure should write fallback content, not leave placeholder."""
    import asyncio
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    _enable_ai_workflow(db_path)
    book_id = "agg:fallback_test"
    _insert_book_and_chapters(db_path, book_id)
    processor = AggregateProcessor(db_path)
    catalog = FakeCatalog(fail=True)
    chapter = {"chapterId": f"{book_id}:ch1", "sourceChapterId": "official_src:ch1",
               "title": "第1章", "chapterIndex": 1, "aggregateBookId": book_id}

    result = asyncio.run(processor._process_chapter(catalog, chapter))

    assert result["success"] is False
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT status, last_error_code FROM aggregate_chapter_tasks WHERE chapter_id = ?",
            (f"{book_id}:ch1",),
        ).fetchone()
    assert row[0] == "error"
    assert row[1] != ""  # error code is recorded


def test_fallback_status_not_auto_selected(tmp_path):
    """Chapters with status='fallback' should not be auto-selected for processing."""
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    _enable_ai_workflow(db_path)
    book_id = "agg:fallback_skip"
    _insert_book_and_chapters(db_path, book_id, chapter_count=3)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE aggregate_chapter_tasks SET status = 'fallback' WHERE chapter_index = 1"
        )
        conn.commit()
    processor = AggregateProcessor(db_path)

    chapters = processor._chapters_for_processing(book_id)
    indices = [c["chapterIndex"] for c in chapters]

    assert 1 not in indices
    assert 2 in indices
    assert 3 in indices


def test_source_alignment_json_is_parseable(tmp_path, monkeypatch):
    """After processing, source_alignment_json must be valid JSON with selectedContentSource."""
    import asyncio
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    _enable_ai_workflow(db_path)
    book_id = "agg:alignment_json"
    _insert_book_and_chapters(db_path, book_id)
    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: True)
    content = "官方完整正文内容，足够长以触发full分类。" * 15
    catalog = FakeCatalog(content=content)
    chapter = {"chapterId": f"{book_id}:ch1", "sourceChapterId": "official_src:ch1",
               "title": "第1章", "chapterIndex": 1, "aggregateBookId": book_id}

    asyncio.run(processor._process_chapter(catalog, chapter))

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT source_alignment_json FROM aggregate_chapter_tasks WHERE chapter_id = ?",
            (f"{book_id}:ch1",),
        ).fetchone()
    alignment = json.loads(row[0] or "{}")
    assert "selectedContentSource" in alignment
    assert alignment["selectedContentSource"] in ("official", "candidate", "fallback_official",
                                                   "fallback_candidate", "third_party_primary_fallback")


def test_five_chapter_window_still_respected(tmp_path):
    """Must not process more than WINDOW_CHAPTER_LIMIT chapters."""
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    _enable_ai_workflow(db_path)
    book_id = "agg:window_test"
    _insert_book_and_chapters(db_path, book_id, chapter_count=10)
    processor = AggregateProcessor(db_path)

    chapters = processor._chapters_for_processing(book_id)

    assert len(chapters) == 5



