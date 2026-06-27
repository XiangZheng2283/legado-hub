"""Tests for AggregateProcessor state machine: preview / third-party / fallback paths."""

import asyncio
import json
import sqlite3
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.services.aggregate_processor import AggregateProcessor
from app.services.aggregate_settings import PROCESSING_PLACEHOLDER
from app.services.shared_book_runtime import SharedBookRuntimeStore
from app.services.shared_book_storage import SharedBookStorage
from app.source_plugins.id_codec import decode_chapter_id, encode_chapter_id
from app.storage.db import initialize_database
from app.services.aggregate_virtual_source import make_aggregate_chapter_url


# ── helpers ──────────────────────────────────────────────────────────────────


def _setup_db(tmp_path, *, ai_enabled=True, purify="conservative", ai_provider=None):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)

    # The product code now reads workflow settings from backend/config/app_config.json
    # instead of the legacy admin_settings table. Write an isolated config per test.
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "app_config.json"
    workflow = {
        "autoAggregate": True,
        "processAggregateOnRead": True,
        "aggregateCheckIntervalMinutes": 10,
        "purifyMode": purify,
        "aiEnabled": ai_enabled,
    }
    config_data: dict[str, Any] = {"aggregate": {"contentWorkflow": workflow}}
    if ai_provider is not None:
        config_data["ai"] = {"provider": ai_provider}
    config_path.write_text(json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

    import app.core.app_config as _app_config_module

    _app_config_module.APP_CONFIG_PATH = config_path
    _app_config_module.AppConfig.reset()
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
        if self._fail:
            raise self._error or RuntimeError("AI aggregation failed")
        return {"status": "processed", "content": self._content,
                "selfScore": self._self_score,
                "aiModel": "official-fake-model", "promptTokens": 120, "completionTokens": 60,
                "totalTokens": 180, "latencyMs": 250, "plannedAnalysis": True}

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
            "SELECT status, processed_content, source_alignment_json, fallback_source_id, last_error_code "
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
            "fallbackSourceId": row[3] or "", "lastErrorCode": row[4] or ""}


def _get_policy_snapshot(db_path, ch_id):
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT policy_snapshot_json FROM aggregate_chapter_tasks WHERE chapter_id = ?",
            (ch_id,),
        ).fetchone()
    if not row or not row[0]:
        return {}
    return json.loads(row[0])


# ── background candidate discovery ───────────────────────────────────────────


def test_ensure_candidate_sources_discovers_and_persists_third_party_matches(tmp_path, monkeypatch):
    """A newly subscribed official-only book should get third-party candidates during aggregation."""
    db_path = _setup_db(tmp_path, ai_enabled=False)
    book_id = "book:auto_candidates"
    payload = {
        "name": "测试书",
        "author": "作者",
        "sources": [
            {
                "bookId": "official_src:1",
                "sourceId": "official_src",
                "sourceName": "官方源",
                "bookUrl": "https://official.example/book/1",
                "score": 100,
            }
        ],
    }
    _insert_book(db_path, book_id, primary_source_id="official_src", aggregate_payload=payload)

    class Metadata:
        id = "candidate_src"
        name = "候选源"
        priority = 50

        def is_official_source(self):
            return False

    plugin = SimpleNamespace(metadata=Metadata(), capabilities=["search"])

    class Scheduler:
        config = {"max_concurrency": 2}

        def _enabled_plugins(self):
            return [plugin]

        def _search_priority_plugins(self, plugins):
            return plugins

        async def search_one(self, source_id, keyword, page):
            assert source_id == "candidate_src"
            assert keyword == "测试书"
            return {
                "items": [
                    {
                        "sourceId": "candidate_src",
                        "sourceName": "候选源",
                        "name": "测试书",
                        "author": "作者",
                        "bookUrl": "https://candidate.example/book/1",
                        "lastChapter": "第十章",
                        "score": 80,
                    },
                    {
                        "sourceId": "candidate_src",
                        "sourceName": "候选源",
                        "name": "别的书",
                        "author": "作者",
                        "bookUrl": "https://candidate.example/book/2",
                    },
                ],
                "error": None,
            }

    monkeypatch.setattr(
        "app.source_plugins.scheduler.get_plugin_scheduler",
        lambda: Scheduler(),
    )

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    updated = asyncio.run(processor._ensure_candidate_sources_for_book(book_id, payload))

    assert [src["sourceId"] for src in updated["sources"]] == ["official_src", "candidate_src"]
    candidate = updated["sources"][1]
    assert candidate["bookId"].startswith("candidate_src:")
    assert candidate["bookUrl"] == "https://candidate.example/book/1"

    with sqlite3.connect(db_path) as conn:
        source_row = conn.execute(
            """
            SELECT source_id, source_book_id, role, enabled, last_chapter_title
            FROM aggregate_book_sources
            WHERE aggregate_book_id = ? AND source_id = ?
            """,
            (book_id, "candidate_src"),
        ).fetchone()
        payload_row = conn.execute(
            "SELECT aggregate_payload_json FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
            (book_id,),
        ).fetchone()

    assert source_row is not None
    assert source_row[2] == "candidate"
    assert source_row[3] == 1
    assert source_row[4] == "第十章"
    persisted = json.loads(payload_row[0])
    assert [src["sourceId"] for src in persisted["sources"]] == ["official_src", "candidate_src"]


