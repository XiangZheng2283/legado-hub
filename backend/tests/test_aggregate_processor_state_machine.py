"""Tests for AggregateProcessor state machine: preview / third-party / fallback paths."""

import asyncio
import json
import sqlite3

import pytest

from app.services.aggregate_processor import AggregateProcessor
from app.services.aggregate_settings import PROCESSING_PLACEHOLDER
from app.storage.db import initialize_database


# ── helpers ──────────────────────────────────────────────────────────────────


def _setup_db(tmp_path, *, ai_enabled=True, purify="conservative"):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    if ai_enabled:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO admin_settings (key, value_json) VALUES (?, ?)",
                ("contentWorkflow", json.dumps({
                    "aiEnabled": True, "autoAggregate": True, "processAggregateOnRead": True,
                    "aggregateCheckIntervalMinutes": 10, "purifyMode": purify,
                }, ensure_ascii=False)),
            )
            conn.commit()
    return db_path


def _insert_book(db_path, book_id, *, primary_source_id="official_src",
                 aggregate_payload=None):
    payload = aggregate_payload or {
        "name": "测试书", "author": "作者",
        "sources": [
            {"bookId": f"official_src:{book_id}", "sourceId": "official_src",
             "score": 100, "bookUrl": f"https://official.example/book/{book_id}"},
            {"bookId": f"candidate_src:{book_id}", "sourceId": "candidate_src",
             "score": 80, "bookUrl": f"https://candidate.example/book/{book_id}"},
        ],
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO aggregate_book_tasks
               (aggregate_book_id, name, author, primary_book_id, primary_source_id,
                aggregate_payload_json, status, ai_enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'active', 1, datetime('now'), datetime('now'))""",
            (book_id, payload.get("name", ""), payload.get("author", ""),
             f"{primary_source_id}:{book_id}", primary_source_id,
             json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()


def _insert_chapter(db_path, book_id, index=1, *, status="pending"):
    ch_id = f"{book_id}:ch{index}"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO aggregate_chapter_tasks
               (chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title, status,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
            (ch_id, book_id, f"official_src:ch{index}", index, f"第{index}章", status),
        )
        conn.commit()
    return ch_id


class _FakeCatalog:
    """Returns different content depending on source_chapter_id prefix."""

    def __init__(self, *, official_content="", candidate_content="",
                 official_fail=False, candidate_fail=False):
        self._official = official_content
        self._candidate = candidate_content
        self._official_fail = official_fail
        self._candidate_fail = candidate_fail

    async def chapter(self, chapter_id: str) -> dict:
        if chapter_id.startswith("official_src"):
            if self._official_fail:
                raise RuntimeError("official source failed")
            return {"content": self._official, "title": "第1章"}
        if chapter_id.startswith("candidate_src"):
            if self._candidate_fail:
                raise RuntimeError("candidate source failed")
            return {"content": self._candidate, "title": "第1章"}
        # Fallback: try official
        if self._official_fail:
            raise RuntimeError("source fetch failed")
        return {"content": self._official, "title": "第1章"}

    async def toc(self, book_id: str) -> dict:
        """Return a fake TOC with one chapter per book."""
        source_id = book_id.split(":")[0] if ":" in book_id else book_id
        from app.source_plugins.id_codec import encode_chapter_id as enc
        ch_url = f"https://{source_id}.example/ch1.html"
        return {"chapters": [
            {"chapterId": enc(source_id, ch_url), "title": "第1章",
             "chapterUrl": ch_url, "index": 1}
        ]}


class _FakeAIService:
    """Records calls and returns canned results."""

    def __init__(self, *, content="AI 聚合正文", fail=False, error=None, self_score=1.0):
        self._content = content
        self._fail = fail
        self._error = error
        self._self_score = self_score
        self.calls: list[dict] = []

    async def process_official_full(self, **kwargs):
        self.calls.append({"method": "official_full", **kwargs})
        return {"status": "processed", "content": kwargs.get("content", self._content),
                "aiModel": "", "promptTokens": 0, "completionTokens": 0,
                "totalTokens": 0, "latencyMs": 0, "plannedAnalysis": True}

    async def process_with_candidates(self, **kwargs):
        self.calls.append({"method": "with_candidates", **kwargs})
        if self._fail:
            raise self._error or RuntimeError("AI aggregation failed")
        return {"status": "processed", "content": self._content,
                "selfScore": self._self_score,
                "aiModel": "fake-model", "promptTokens": 100, "completionTokens": 50,
                "totalTokens": 150, "latencyMs": 200, "plannedAnalysis": False}

    async def process_third_party_primary(self, **kwargs):
        self.calls.append({"method": "third_party_primary", **kwargs})
        if self._fail:
            return {"status": "fallback", "content": kwargs.get("content", ""),
                    "selfScore": 0.0,
                    "aiModel": "", "error": str(self._error or "AI failed"),
                    "promptTokens": 0, "completionTokens": 0,
                    "totalTokens": 0, "latencyMs": 0, "plannedAnalysis": False}
        return {"status": "processed", "content": self._content,
                "selfScore": self._self_score,
                "aiModel": "fake-model", "promptTokens": 100, "completionTokens": 50,
                "totalTokens": 150, "latencyMs": 200, "plannedAnalysis": False}


def _chapter_dict(ch_id, book_id, index=1):
    return {"chapterId": ch_id, "sourceChapterId": f"official_src:ch{index}",
            "title": f"第{index}章", "chapterIndex": index, "aggregateBookId": book_id}


def _get_chapter_row(db_path, ch_id):
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT status, processed_content, source_alignment_json, fallback_source_id "
            "FROM aggregate_chapter_tasks WHERE chapter_id = ?", (ch_id,),
        ).fetchone()
    if not row:
        return None
    alignment = {}
    try:
        alignment = json.loads(row[2] or "{}")
    except Exception:
        pass
    return {"status": row[0], "content": row[1] or "", "alignment": alignment,
            "fallbackSourceId": row[3] or ""}


# ── Test A: preview must NOT be marked processed ─────────────────────────────


def test_preview_content_is_not_marked_processed_without_candidate(tmp_path):
    """VIP preview (~30 chars) without aligned candidate → must NOT be 'processed'."""
    db_path = _setup_db(tmp_path)
    book_id = "book:preview_no_cand"
    _insert_book(db_path, book_id)
    ch_id = _insert_chapter(db_path, book_id)

    preview = "少年站在山巅望着远方，他知道这一切才刚刚开始。"  # < 200 chars
    catalog = _FakeCatalog(official_content=preview)
    # No AI service needed — preview without candidate should not reach AI.
    processor = AggregateProcessor(db_path)

    result = asyncio.run(processor._process_chapter(catalog, _chapter_dict(ch_id, book_id)))

    row = _get_chapter_row(db_path, ch_id)
    assert row["status"] != "processed", \
        f"Preview content must NOT be 'processed', got '{row['status']}'"
    assert row["alignment"]["selectedContentSource"] != "official", \
        "Preview-only must not claim selectedContentSource='official'"


# ── Test B: fallback chapter response returns content ────────────────────────


def test_fallback_chapter_response_returns_fallback_content(tmp_path):
    """A chapter with status='fallback' and processed_content must return that content."""
    from app.services.aggregate_virtual_source import (
        make_aggregate_chapter_url, VIRTUAL_SOURCE_ID,
    )
    from app.source_plugins.id_codec import encode_chapter_id

    db_path = _setup_db(tmp_path)
    book_id = "book:fallback_resp"
    _insert_book(db_path, book_id)
    ch_id = _insert_chapter(db_path, book_id)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE aggregate_chapter_tasks SET status='fallback', "
            "processed_content=? WHERE chapter_id=?",
            ("这是 fallback 正文内容", ch_id),
        )
        conn.commit()

    chapter_url = make_aggregate_chapter_url(book_id, f"official_src:ch1", title="第1章", index=1)
    processor = AggregateProcessor(db_path)
    resp = processor.aggregate_chapter_response(chapter_url, chapter_id=ch_id)

    assert resp["content"] == "这是 fallback 正文内容"
    assert resp["debug"]["status"] == "fallback"


# ── Test C: third-party primary not marked as official ───────────────────────


def test_third_party_primary_not_marked_as_official(tmp_path):
    """When primary_source_id is NOT an official source, selectedContentSource ≠ 'official'."""
    db_path = _setup_db(tmp_path)
    book_id = "book:tp_primary"
    _insert_book(db_path, book_id, primary_source_id="candidate_src")
    ch_id = _insert_chapter(db_path, book_id)

    full_content = "这是一段第三方源的完整正文，超过两百个字的阈值。" * 15
    catalog = _FakeCatalog(official_content=full_content)
    ai_service = _FakeAIService(content="AI 整理后的第三方正文")
    processor = AggregateProcessor(db_path, ai_service=ai_service)

    result = asyncio.run(processor._process_chapter(catalog, _chapter_dict(ch_id, book_id)))

    row = _get_chapter_row(db_path, ch_id)
    assert row["alignment"]["selectedContentSource"] != "official", \
        "Third-party primary must NOT get selectedContentSource='official'"
    assert "official" not in row["alignment"]["selectedContentSource"] or \
           "third_party" in row["alignment"]["selectedContentSource"]


# ── Test D: preview + aligned candidate calls AI service ─────────────────────


def test_preview_with_aligned_candidate_calls_ai_service(tmp_path):
    """Official preview + aligned candidate → AI service called → processed."""
    db_path = _setup_db(tmp_path)
    book_id = "book:preview_ai"
    _insert_book(db_path, book_id)
    ch_id = _insert_chapter(db_path, book_id)

    preview = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始，未来路还很长。"
    # Candidate content contains the preview text + extended content.
    candidate = ("【小说网】少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。"
                 "他知道这一切才刚刚开始，未来路还很长。后续正文内容扩充了很多。" * 10)

    catalog = _FakeCatalog(official_content=preview, candidate_content=candidate)
    # AI output must be similar to candidate to pass deviation check.
    ai_output = ("少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。"
                 "他知道这一切才刚刚开始，未来路还很长。后续正文内容扩充了很多。" * 10)
    ai_service = _FakeAIService(content=ai_output)
    processor = AggregateProcessor(db_path, ai_service=ai_service)

    result = asyncio.run(processor._process_chapter(catalog, _chapter_dict(ch_id, book_id)))

    row = _get_chapter_row(db_path, ch_id)
    assert row["status"] == "processed"
    assert row["content"] == ai_output
    assert len(ai_service.calls) == 1
    assert ai_service.calls[0]["method"] == "with_candidates"
    assert row["alignment"]["selectedContentSource"] in ("candidate", "ai_aggregate_candidate")


# ── Test E: preview + aligned candidate + AI failure → candidate fallback ────


def test_preview_with_aligned_candidate_ai_failure_writes_candidate_fallback(tmp_path):
    """AI failure after alignment → fallback to candidate content, not placeholder."""
    db_path = _setup_db(tmp_path)
    book_id = "book:ai_fail_fallback"
    _insert_book(db_path, book_id)
    ch_id = _insert_chapter(db_path, book_id)

    preview = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始，未来路还很长。"
    candidate = ("【小说网】少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。"
                 "他知道这一切才刚刚开始，未来路还很长。后续正文内容扩充了很多。" * 10)

    catalog = _FakeCatalog(official_content=preview, candidate_content=candidate)
    ai_service = _FakeAIService(fail=True, error=RuntimeError("AI provider failed"))
    processor = AggregateProcessor(db_path, ai_service=ai_service)

    result = asyncio.run(processor._process_chapter(catalog, _chapter_dict(ch_id, book_id)))

    row = _get_chapter_row(db_path, ch_id)
    assert row["status"] == "fallback", f"Expected 'fallback', got '{row['status']}'"
    assert row["content"] != PROCESSING_PLACEHOLDER, "Must not be placeholder"
    assert len(row["content"]) > len(preview), "Fallback should be candidate content, not preview"
    assert row["fallbackSourceId"] != "", "fallback_source_id must be set"


# ── _is_official_source ─────────────────────────────────────────────────────


def test_is_official_source_returns_false_for_unknown(tmp_path, monkeypatch):
    """Unknown source_id → not official."""
    db_path = _setup_db(tmp_path)
    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(
        "app.source_plugins.loader.PluginLoader.load_all",
        lambda self: {},
    )
    assert processor._is_official_source("nonexistent_src") is False


def test_is_official_source_returns_true_for_official(tmp_path, monkeypatch):
    """Source marked as official → True."""
    db_path = _setup_db(tmp_path)
    processor = AggregateProcessor(db_path)

    class FakePlugin:
        def __init__(self, official: bool):
            self.metadata = type("M", (), {"is_official_source": lambda self: official})()

    monkeypatch.setattr(
        "app.source_plugins.loader.PluginLoader.load_all",
        lambda self: {"qidian_com": FakePlugin(True), "example_com": FakePlugin(False)},
    )
    assert processor._is_official_source("qidian_com") is True
    assert processor._is_official_source("example_com") is False


# ── TOC cache ────────────────────────────────────────────────────────────────


def test_toc_cache_avoids_repeated_calls(tmp_path):
    """_cached_toc should return cached result on second call without hitting catalog."""
    db_path = _setup_db(tmp_path)
    processor = AggregateProcessor(db_path)

    call_count = 0
    class CountingCatalog:
        async def toc(self, book_id):
            nonlocal call_count
            call_count += 1
            return {"chapters": [{"chapterId": "x:1", "title": "ch1", "index": 1}]}

    catalog = CountingCatalog()
    asyncio.run(processor._cached_toc(catalog, "book_a"))
    asyncio.run(processor._cached_toc(catalog, "book_a"))
    asyncio.run(processor._cached_toc(catalog, "book_b"))

    assert call_count == 2  # book_a once, book_b once


def test_toc_cache_cleared_between_books(tmp_path):
    """_clear_toc_cache should empty the cache."""
    db_path = _setup_db(tmp_path)
    processor = AggregateProcessor(db_path)
    processor._toc_cache["x"] = {"chapters": []}
    processor._clear_toc_cache()
    assert len(processor._toc_cache) == 0


# ── previous chapter context ─────────────────────────────────────────────────


def test_load_previous_chapters_context(tmp_path):
    """_load_previous_chapters_context returns excerpts of earlier processed chapters."""
    db_path = _setup_db(tmp_path)
    book_id = "book:prev_ctx"
    _insert_book(db_path, book_id)
    for i in range(1, 5):
        ch_id = _insert_chapter(db_path, book_id, index=i)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE aggregate_chapter_tasks SET status='processed', "
                "processed_content=? WHERE chapter_id=?",
                (f"第{i}章的正文内容，" * 50, ch_id),
            )
            conn.commit()

    processor = AggregateProcessor(db_path)
    ctx = processor._load_previous_chapters_context(book_id, before_index=4, count=2)

    # Should contain chapters 2 and 3 (the 2 before index 4).
    assert "第2章" in ctx or "第3章" in ctx
    assert len(ctx) > 0


def test_load_previous_chapters_context_empty_when_none(tmp_path):
    """No previous chapters → empty string."""
    db_path = _setup_db(tmp_path)
    book_id = "book:no_prev"
    _insert_book(db_path, book_id)
    _insert_chapter(db_path, book_id, index=1)

    processor = AggregateProcessor(db_path)
    ctx = processor._load_previous_chapters_context(book_id, before_index=1)
    assert ctx == ""


def test_previous_context_passed_to_ai_service(tmp_path):
    """When previous chapters exist, previous_context should be passed to AI service."""
    db_path = _setup_db(tmp_path)
    book_id = "book:ctx_pass"
    _insert_book(db_path, book_id)
    # Insert a processed chapter 1.
    ch1 = _insert_chapter(db_path, book_id, index=1)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE aggregate_chapter_tasks SET status='processed', "
            "processed_content=? WHERE chapter_id=?",
            ("第一章已处理的正文内容，" * 30, ch1),
        )
        conn.commit()
    # Insert chapter 2 as pending.
    ch2 = _insert_chapter(db_path, book_id, index=2)

    preview = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始，未来路还很长。"
    from app.source_plugins.id_codec import encode_chapter_id as enc
    candidate_ch2_id = enc("candidate_src", "https://candidate.example/ch2.html")
    candidate = ("【小说网】少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。"
                 "他知道这一切才刚刚开始，未来路还很长。后续正文内容扩充了很多。" * 10)

    class TwoChapterCatalog(_FakeCatalog):
        async def toc(self, book_id):
            return {"chapters": [
                {"chapterId": enc("candidate_src", "https://candidate.example/ch1.html"), "title": "第1章", "index": 1},
                {"chapterId": candidate_ch2_id, "title": "第2章", "index": 2},
            ]}
        async def chapter(self, chapter_id):
            if chapter_id == candidate_ch2_id:
                return {"content": candidate, "title": "第2章"}
            return await super().chapter(chapter_id)

    catalog = TwoChapterCatalog(official_content=preview, candidate_content=candidate)
    ai_service = _FakeAIService(content="AI 聚合正文")
    processor = AggregateProcessor(db_path, ai_service=ai_service)

    asyncio.run(processor._process_chapter(catalog, _chapter_dict(ch2, book_id, index=2)))

    assert len(ai_service.calls) == 1
    call = ai_service.calls[0]
    assert "previous_context" in call
    assert len(call["previous_context"]) > 0


# ── deviation score integration ──────────────────────────────────────────────


def test_high_deviation_reverts_to_fallback(tmp_path):
    """AI output that deviates too much from candidate → fallback instead of processed."""
    db_path = _setup_db(tmp_path)
    book_id = "book:deviation"
    _insert_book(db_path, book_id)
    ch_id = _insert_chapter(db_path, book_id)

    preview = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始，未来路还很长。"
    candidate = ("【小说网】少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。"
                 "他知道这一切才刚刚开始，未来路还很长。后续正文内容扩充了很多。" * 10)
    # AI returns completely different content → deviation < threshold.
    catalog = _FakeCatalog(official_content=preview, candidate_content=candidate)
    ai_service = _FakeAIService(content="这是一段和原文完全无关的输出内容，偏离度极高。" * 10)
    processor = AggregateProcessor(db_path, ai_service=ai_service)

    asyncio.run(processor._process_chapter(catalog, _chapter_dict(ch_id, book_id)))

    row = _get_chapter_row(db_path, ch_id)
    assert row["status"] == "fallback", \
        f"High deviation should be fallback, got '{row['status']}'"
    assert row["content"] != "这是一段和原文完全无关的输出内容", \
        "Fallback should be candidate content, not the bad AI output"


def test_low_deviation_keeps_processed(tmp_path):
    """AI output within threshold → processed with deviation_score written."""
    db_path = _setup_db(tmp_path)
    book_id = "book:dev_ok"
    _insert_book(db_path, book_id)
    ch_id = _insert_chapter(db_path, book_id)

    preview = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始，未来路还很长。"
    # AI returns content very similar to candidate → high deviation score (close to 1.0).
    candidate = ("【小说网】少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。"
                 "他知道这一切才刚刚开始，未来路还很长。后续正文内容扩充了很多。" * 10)
    ai_output = ("少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。"
                 "他知道这一切才刚刚开始，未来路还很长。后续正文内容扩充了很多。" * 10)

    catalog = _FakeCatalog(official_content=preview, candidate_content=candidate)
    ai_service = _FakeAIService(content=ai_output)
    processor = AggregateProcessor(db_path, ai_service=ai_service)

    asyncio.run(processor._process_chapter(catalog, _chapter_dict(ch_id, book_id)))

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT status, deviation_score, ai_model FROM aggregate_chapter_tasks WHERE chapter_id=?",
            (ch_id,),
        ).fetchone()
    assert row[0] == "processed"
    assert row[1] > 0.0  # deviation_score is written
    assert row[2] == "fake-model"


def test_ai_output_deviation_error_code():
    from app.ai.client import AIProviderHTTPError
    from app.services.aggregate_processor import classify_error
    # The ValueError with "AI_OUTPUT_DEVIATION" message.
    assert classify_error(ValueError("AI_OUTPUT_DEVIATION: score 0.3 < threshold 0.9")) == "AI_OUTPUT_DEVIATION"
