"""Tests for AggregateProcessor state machine: preview / third-party / fallback paths."""

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.aggregate_processor import AggregateProcessor
from app.services.aggregate_settings import PROCESSING_PLACEHOLDER
from app.services.catalog import Catalog
from app.services.novel_file_cache import NovelFileCache
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
        "useSharedBookStorage": True,
        "sharedBookStorageDualWrite": False,
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


def test_read_chapter_content_skips_garbled_local_file(tmp_path):
    processor = AggregateProcessor(db_path=tmp_path / "test.db")
    normal = tmp_path / "normal.md"
    garbled = tmp_path / "garbled.md"
    normal.write_text("# 第一章\n\n这是正常中文正文。\n", encoding="utf-8")
    garbled.write_text("# 第一章\n\njF9@\ufffd\ufffd\ufffd\u0011\u0000\ufffd" * 20, encoding="utf-8")

    assert processor._read_chapter_content_from_file(str(normal)) == "这是正常中文正文。"
    assert processor._read_chapter_content_from_file(str(garbled)) == ""


def test_garbled_content_is_not_persisted_or_reused(tmp_path):
    db_path = _setup_db(tmp_path)
    processor = AggregateProcessor(db_path=db_path)
    garbled = "jF9@\ufffd\ufffd\ufffd\u0011\u0000\ufffd" * 20

    with pytest.raises(ValueError, match="garbled"):
        processor._save_source_snapshot(
            aggregate_book_id="book-1",
            chapter_index=1,
            source_id="official_src",
            source_book_id="source-book-1",
            source_chapter_id="source-chapter-1",
            title="第一章",
            clean_content=garbled,
            classification="unknown",
        )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO aggregate_source_snapshots
               (aggregate_book_id, chapter_index, source_id, clean_content, content_hash)
               VALUES (?, ?, ?, ?, ?)""",
            ("book-1", 1, "official_src", garbled, "legacy-bad-hash"),
        )
        conn.commit()

    assert processor._load_source_snapshot_content(
        aggregate_book_id="book-1",
        chapter_index=1,
        source_id="official_src",
    ) == ""

    with pytest.raises(ValueError, match="garbled"):
        processor._write_chapter_result(
            chapter_id="book-1:ch1",
            aggregate_book_id="book-1",
            title="第一章",
            chapter_index=1,
            status="processed",
            content=garbled,
            alignment_json={},
        )

    with sqlite3.connect(db_path) as conn, pytest.raises(ValueError, match="garbled"):
        NovelFileCache(root=tmp_path / "cache").write_chapter(
            conn=conn,
            chapter_id="official_src:chapter-1",
            source_id="official_src",
            chapter_url="https://example.com/chapter/1",
            title="第一章",
            content=garbled,
        )


def test_catalog_rejects_garbled_plugin_chapter():
    garbled = "jF9@\ufffd\ufffd\ufffd\u0011\u0000\ufffd" * 20

    class FakeScheduler:
        async def chapter(self, source_id, chapter_url):
            return {"title": "第一章", "content": garbled, "debug": {}}

    class FakeCache:
        def get_chapter(self, chapter_id):
            return None

        def set_chapter(self, *args, **kwargs):
            raise AssertionError("garbled content must not enter chapter_cache")

    catalog = object.__new__(Catalog)
    catalog.scheduler = FakeScheduler()
    catalog.cache = FakeCache()
    chapter_id = encode_chapter_id("official_src", "https://example.com/chapter/1")

    result = asyncio.run(catalog.chapter(chapter_id))

    assert result["content"] == ""
    assert result["debug"]["error"] == "garbled chapter content"


def test_catalog_preserves_paid_chapter_flags():
    cached: list[dict] = []

    class FakeScheduler:
        async def chapter(self, source_id, chapter_url):
            return {
                "title": "付费章节",
                "content": "付费章节预览",
                "authRequired": True,
                "isPaid": True,
                "extra": {"previewOnly": True},
                "debug": {},
            }

    class FakeCache:
        def get_chapter(self, chapter_id):
            return None

        def set_chapter(self, chapter_id, source_id, chapter_url, data):
            cached.append(data)

    catalog = object.__new__(Catalog)
    catalog.scheduler = FakeScheduler()
    catalog.cache = FakeCache()
    chapter_id = encode_chapter_id("official_src", "https://example.com/chapter/paid")

    result = asyncio.run(catalog.chapter(chapter_id))

    assert result["authRequired"] is True
    assert result["isPaid"] is True
    assert cached[0]["authRequired"] is True
    assert cached[0]["isPaid"] is True


def test_candidate_sources_respect_source_candidate_limit(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    processor = AggregateProcessor(db_path=db_path)
    monkeypatch.setattr(
        processor,
        "_book_workflow_settings",
        lambda _book_id: {"sourceCandidateLimit": 2},
    )

    class FakeSourceMapService:
        def __init__(self, *args, **kwargs):
            pass

        def load_current_source_map_refs(self, *args, **kwargs):
            return [
                {"sourceId": "s1", "bookId": "s1:b", "score": 100},
                {"sourceId": "s2", "bookId": "s2:b", "score": 90},
                {"sourceId": "s3", "bookId": "s3:b", "score": 80},
            ]

    monkeypatch.setattr(
        "app.services.shared_book_source_map.SharedBookSourceMapService",
        FakeSourceMapService,
    )

    candidates = processor._candidate_sources_from_payload({}, "official", "book-1")

    assert [item["sourceId"] for item in candidates] == ["s1", "s2"]


def test_candidate_sources_respect_candidate_source_priority(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    processor = AggregateProcessor(db_path=db_path)
    monkeypatch.setattr(
        processor,
        "_book_workflow_settings",
        lambda _book_id: {
            "sourceCandidateLimit": 10,
            "candidateSourcePriority": ["s3", "s1"],
        },
    )

    class FakeSourceMapService:
        def __init__(self, *args, **kwargs):
            pass

        def load_current_source_map_refs(self, *args, **kwargs):
            return [
                {"sourceId": "s1", "bookId": "s1:b", "score": 100},
                {"sourceId": "s2", "bookId": "s2:b", "score": 90},
                {"sourceId": "s3", "bookId": "s3:b", "score": 80},
            ]

    monkeypatch.setattr(
        "app.services.shared_book_source_map.SharedBookSourceMapService",
        FakeSourceMapService,
    )

    candidates = processor._candidate_sources_from_payload({}, "official", "book-1")

    assert [item["sourceId"] for item in candidates] == ["s3", "s1"]


class _FakeCatalog:
    """Returns different content depending on source_chapter_id prefix."""

    def __init__(self, *, official_content="", candidate_content="",
                 official_fail=False, candidate_fail=False,
                 official_extra=None, candidate_extra=None):
        self._official = official_content
        self._candidate = candidate_content
        self._official_fail = official_fail
        self._candidate_fail = candidate_fail
        self._official_extra = official_extra
        self._candidate_extra = candidate_extra

    async def chapter(self, chapter_id: str) -> dict:
        if chapter_id.startswith("official_src"):
            if self._official_fail:
                raise RuntimeError("official source failed")
            result = {"content": self._official, "title": "第1章"}
            if self._official_extra is not None:
                result["extra"] = self._official_extra
            return result
        if chapter_id.startswith("candidate_src"):
            if self._candidate_fail:
                raise RuntimeError("candidate source failed")
            result = {"content": self._candidate, "title": "第1章"}
            if self._candidate_extra is not None:
                result["extra"] = self._candidate_extra
            return result
        # Fallback: try official
        if self._official_fail:
            raise RuntimeError("source fetch failed")
        result = {"content": self._official, "title": "第1章"}
        if self._official_extra is not None:
            result["extra"] = self._official_extra
        return result

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
            "SELECT status, content_file_path, source_alignment_json, fallback_source_id, last_error_code, preview_only "
            "FROM aggregate_chapter_tasks WHERE chapter_id = ?", (ch_id,),
        ).fetchone()
    if not row:
        return None
    alignment = {}
    try:
        alignment = json.loads(row[2] or "{}")
    except Exception:
        pass
    content = ""
    if row[1]:
        try:
            content = Path(row[1]).read_text(encoding="utf-8")
            TRACE_RE = re.compile(
                r"(?:\n|^)(?:<!--\s*)?LEGADOHUB_TRACE_BEGIN\s*(?:```yaml\s*)?\n.*?\n(?:\s*```\s*)?LEGADOHUB_TRACE_END(?:\s*-->)?\s*$",
                re.DOTALL,
            )
            content = TRACE_RE.sub("", content).strip()
            if content.startswith("# "):
                lines = content.split("\n", 1)
                content = lines[1] if len(lines) > 1 else ""
            content = content.strip()
        except Exception:
            pass
    return {"status": row[0], "content": content, "alignment": alignment,
            "fallbackSourceId": row[3] or "", "lastErrorCode": row[4] or "",
            "previewOnly": bool(row[5])}


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


def test_processing_enabled_does_not_use_process_aggregate_on_read_for_background_subscription(tmp_path):
    """Disabling reading-triggered aggregation must not disable shared-subscription background jobs."""
    db_path = _setup_db(tmp_path, ai_enabled=False)

    config_dir = tmp_path / "config"
    config_path = config_dir / "app_config.json"
    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    config_data["aggregate"]["contentWorkflow"]["processAggregateOnRead"] = False
    config_path.write_text(json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

    import app.core.app_config as _app_config_module

    _app_config_module.AppConfig.reset()

    processor = AggregateProcessor(db_path)
    assert processor.processing_enabled() is True
    assert processor.processing_enabled("book:any") is True


def test_processing_enabled_respects_auto_aggregate_for_background_subscription(tmp_path):
    """The real background subscription kill switch remains autoAggregate."""
    db_path = _setup_db(tmp_path, ai_enabled=False)

    config_dir = tmp_path / "config"
    config_path = config_dir / "app_config.json"
    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    config_data["aggregate"]["contentWorkflow"]["autoAggregate"] = False
    config_path.write_text(json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

    import app.core.app_config as _app_config_module

    _app_config_module.AppConfig.reset()

    processor = AggregateProcessor(db_path)
    assert processor.processing_enabled() is False
    assert processor.processing_enabled("book:any") is False


def test_run_due_once_still_runs_when_process_aggregate_on_read_disabled(tmp_path, monkeypatch):
    """Background subscription scheduler must still run when only reading-trigger aggregation is disabled."""
    db_path = _setup_db(tmp_path, ai_enabled=False)
    book_id = "book:due_processes"
    _insert_book(db_path, book_id)

    config_dir = tmp_path / "config"
    config_path = config_dir / "app_config.json"
    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    config_data["aggregate"]["contentWorkflow"]["processAggregateOnRead"] = False
    config_path.write_text(json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

    import app.core.app_config as _app_config_module

    _app_config_module.AppConfig.reset()

    processor = AggregateProcessor(db_path)

    async def _fake_run_book_task(aggregate_book_id: str):
        return {"bookId": aggregate_book_id, "success": True}

    monkeypatch.setattr(processor, "run_book_task", _fake_run_book_task)

    result = asyncio.run(processor.run_due_once(limit=5))

    assert result["enabled"] is True
    assert result["dueBooks"] == 1
    assert result["processedBooks"] == 1


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
    """A chapter with status='fallback' and content_file_path must return file content."""
    from app.services.aggregate_virtual_source import (
        make_aggregate_chapter_url, VIRTUAL_SOURCE_ID,
    )
    from app.source_plugins.id_codec import encode_chapter_id

    db_path = _setup_db(tmp_path, ai_enabled=False)
    book_id = "book:fallback_resp"
    _insert_book(db_path, book_id)
    ch_id = _insert_chapter(db_path, book_id)

    storage = SharedBookStorage(root=db_path.parent / "library")
    md_path = storage.chapter_markdown_path(
        book_name="测试书", author="作者", chapter_index=1, title="第1章",
    )
    md_path.parent.mkdir(parents=True, exist_ok=True)
    trace_block = storage.render_trace_block({"chapterId": ch_id, "status": "fallback"})
    md_content = storage.render_chapter_markdown(
        title="第1章", body="这是 fallback 正文内容", trace_payload={"chapterId": ch_id, "status": "fallback"},
    )
    md_path.write_text(md_content, encoding="utf-8")

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE aggregate_chapter_tasks SET status='fallback', "
            "content_file_path=? WHERE chapter_id=?",
            (str(md_path), ch_id),
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


def test_default_processor_does_not_build_ai_service_while_runtime_disabled(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path)
    _patch_ai_provider_config(monkeypatch, {
        "baseUrl": "https://api.example.com/v1",
        "apiKey": "sk-test",
        "model": "mimo-v2.5",
    })
    processor = AggregateProcessor(db_path)

    service = processor._get_ai_service()

    assert service is None


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

    catalog = TOCOnlyCatalog(official_content=preview, candidate_content=candidate,
                             official_extra={"previewOnly": True})
    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    result = asyncio.run(processor._process_chapter(catalog, _chapter_dict(ch_id, book_id, index=3)))

    row = _get_chapter_row(db_path, ch_id)
    assert row["status"] == "fallback"


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

    catalog = WindowCatalog(official_content=preview, official_extra={"previewOnly": True})
    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    result = asyncio.run(processor._process_chapter(catalog, _chapter_dict(ch_id, book_id, index=5)))

    row = _get_chapter_row(db_path, ch_id)
    decoded_urls = [decode_chapter_id(cid)[1] for cid in fetched_chapter_ids]
    assert row["status"] == "fallback"
    # Only window chapters 3..7 should be fetched (target index 5 -> 3,4,5,6,7).
    assert len(fetched_chapter_ids) <= 5, f"Expected <=5 fetches, got {len(fetched_chapter_ids)}: {fetched_chapter_ids}"
    assert any("5.html" in url for url in decoded_urls)
    assert not any(f"{i}.html" in url for url in decoded_urls for i in [1, 2, 8, 9, 10, 20])


def test_stage2_reads_all_candidates_and_keeps_priority_with_consensus(tmp_path, monkeypatch):
    """Stage 2 should compare every valid candidate before selecting a consensus."""
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
                return {"content": preview, "title": "第1章", "extra": {"previewOnly": True}}
            fetched_candidate_ids.append(chapter_id)
            if chapter_id.startswith("candidate_a"):
                return {"content": candidate_a_content, "title": "第1章"}
            if chapter_id.startswith("candidate_b"):
                return {"content": candidate_b_content, "title": "第1章"}
            return await super().chapter(chapter_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    asyncio.run(processor._process_chapter(MultiSourceCatalog(), _chapter_dict(ch_id, book_id)))

    row = _get_chapter_row(db_path, ch_id)
    assert row["status"] == "fallback"
    assert row["content"] != ""
    assert row["alignment"]["candidateSourceId"] == "candidate_a"
    assert row["fallbackSourceId"] == "candidate_a"
    assert any(chapter_id.startswith("candidate_a") for chapter_id in fetched_candidate_ids)
    assert any(chapter_id.startswith("candidate_b") for chapter_id in fetched_candidate_ids)


def test_candidate_consensus_rejects_out_of_order_body(tmp_path):
    processor = AggregateProcessor(db_path=tmp_path / "test.db")
    opening = "冬日阴云，寒风阵阵。季觉站在寥落破败的厂区前面，鼓起勇气发问。"
    paragraphs = [
        opening,
        "中年人即答，告诉他欢迎进厂。",
        "而季觉的神情顿时一言难尽起来。",
        "延建带着大家召开了第一次重组会议。",
        "所有人开始讨论生产线的具体问题。",
    ]
    ordered = "\n\n".join(paragraphs * 12)
    disordered = "\n\n".join([
        paragraphs[0], paragraphs[3], paragraphs[1], paragraphs[4], paragraphs[2],
    ] * 12)

    selected, consensus = processor._select_consistent_candidate([
        {"source_id": "scrambled", "content": disordered, "alignment_json": {}},
        {"source_id": "normal_a", "content": ordered, "alignment_json": {}},
        {"source_id": "normal_b", "content": ordered, "alignment_json": {}},
    ])

    assert selected and selected["source_id"] == "normal_a"
    assert next(item for item in consensus if item["sourceId"] == "scrambled")["supportCount"] == 0


def test_candidate_consensus_rejects_similarity_below_ninety_percent(tmp_path, monkeypatch):
    import app.services.aggregate_alignment as alignment

    processor = AggregateProcessor(db_path=tmp_path / "test.db")
    monkeypatch.setattr(alignment, "cross_source_content_similarity", lambda left, right: 0.85)

    selected, consensus = processor._select_consistent_candidate([
        {"source_id": "candidate_a", "content": "正文甲", "alignment_json": {}},
        {"source_id": "candidate_b", "content": "正文乙", "alignment_json": {}},
    ])

    assert selected is None
    assert all(item["supportCount"] == 0 for item in consensus)


def test_stage2_keeps_preview_when_only_one_candidate_is_valid(tmp_path, monkeypatch):
    """A lone supplement cannot establish that its sentence order is trustworthy."""
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
                return {"content": preview, "title": "第1章", "extra": {"previewOnly": True}}
            fetched_candidate_ids.append(chapter_id)
            if chapter_id.startswith("candidate_a"):
                return {"content": "", "title": "第1章"}
            if chapter_id.startswith("candidate_b"):
                return {"content": candidate_b_content, "title": "第1章"}
            return await super().chapter(chapter_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    asyncio.run(processor._process_chapter(MultiSourceCatalog(), _chapter_dict(ch_id, book_id)))

    row = _get_chapter_row(db_path, ch_id)
    assert row["status"] == "fallback"
    assert row["content"] != ""
    assert row["alignment"]["candidateSourceId"] == ""
    assert row["previewOnly"] is True
    assert any(chapter_id.startswith("candidate_a") for chapter_id in fetched_candidate_ids)
    assert any(chapter_id.startswith("candidate_b") for chapter_id in fetched_candidate_ids)


def test_stage2_keeps_preview_for_solitary_nearby_title_match(tmp_path, monkeypatch):
    """A nearby-title match still needs an independent content confirmation."""
    db_path = _setup_db(tmp_path, ai_enabled=False)
    book_id = "book:stage2_nearby_index_drift"
    _insert_book(db_path, book_id, aggregate_payload={
        "name": "测试书", "author": "作者",
        "sources": [
            {"bookId": "official_src:1", "sourceId": "official_src", "score": 100, "bookUrl": "https://official.example/book/1"},
            {"bookId": "candidate_src:1", "sourceId": "candidate_src", "score": 80, "bookUrl": "https://candidate.example/book/1"},
        ],
    })
    ch_id = _insert_chapter(db_path, book_id, index=1)

    preview = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始，未来路还很长。"
    matched_candidate = ("【候选源】" + preview + "后续正文内容扩充了很多。" * 20)

    class DriftCatalog(_FakeCatalog):
        async def toc(self, book_id: str) -> dict:
            source_id = book_id.split(":")[0]
            if source_id == "candidate_src":
                return {"chapters": [
                    {"chapterId": encode_chapter_id("candidate_src", "https://candidate.example/wrong.html"), "title": "山风起时", "index": 1},
                    {"chapterId": encode_chapter_id("candidate_src", "https://candidate.example/right.html"), "title": "云海翻腾", "index": 2},
                    {"chapterId": encode_chapter_id("candidate_src", "https://candidate.example/other.html"), "title": "夜雨将至", "index": 3},
                ]}
            return await super().toc(book_id)

        async def chapter(self, chapter_id: str) -> dict:
            _, chapter_url = decode_chapter_id(chapter_id)
            if chapter_url.endswith("wrong.html"):
                return {"content": "完全不相关的错误正文。" * 30, "title": "山风起时"}
            if chapter_url.endswith("right.html"):
                return {"content": matched_candidate, "title": "云海翻腾"}
            if chapter_url.endswith("other.html"):
                return {"content": "另一段错误正文。" * 30, "title": "夜雨将至"}
            return await super().chapter(chapter_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    asyncio.run(processor._process_chapter(DriftCatalog(official_content=preview, official_extra={"previewOnly": True}), _chapter_dict(ch_id, book_id)))

    row = _get_chapter_row(db_path, ch_id)
    assert row["status"] == "fallback"
    assert row["alignment"]["candidateSourceId"] == ""
    assert row["previewOnly"] is True
    assert row["fallbackSourceId"] == "official_src"
    assert row["content"] == preview


def test_stage2_rejects_candidate_that_is_not_longer_than_official_preview(tmp_path, monkeypatch):
    """A candidate that is still shorter than the official preview should not replace the official preview."""
    db_path = _setup_db(tmp_path, ai_enabled=False)
    book_id = "book:stage2_shorter_candidate"
    _insert_book(db_path, book_id, aggregate_payload={
        "name": "测试书", "author": "作者",
        "sources": [
            {"bookId": "official_src:1", "sourceId": "official_src", "score": 100, "bookUrl": "https://official.example/book/1"},
            {"bookId": "candidate_src:1", "sourceId": "candidate_src", "score": 80, "bookUrl": "https://candidate.example/book/1"},
        ],
    })
    ch_id = _insert_chapter(db_path, book_id, index=1)

    official_preview = ("少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。"
                        "他知道这一切才刚刚开始，未来路还很长。") * 3
    shorter_candidate = official_preview[: len(official_preview) - 40]

    class PreviewVsShorterCandidateCatalog(_FakeCatalog):
        async def toc(self, book_id: str) -> dict:
            source_id = book_id.split(":")[0]
            if source_id == "candidate_src":
                return {"chapters": [
                    {"chapterId": encode_chapter_id("candidate_src", "https://candidate.example/ch1.html"), "title": "第1章", "index": 1}
                ]}
            return await super().toc(book_id)

        async def chapter(self, chapter_id: str) -> dict:
            if chapter_id.startswith("official_src"):
                return {
                    "content": official_preview,
                    "title": "第1章",
                    "extra": {"previewOnly": True},
                }
            if chapter_id.startswith("candidate_src"):
                return {"content": shorter_candidate, "title": "第1章"}
            return await super().chapter(chapter_id)

    processor = AggregateProcessor(db_path)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    result = asyncio.run(processor._process_chapter(PreviewVsShorterCandidateCatalog(), _chapter_dict(ch_id, book_id)))

    row = _get_chapter_row(db_path, ch_id)
    assert result.get("fallback") is True
    assert row["status"] == "fallback"
    assert row["previewOnly"] == 1
    assert row["fallbackSourceId"] == "official_src"
    assert row["alignment"]["selectedContentSource"] == "preview_fallback"
    assert official_preview[:80] in row["content"]


def test_stage2_falls_back_to_official_preview_when_candidates_fail(tmp_path, monkeypatch):
    """When every candidate source fails, Stage 2 should still keep the official preview as a readable fallback."""
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
    assert result["success"] is True
    assert result.get("fallback") is True
    assert row["status"] == "fallback"
    assert row["previewOnly"] == 1
    assert preview in row["content"]


def test_refresh_shared_book_state_uses_configured_min_readable_threshold(tmp_path):
    db_path = _setup_db(tmp_path, ai_enabled=False)
    book_id = "book:visibility_threshold"
    _insert_book(db_path, book_id)
    for index in range(1, 71):
        _insert_chapter(db_path, book_id, index=index, status="processed")

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE aggregate_book_tasks
            SET total_chapters = 200,
                start_chapter_index = 1,
                processed_chapters = 70,
                visible_processed_chapters = 0,
                search_visibility_status = 'hidden'
            WHERE aggregate_book_id = ?
            """,
            (book_id,),
        )
        conn.commit()

    config_path = tmp_path / "config" / "app_config.json"
    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    config_data["aggregate"]["contentWorkflow"]["minReadableChaptersForDiscovery"] = 80
    config_path.write_text(json.dumps(config_data, ensure_ascii=False), encoding="utf-8")

    processor = AggregateProcessor(db_path)
    processor._refresh_shared_book_state(book_id)

    with sqlite3.connect(db_path) as conn:
        refreshed = conn.execute(
            """
            SELECT visible_processed_chapters, search_visibility_status
            FROM aggregate_book_tasks
            WHERE aggregate_book_id = ?
            """,
            (book_id,),
        ).fetchone()

    assert refreshed[0] == 70
    assert refreshed[1] == "hidden"