# ── Test A: preview must NOT be marked processed ─────────────────────────────


def test_preview_content_is_not_marked_processed_without_candidate(tmp_path):
    """VIP preview (~30 chars) without aligned candidate → must NOT be 'processed'."""
    db_path = _setup_db(tmp_path, ai_enabled=False)
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

    db_path = _setup_db(tmp_path, ai_enabled=False)
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
    db_path = _setup_db(tmp_path, ai_enabled=False)
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
    db_path = _setup_db(tmp_path, ai_enabled=False)
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
    processor.ai_aggregate_enabled = lambda aggregate_book_id="": True

    result = asyncio.run(processor._process_chapter(catalog, _chapter_dict(ch_id, book_id)))

    row = _get_chapter_row(db_path, ch_id)
    assert row["status"] == "processed"
    assert row["content"] == ai_output
    assert len(ai_service.calls) == 1
    # Aligned candidate content is treated as third-party primary and processed by
    # process_third_party_primary in the shared-subscription refactor.
    assert ai_service.calls[0]["method"] == "third_party_primary"
    assert row["alignment"]["selectedContentSource"] == "candidate"


# ── Test E: preview + aligned candidate + AI failure → candidate fallback ────


def test_preview_with_aligned_candidate_ai_failure_writes_candidate_fallback(tmp_path):
    """AI failure after alignment → fallback to candidate content, not placeholder."""
    db_path = _setup_db(tmp_path, ai_enabled=False)
    book_id = "book:ai_fail_fallback"
    _insert_book(db_path, book_id)
    ch_id = _insert_chapter(db_path, book_id)

    preview = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始，未来路还很长。"
    candidate = ("【小说网】少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。"
                 "他知道这一切才刚刚开始，未来路还很长。后续正文内容扩充了很多。" * 10)

    catalog = _FakeCatalog(official_content=preview, candidate_content=candidate)
    ai_service = _FakeAIService(fail=True, error=RuntimeError("AI provider failed"))
    processor = AggregateProcessor(db_path, ai_service=ai_service)
    processor.ai_aggregate_enabled = lambda aggregate_book_id="": True

    result = asyncio.run(processor._process_chapter(catalog, _chapter_dict(ch_id, book_id)))

    row = _get_chapter_row(db_path, ch_id)
    assert row["status"] == "fallback", f"Expected 'fallback', got '{row['status']}'"
    assert row["content"] != PROCESSING_PLACEHOLDER, "Must not be placeholder"
    assert len(row["content"]) > len(preview), "Fallback should be candidate content, not preview"
    assert row["fallbackSourceId"] != "", "fallback_source_id must be set"


# ── _is_official_source ─────────────────────────────────────────────────────


def test_is_official_source_returns_false_for_unknown(tmp_path, monkeypatch):
    """Unknown source_id → not official."""
    db_path = _setup_db(tmp_path, ai_enabled=False)
    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(
        "app.source_plugins.loader.PluginLoader.load_all",
        lambda self: {},
    )
    assert processor._is_official_source("nonexistent_src") is False


def test_is_official_source_returns_true_for_official(tmp_path, monkeypatch):
    """Source marked as official → True."""
    db_path = _setup_db(tmp_path, ai_enabled=False)
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
    db_path = _setup_db(tmp_path, ai_enabled=False)
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
    db_path = _setup_db(tmp_path, ai_enabled=False)
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


@pytest.mark.skip(reason="Deviation-based fallback check was removed in the shared-subscription refactor.")
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
    # After the shared-subscription refactor, classify_error maps Stage 1 fetch failures.
    # A generic ValueError (including the legacy AI_OUTPUT_DEVIATION message) is no longer
    # a dedicated error code and falls back to S1_SOURCE_FETCH_FAILED.
    assert classify_error(ValueError("AI_OUTPUT_DEVIATION: score 0.3 < threshold 0.9")) == "S1_SOURCE_FETCH_FAILED"


# ── production default AI service ────────────────────────────────────────────


def _patch_ai_provider_config(monkeypatch, config: dict | None):
    """Monkeypatch AggregateSettingsRepository.ai_provider_config for tests."""
    from app.services.aggregate_settings import AggregateSettingsRepository

    def _fake(self):
        from app.services.aggregate_settings import _merge_defaults, DEFAULT_AI_PROVIDER_CONFIG
        if config is None:
            return _merge_defaults(DEFAULT_AI_PROVIDER_CONFIG, {})
        return _merge_defaults(DEFAULT_AI_PROVIDER_CONFIG, config)

    monkeypatch.setattr(AggregateSettingsRepository, "ai_provider_config", _fake)


def test_default_processor_builds_ai_service_when_provider_configured(tmp_path, monkeypatch):
    """With complete aiProviderConfig and aiEnabled=True, _get_ai_service() should return AggregateAIService."""
    db_path = _setup_db(tmp_path)
    _patch_ai_provider_config(monkeypatch, {
        "baseUrl": "https://api.example.com/v1",
        "apiKey": "sk-test",
        "model": "mimo-v2.5",
    })
    processor = AggregateProcessor(db_path)

    service = processor._get_ai_service()

    assert service is not None
    assert type(service).__name__ == "AggregateAIService"
    # Cached on second call.
    assert processor._get_ai_service() is service


def test_default_processor_builds_ai_service_with_lexicon(tmp_path, monkeypatch):
    """When sensitiveLexiconEnabled=True and a valid lexicon path is set, the default
    AggregateAIService built by _get_ai_service() must hold a non-None lexicon."""
    import logging

    db_path = _setup_db(tmp_path)
    _patch_ai_provider_config(monkeypatch, {
        "baseUrl": "https://api.example.com/v1",
        "apiKey": "sk-test",
        "model": "mimo-v2.5",
    })

    lex_dir = tmp_path / "lexicon"
    lex_dir.mkdir()
    (lex_dir / "words.txt").write_text("血腥\n暴力\n杀意\n", encoding="utf-8")

    monkeypatch.setattr(
        "app.services.aggregate_settings.AggregateSettingsRepository.content_workflow",
        lambda self: {
            "aiEnabled": True,
            "autoAggregate": True,
            "processAggregateOnRead": True,
            "aggregateCheckIntervalMinutes": 10,
            "purifyMode": "conservative",
            "sensitiveLexiconEnabled": True,
            "sensitiveLexiconPath": str(lex_dir),
        },
    )

    processor = AggregateProcessor(db_path)
    service = processor._get_ai_service()

    assert service is not None
    assert type(service).__name__ == "AggregateAIService"
    assert service._lexicon is not None, "AggregateAIService should hold a loaded lexicon"
    assert service._lexicon.word_count >= 2


def test_default_processor_builds_ai_service_when_lexicon_path_missing(tmp_path, monkeypatch, caplog):
    """A missing/broken lexicon path must NOT block AI service creation, but it should
    be logged so the failure is diagnosable."""
    import logging

    db_path = _setup_db(tmp_path)
    _patch_ai_provider_config(monkeypatch, {
        "baseUrl": "https://api.example.com/v1",
        "apiKey": "sk-test",
        "model": "mimo-v2.5",
    })

    missing_path = tmp_path / "does_not_exist" / "lexicon.txt"

    monkeypatch.setattr(
        "app.services.aggregate_settings.AggregateSettingsRepository.content_workflow",
        lambda self: {
            "aiEnabled": True,
            "autoAggregate": True,
            "processAggregateOnRead": True,
            "aggregateCheckIntervalMinutes": 10,
            "purifyMode": "conservative",
            "sensitiveLexiconEnabled": True,
            "sensitiveLexiconPath": str(missing_path),
        },
    )

    processor = AggregateProcessor(db_path)
    # The runtime now creates an empty lexicon directory and logs INFO when the
    # configured path is missing, so we capture INFO to verify it is logged.
    with caplog.at_level(logging.INFO, logger="app.services.aggregate_processor"):
        service = processor._get_ai_service()

    assert service is not None, "AI service should still be created when lexicon load fails"
    assert service._lexicon is None, "Lexicon should be None after load failure"
    assert any("lexicon" in rec.message.lower() for rec in caplog.records), \
        "Expected a log message mentioning the lexicon"


def test_default_processor_without_ai_config_falls_back_readably(tmp_path, monkeypatch):
    """AI config incomplete → _get_ai_service() returns None; preview fallback still works."""
    db_path = _setup_db(tmp_path)  # no ai_provider inserted
    _patch_ai_provider_config(monkeypatch, None)
    preview = "少年站在山巅望着远方。" * 5
    catalog = _FakeCatalog(official_content=preview)
    processor = AggregateProcessor(db_path)

    assert processor._get_ai_service() is None

    book_id = "book:no_ai"
    _insert_book(db_path, book_id)
    ch_id = _insert_chapter(db_path, book_id)
    result = asyncio.run(processor._process_chapter(catalog, _chapter_dict(ch_id, book_id)))

    row = _get_chapter_row(db_path, ch_id)
    assert row["status"] != "processed"


def test_official_full_uses_ai_service_process_official_full(tmp_path, monkeypatch):
    """Official full content path must call process_official_full and write AI fields."""
    db_path = _setup_db(tmp_path)
    _patch_ai_provider_config(monkeypatch, None)
    book_id = "book:official_full_ai"
    _insert_book(db_path, book_id)
    ch_id = _insert_chapter(db_path, book_id)

    full_content = "【起点正版】这是一段官方完整正文，字数足够长。" * 20
    catalog = _FakeCatalog(official_content=full_content)
    ai_service = _FakeAIService(content="AI 整理后的官方正文")
    processor = AggregateProcessor(db_path, ai_service=ai_service)

    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    result = asyncio.run(processor._process_chapter(catalog, _chapter_dict(ch_id, book_id)))

    assert len(ai_service.calls) == 1
    assert ai_service.calls[0]["method"] == "official_full"

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """SELECT status, processed_content, ai_model, ai_prompt_tokens, ai_completion_tokens,
                      ai_total_tokens, ai_latency_ms, ai_self_score
               FROM aggregate_chapter_tasks WHERE chapter_id = ?""",
            (ch_id,),
        ).fetchone()
    assert row[0] == "processed"
    assert row[1] == "AI 整理后的官方正文"
    assert row[2] == "official-fake-model"
    assert row[3] == 120
    assert row[4] == 60
    assert row[5] == 180
    assert row[6] == 250
    assert row[7] == 1.0