class TestSharedBookProcessLoggerTailStream:
    """Tail -f style log streaming for the subscription processing panel."""

    @pytest.mark.asyncio
    async def test_tail_stream_yields_appended_records(self, tmp_path):
        from app.services.shared_book_storage import SharedBookStorage
        from app.services.shared_book_runtime import SharedBookProcessLogger

        storage = SharedBookStorage(root=tmp_path / "library")
        logger = SharedBookProcessLogger(storage)
        book_name = "测试日志书"
        author = "测试作者"

        records = []
        tail_task = asyncio.create_task(
            self._collect(logger.tail_stream(book_name=book_name, author=author, poll_interval_seconds=0.05), records)
        )

        await asyncio.sleep(0.02)
        logger.append(book_name=book_name, author=author, event="chapter_write", book_id="b1", chapter_index=1, stage="stage1", payload={"title": "第一章"})
        logger.append(book_name=book_name, author=author, event="chapter_error", book_id="b1", chapter_index=2, stage="stage1", error_code="E1", error_message="boom")

        await asyncio.sleep(0.1)
        tail_task.cancel()
        try:
            await tail_task
        except asyncio.CancelledError:
            pass

        assert len(records) >= 2
        assert records[0]["event"] == "chapter_write"
        assert records[0]["chapterIndex"] == 1
        assert records[1]["event"] == "chapter_error"
        assert records[1]["errorCode"] == "E1"

    async def _collect(self, gen, out):
        async for record in gen:
            out.append(record)