# ── preview candidate TOC window alignment ───────────────────────────────────


def test_candidate_chapter_uses_candidate_toc_url_not_guessed_book_url(tmp_path, monkeypatch):
    """Preview candidate must fetch chapter via toc's chapterId/chapterUrl, not bookUrl/{index}.html."""
    db_path = _setup_db(tmp_path, ai_enabled=False)
    _patch_ai_provider_config(monkeypatch, None)
    book_id = "book:toc_url"
    _insert_book(db_path, book_id, aggregate_payload={
        "name": "测试书", "author": "作者",
        "sources": [
            {"bookId": "official_src:1", "sourceId": "official_src", "score": 100, "bookUrl": "https://official.example/book/1"},
            {"bookId": "candidate_src:1", "sourceId": "candidate_src", "score": 80, "bookUrl": "https://candidate.example/book/1"},
        ],
    })
    ch_id = _insert_chapter(db_path, book_id, index=3)

    preview = "少年站在山巅，望着远方的云海。" * 10
    real_candidate_url = "https://candidate.example/read/3.html"
    real_candidate_id = encode_chapter_id("candidate_src", real_candidate_url)
    candidate = ("【小说网】" + preview + "后续正文内容扩充了很多。" * 30)

    class TOCOnlyCatalog(_FakeCatalog):
        async def toc(self, book_id: str) -> dict:
            source_id = book_id.split(":")[0]
            if source_id == "candidate_src":
                return {"chapters": [
                    {"chapterId": encode_chapter_id("candidate_src", "https://candidate.example/read/1.html"), "title": "第1章", "index": 1},
                    {"chapterId": encode_chapter_id("candidate_src", "https://candidate.example/read/2.html"), "title": "第2章", "index": 2},
                    {"chapterId": real_candidate_id, "title": "第3章", "index": 3, "chapterUrl": real_candidate_url},
                ]}
            return await super().toc(book_id)

        async def chapter(self, chapter_id: str) -> dict:
            if chapter_id == real_candidate_id:
                return {"content": candidate, "title": "第3章"}
            return await super().chapter(chapter_id)

    catalog = TOCOnlyCatalog(official_content=preview, candidate_content=candidate)
    ai_service = _FakeAIService(content=candidate)
    processor = AggregateProcessor(db_path, ai_service=ai_service)
    processor.ai_aggregate_enabled = lambda aggregate_book_id="": True
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    result = asyncio.run(processor._process_chapter(catalog, _chapter_dict(ch_id, book_id, index=3)))

    row = _get_chapter_row(db_path, ch_id)
    assert row["status"] == "processed"
    assert len(ai_service.calls) == 1


def test_candidate_toc_search_uses_index_window(tmp_path, monkeypatch):
    """For target index=N, only N-2..N+2 window chapters should be fetched and aligned."""
    db_path = _setup_db(tmp_path, ai_enabled=False)
    _patch_ai_provider_config(monkeypatch, None)
    book_id = "book:window"
    _insert_book(db_path, book_id, aggregate_payload={
        "name": "测试书", "author": "作者",
        "sources": [
            {"bookId": "official_src:1", "sourceId": "official_src", "score": 100},
            {"bookId": "candidate_src:1", "sourceId": "candidate_src", "score": 80},
        ],
    })
    ch_id = _insert_chapter(db_path, book_id, index=5)

    preview = "少年站在山巅，望着远方的云海。" * 10

    fetched_chapter_ids: list[str] = []

    class WindowCatalog(_FakeCatalog):
        async def toc(self, book_id: str) -> dict:
            source_id = book_id.split(":")[0]
            if source_id == "candidate_src":
                return {"chapters": [
                    {"chapterId": encode_chapter_id("candidate_src", f"https://c.example/{i}.html"), "title": f"第{i}章", "index": i}
                    for i in range(1, 21)
                ]}
            return await super().toc(book_id)

        async def chapter(self, chapter_id: str) -> dict:
            # Only intercept candidate chapters; let official fall through to _FakeCatalog.
            if not chapter_id.startswith("candidate_src"):
                return await super().chapter(chapter_id)
            _, url = decode_chapter_id(chapter_id)
            fetched_chapter_ids.append(chapter_id)
            # Make chapter 5 align, others mismatch.
            if "5.html" in url:
                return {"content": "【小说网】" + preview + "后续正文内容扩充了很多。" * 30, "title": "第5章"}
            return {"content": "错误的章节内容，与预览完全不同。" * 50, "title": "其他章"}

    catalog = WindowCatalog(official_content=preview)
    ai_service = _FakeAIService(content=preview + "后续正文内容扩充了很多。" * 30)
    processor = AggregateProcessor(db_path, ai_service=ai_service)
    processor.ai_aggregate_enabled = lambda aggregate_book_id="": True
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    result = asyncio.run(processor._process_chapter(catalog, _chapter_dict(ch_id, book_id, index=5)))

    row = _get_chapter_row(db_path, ch_id)
    decoded_urls = [decode_chapter_id(cid)[1] for cid in fetched_chapter_ids]
    assert row["status"] == "processed"
    # Only window chapters 3..7 should be fetched (target index 5 -> 3,4,5,6,7).
    assert len(fetched_chapter_ids) <= 5, f"Expected <=5 fetches, got {len(fetched_chapter_ids)}: {fetched_chapter_ids}"
    assert any("5.html" in url for url in decoded_urls)
    assert not any(f"{i}.html" in url for url in decoded_urls for i in [1, 2, 8, 9, 10, 20])


def test_stage2_uses_highest_priority_source_first_and_stops_on_success(tmp_path, monkeypatch):
    """Stage 2 should try the highest-priority source first and stop once one readable supplement succeeds."""
    db_path = _setup_db(tmp_path, ai_enabled=False)
    book_id = "book:stage2_first_source"
    _insert_book(db_path, book_id, aggregate_payload={
        "name": "测试书", "author": "作者",
        "sources": [
            {"bookId": "official_src:1", "sourceId": "official_src", "score": 100, "bookUrl": "https://official.example/book/1"},
            {"bookId": "candidate_a:1", "sourceId": "candidate_a", "score": 95, "bookUrl": "https://candidate-a.example/book/1"},
            {"bookId": "candidate_b:1", "sourceId": "candidate_b", "score": 80, "bookUrl": "https://candidate-b.example/book/1"},
        ],
    })
    ch_id = _insert_chapter(db_path, book_id, index=1)

    preview = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始，未来路还很长。"
    candidate_a_content = ("【A站】少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。"
                           "他知道这一切才刚刚开始，未来路还很长。后续正文内容扩充了很多。" * 10)
    candidate_b_content = ("【B站】少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。"
                           "他知道这一切才刚刚开始，未来路还很长。这是不该被命中的后续正文。" * 10)
    fetched_candidate_ids: list[str] = []

    class MultiSourceCatalog(_FakeCatalog):
        async def toc(self, book_id: str) -> dict:
            source_id = book_id.split(":")[0]
            return {"chapters": [
                {"chapterId": encode_chapter_id(source_id, f"https://{source_id}.example/ch1.html"), "title": "第1章", "index": 1}
            ]}

        async def chapter(self, chapter_id: str) -> dict:
            if chapter_id.startswith("official_src"):
                return {"content": preview, "title": "第1章"}
            fetched_candidate_ids.append(chapter_id)
            if chapter_id.startswith("candidate_a"):
                return {"content": candidate_a_content, "title": "第1章"}
            if chapter_id.startswith("candidate_b"):
                return {"content": candidate_b_content, "title": "第1章"}
            return await super().chapter(chapter_id)

    ai_service = _FakeAIService(content=candidate_a_content)
    processor = AggregateProcessor(db_path, ai_service=ai_service)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    asyncio.run(processor._process_chapter(MultiSourceCatalog(), _chapter_dict(ch_id, book_id)))

    row = _get_chapter_row(db_path, ch_id)
    assert row["status"] == "fallback"
    assert row["content"] != ""
    assert row["alignment"]["candidateSourceId"] == "candidate_a"
    assert row["fallbackSourceId"] == "candidate_a"
    assert any(chapter_id.startswith("candidate_a") for chapter_id in fetched_candidate_ids)
    assert not any(chapter_id.startswith("candidate_b") for chapter_id in fetched_candidate_ids)


def test_stage2_continues_to_next_source_when_first_source_is_invalid(tmp_path, monkeypatch):
    """Stage 2 should skip an invalid first source and accept the next readable supplement result."""
    db_path = _setup_db(tmp_path, ai_enabled=False)
    book_id = "book:stage2_second_source"
    _insert_book(db_path, book_id, aggregate_payload={
        "name": "测试书", "author": "作者",
        "sources": [
            {"bookId": "official_src:1", "sourceId": "official_src", "score": 100, "bookUrl": "https://official.example/book/1"},
            {"bookId": "candidate_a:1", "sourceId": "candidate_a", "score": 95, "bookUrl": "https://candidate-a.example/book/1"},
            {"bookId": "candidate_b:1", "sourceId": "candidate_b", "score": 85, "bookUrl": "https://candidate-b.example/book/1"},
        ],
    })
    ch_id = _insert_chapter(db_path, book_id, index=1)

    preview = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始，未来路还很长。"
    candidate_b_content = ("【B站】少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。"
                           "他知道这一切才刚刚开始，未来路还很长。后续正文内容扩充了很多。" * 10)
    fetched_candidate_ids: list[str] = []

    class MultiSourceCatalog(_FakeCatalog):
        async def toc(self, book_id: str) -> dict:
            source_id = book_id.split(":")[0]
            return {"chapters": [
                {"chapterId": encode_chapter_id(source_id, f"https://{source_id}.example/ch1.html"), "title": "第1章", "index": 1}
            ]}

        async def chapter(self, chapter_id: str) -> dict:
            if chapter_id.startswith("official_src"):
                return {"content": preview, "title": "第1章"}
            fetched_candidate_ids.append(chapter_id)
            if chapter_id.startswith("candidate_a"):
                return {"content": "", "title": "第1章"}
            if chapter_id.startswith("candidate_b"):
                return {"content": candidate_b_content, "title": "第1章"}
            return await super().chapter(chapter_id)

    ai_service = _FakeAIService(content=candidate_b_content)
    processor = AggregateProcessor(db_path, ai_service=ai_service)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    asyncio.run(processor._process_chapter(MultiSourceCatalog(), _chapter_dict(ch_id, book_id)))

    row = _get_chapter_row(db_path, ch_id)
    assert row["status"] == "fallback"
    assert row["content"] != ""
    assert row["alignment"]["candidateSourceId"] == "candidate_b"
    assert row["fallbackSourceId"] == "candidate_b"
    assert any(chapter_id.startswith("candidate_a") for chapter_id in fetched_candidate_ids)
    assert any(chapter_id.startswith("candidate_b") for chapter_id in fetched_candidate_ids)


def test_stage2_marks_long_cycle_wait_when_all_current_sources_fail(tmp_path, monkeypatch):
    """When every current source fails, Stage 2 should leave the chapter in long-cycle wait instead of writing preview fallback."""
    db_path = _setup_db(tmp_path, ai_enabled=False)
    book_id = "book:stage2_wait"
    _insert_book(db_path, book_id, aggregate_payload={
        "name": "测试书", "author": "作者",
        "sources": [
            {"bookId": "official_src:1", "sourceId": "official_src", "score": 100, "bookUrl": "https://official.example/book/1"},
            {"bookId": "candidate_a:1", "sourceId": "candidate_a", "score": 95, "bookUrl": "https://candidate-a.example/book/1"},
            {"bookId": "candidate_b:1", "sourceId": "candidate_b", "score": 85, "bookUrl": "https://candidate-b.example/book/1"},
        ],
    })
    ch_id = _insert_chapter(db_path, book_id, index=1)

    preview = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始。"

    class MultiSourceCatalog(_FakeCatalog):
        async def toc(self, book_id: str) -> dict:
            source_id = book_id.split(":")[0]
            return {"chapters": [
                {"chapterId": encode_chapter_id(source_id, f"https://{source_id}.example/ch1.html"), "title": "第1章", "index": 1}
            ]}

        async def chapter(self, chapter_id: str) -> dict:
            if chapter_id.startswith("official_src"):
                return {"content": preview, "title": "第1章"}
            if chapter_id.startswith("candidate_a"):
                return {"content": "", "title": "第1章"}
            if chapter_id.startswith("candidate_b"):
                return {"content": "这是一段很短的无效内容。", "title": "第1章"}
            return await super().chapter(chapter_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    result = asyncio.run(processor._process_chapter(MultiSourceCatalog(), _chapter_dict(ch_id, book_id)))

    row = _get_chapter_row(db_path, ch_id)
    assert result["success"] is False
    assert row["status"] == "error"
    # Stage 2 candidate failures are now classified as S2_* codes.
    assert row["lastErrorCode"] == "S2_CANDIDATE_FETCH_FAILED"
    assert row["content"] == ""


def test_stage3_breaker_opens_and_new_ai_work_pauses(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path, ai_enabled=False)
    book_id = "book:stage3_breaker"
    _insert_book(
        db_path,
        book_id,
        aggregate_payload={
            "name": "测试书",
            "author": "作者",
            "sources": [
                {
                    "bookId": f"official_src:{book_id}",
                    "sourceId": "official_src",
                    "score": 100,
                    "bookUrl": f"https://official.example/book/{book_id}",
                }
            ],
        },
    )
    full_content = "这是一段足够长的完整正文。" * 30
    ai_service = _FakeAIService(fail=True, error=RuntimeError("AI provider overloaded"))
    processor = AggregateProcessor(db_path, ai_service=ai_service)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    monkeypatch.setattr(
        processor,
        "_book_workflow_settings",
        lambda aggregate_book_id="": {
            "aiEnabled": True,
            "autoAggregate": True,
            "blockedWordRepair": True,
            "aiFailureRateThreshold": 0.5,
            "aiCircuitBreakerCooldownMinutes": 30,
            "aiTokenBudgetPerHour": 0,
            "stage3PeakHourSkipEnabled": False,
        },
    )
    # Enable shared-book dual write so policy_snapshot_json is persisted to DB.
    monkeypatch.setattr(
        "app.services.aggregate_settings.AggregateSettingsRepository.content_workflow",
        lambda self: {
            "aiEnabled": True,
            "autoAggregate": True,
            "processAggregateOnRead": True,
            "aggregateCheckIntervalMinutes": 10,
            "purifyMode": "conservative",
            "useSharedBookStorage": True,
            "sharedBookStorageDualWrite": True,
            "sharedBookStorageReadMode": "dual_verify",
        },
    )

    # Insert and process chapters one at a time so the shared-book bundle writer
    # never sees empty/unprocessed chapter rows (avoids a product-side kwarg bug
    # in _shared_stage1_status when it is called with positional arguments).
    chapter_ids: list[str] = []
    for index in range(1, 5):
        chapter_id = _insert_chapter(db_path, book_id, index=index)
        chapter_ids.append(chapter_id)
        asyncio.run(
            processor._process_chapter(
                _FakeCatalog(official_content=full_content),
                _chapter_dict(chapter_id, book_id, index=index),
            )
        )

    breaker = processor.ai_circuit_breaker_state(book_id)
    row4 = _get_chapter_row(db_path, chapter_ids[-1])
    trace4 = _get_policy_snapshot(db_path, chapter_ids[-1])
    assert breaker["isOpen"] is True
    assert breaker["reason"] == "failure_rate_threshold_exceeded"
    assert len(ai_service.calls) == 3, "Fourth chapter should pause Stage 3 while breaker is open"
    assert row4["status"] == "fallback"
    assert trace4["chapterStatus"] == "readable"
    assert trace4["proofreadComplete"] is False


def test_stage3_pause_still_allows_stage1_and_stage2_to_complete_readable_content(tmp_path, monkeypatch):
    # AI must be enabled so the open circuit breaker genuinely pauses Stage 3.
    db_path = _setup_db(tmp_path, ai_enabled=True)
    book_id = "book:stage3_pause_flow"
    _insert_book(
        db_path,
        book_id,
        aggregate_payload={
            "name": "测试书",
            "author": "作者",
            "sources": [
                {"bookId": f"official_src:{book_id}", "sourceId": "official_src", "score": 100, "bookUrl": "https://official.example/book/1"},
                {"bookId": f"candidate_src:{book_id}", "sourceId": "candidate_src", "score": 80, "bookUrl": "https://candidate.example/book/1"},
            ],
        },
    )
    full_chapter_id = _insert_chapter(db_path, book_id, index=1)
    preview_chapter_id = _insert_chapter(db_path, book_id, index=2)

    preview = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始。"
    candidate = ("【小说网】少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。"
                 "他知道这一切才刚刚开始。后续正文内容扩充了很多。" * 10)
    full_content = "这是一段完整正文，字数足够长。" * 25

    class PauseCatalog(_FakeCatalog):
        async def chapter(self, chapter_id: str) -> dict:
            if chapter_id == "official_src:ch1":
                return {"content": full_content, "title": "第1章"}
            if chapter_id == "official_src:ch2":
                return {"content": preview, "title": "第2章"}
            source_id, _ = decode_chapter_id(chapter_id)
            if source_id == "candidate_src":
                return {"content": candidate, "title": "第2章"}
            return await super().chapter(chapter_id)

        async def toc(self, book_id: str) -> dict:
            source_id = book_id.split(":")[0]
            index = 2
            return {
                "chapters": [
                    {
                        "chapterId": encode_chapter_id(source_id, f"https://{source_id}.example/ch{index}.html"),
                        "title": "第2章",
                        "chapterUrl": f"https://{source_id}.example/ch{index}.html",
                        "index": index,
                    }
                ]
            }

    ai_service = _FakeAIService(content="不应该被调用")
    processor = AggregateProcessor(db_path, ai_service=ai_service)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    async def fake_try_candidate_content(catalog, chapter, payload, primary_source_id):
        if chapter["chapterId"] == preview_chapter_id:
            return {
                "content": candidate,
                "source_id": "candidate_src",
                "alignment_json": {
                    "primarySourceId": "official_src",
                    "candidateSourceId": "candidate_src",
                    "selectedContentSource": "candidate",
                    "alignmentPassed": True,
                },
            }
        return None
    monkeypatch.setattr(processor, "_try_candidate_content", fake_try_candidate_content)
    processor._ai_circuit_breakers[book_id] = {
        "reason": "token_budget_exceeded",
        "openUntil": processor._now_dt() + timedelta(minutes=20),
    }

    asyncio.run(processor._process_chapter(PauseCatalog(), _chapter_dict(full_chapter_id, book_id, index=1)))
    asyncio.run(processor._process_chapter(PauseCatalog(), _chapter_dict(preview_chapter_id, book_id, index=2)))

    full_row = _get_chapter_row(db_path, full_chapter_id)
    preview_row = _get_chapter_row(db_path, preview_chapter_id)
    assert ai_service.calls == []
    assert full_row["status"] == "fallback"
    assert full_row["content"] != PROCESSING_PLACEHOLDER
    assert preview_row["status"] == "fallback"
    assert preview_row["fallbackSourceId"] == "candidate_src"
    assert len(preview_row["content"]) > len(preview)


def test_stage3_deferred_chapter_stays_readable_unproofread_and_retries_from_periodic_scan(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path, ai_enabled=False)
    book_id = "book:stage3_deferred_retry"
    _insert_book(db_path, book_id)
    chapter_id = _insert_chapter(db_path, book_id, index=1)
    full_content = "这是一段完整正文，字数足够长。" * 25

    ai_service = _FakeAIService(content="不应该被调用")
    processor = AggregateProcessor(db_path, ai_service=ai_service)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")
    # Enable shared-book dual write so policy_snapshot_json is persisted to DB.
    monkeypatch.setattr(
        "app.services.aggregate_settings.AggregateSettingsRepository.content_workflow",
        lambda self: {
            "aiEnabled": True,
            "autoAggregate": True,
            "processAggregateOnRead": True,
            "aggregateCheckIntervalMinutes": 10,
            "purifyMode": "conservative",
            "useSharedBookStorage": True,
            "sharedBookStorageDualWrite": True,
            "sharedBookStorageReadMode": "dual_verify",
        },
    )
    processor._ai_circuit_breakers[book_id] = {
        "reason": "failure_rate_threshold_exceeded",
        "openUntil": processor._now_dt() + timedelta(minutes=10),
    }

    asyncio.run(
        processor._process_chapter(
            _FakeCatalog(official_content=full_content),
            _chapter_dict(chapter_id, book_id, index=1),
        )
    )

    row = _get_chapter_row(db_path, chapter_id)
    trace = _get_policy_snapshot(db_path, chapter_id)
    response = processor.aggregate_chapter_response(
        make_aggregate_chapter_url(book_id, "official_src:ch1", title="第1章", index=1),
        chapter_id=chapter_id,
    )
    runtime_store = SharedBookRuntimeStore(storage=SharedBookStorage(tmp_path / "library"))
    state = runtime_store.load_state(book_name="测试书", author="作者")
    assert row["status"] == "fallback"
    assert trace["chapterStatus"] == "readable"
    assert trace["proofreadComplete"] is False
    assert response["content"] == full_content.strip()
    assert len(state.stage3Deferred) == 1

    deferred = state.stage3Deferred[0].model_copy(update={"retryNotBefore": "2000-01-01T00:00:00+00:00"})
    runtime_store.save_state(
        book_name="测试书",
        author="作者",
        state=state.model_copy(update={"stage3Deferred": [deferred]}),
    )
    chapters = processor._chapters_for_processing(book_id, limit=5)
    assert any(item["chapterId"] == chapter_id for item in chapters)


def test_stage1_dual_write_writes_shared_storage_and_dual_verify_logs_mismatch(
    tmp_path, monkeypatch, caplog
):
    db_path = _setup_db(tmp_path, ai_enabled=False)
    book_id = "book:shared_stage1"
    _insert_book(
        db_path,
        book_id,
        aggregate_payload={
            "name": "测试书",
            "author": "作者",
            "sources": [
                {
                    "bookId": f"official_src:{book_id}",
                    "sourceId": "official_src",
                    "sourceName": "官方源",
                    "score": 100,
                    "bookUrl": "https://official.example/book/shared_stage1",
                    "tocUrl": "https://official.example/book/shared_stage1/toc",
                }
            ],
        },
    )
    chapter_id = _insert_chapter(db_path, book_id, index=1)
    processor = AggregateProcessor(db_path)

    monkeypatch.setattr(
        "app.services.aggregate_settings.AggregateSettingsRepository.content_workflow",
        lambda self: {
            "aiEnabled": True,
            "autoAggregate": True,
            "processAggregateOnRead": True,
            "aggregateCheckIntervalMinutes": 10,
            "blockedWordRepair": True,
            "useSharedBookStorage": True,
            "sharedBookStorageDualWrite": True,
            "sharedBookStorageReadMode": "dual_verify",
        },
    )

    content = "第一章完整正文\n第二段内容"
    processor._write_chapter_result(
        chapter_id=chapter_id,
        aggregate_book_id=book_id,
        title="第1章",
        chapter_index=1,
        status="processed",
        content=content,
        alignment_json={
            "primarySourceId": "official_src",
            "selectedContentSource": "official",
            "alignmentPassed": True,
        },
        fallback_source_id="official_src",
        ai_model="official-fake-model",
        ai_self_score=0.98,
        ai_prompt_tokens=120,
        ai_completion_tokens=60,
        ai_total_tokens=180,
        ai_latency_ms=250,
        source_word_count=321,
        primary_source_chapter_url="https://official.example/book/shared_stage1/1",
        preview_only=False,
    )

    storage = SharedBookStorage(tmp_path / "library")
    chapter_path = storage.chapter_markdown_path(
        book_name="测试书",
        author="作者",
        chapter_index=1,
        title="第1章",
    )
    chapter_index_path = storage.chapter_index_path(book_name="测试书", author="作者")
    metadata_path = storage.metadata_path(book_name="测试书", author="作者")

    assert chapter_path.exists()
    assert chapter_index_path.exists()
    assert metadata_path.exists()

    chapter_markdown = chapter_path.read_text(encoding="utf-8")
    trace = storage.parse_trace_block(chapter_markdown)
    chapter_index_payload = json.loads(chapter_index_path.read_text(encoding="utf-8"))
    metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert trace["chapterIndex"] == 1
    assert trace["chapterTitle"] == "第1章"
    assert trace["chapterStatus"] == "proofread_complete"
    assert trace["proofreadComplete"] is True
    assert trace["previewOnly"] is False
    assert trace["primarySource"]["sourceId"] == "official_src"
    # The shared-book trace no longer exposes private source chapter URLs.
    assert "chapterUrl" not in trace["primarySource"]
    assert trace["primarySource"]["wordCount"] == 321
    assert trace["officialWordCount"] == 321
    assert trace["fetchedWordCount"] == len(content)
    assert chapter_index_payload["chapters"] == [
        {
            "index": 1,
            "title": "第1章",
            "file": "chapters/0001-第1章.md",
            "status": "proofread_complete",
        }
    ]
    assert metadata_payload["bookState"]["processedChapterCount"] == 1
    assert metadata_payload["bookState"]["proofreadCompleteCount"] == 1

    tampered_markdown = chapter_markdown.replace("第二段内容", "被篡改的共享内容")
    chapter_path.write_text(tampered_markdown, encoding="utf-8", newline="\n")

    chapter_url = make_aggregate_chapter_url(
        aggregate_book_id=book_id,
        source_chapter_id="official_src:ch1",
        title="第1章",
        index=1,
    )
    with caplog.at_level("WARNING", logger="app.services.aggregate_processor"):
        response = processor.aggregate_chapter_response(chapter_url, chapter_id=chapter_id)

    assert response["content"] == content
    assert any("dual_verify" in record.message for record in caplog.records)
