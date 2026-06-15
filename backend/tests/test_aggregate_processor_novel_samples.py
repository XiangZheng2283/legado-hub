"""Aggregate processor tests backed by real novel samples.

These tests use local chapter files (by default ``backend/data/novels/legadohub_ai_aggregate/诡秘之主``)
as realistic Chinese web-novel input.  The sample directory can be overridden via the
``LEGADO_HUB_TEST_NOVEL_SAMPLE`` environment variable; if neither the env var nor the default
directory exists, the tests are skipped with a clear reason.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.services.aggregate_processor import AggregateProcessor
from app.source_plugins.id_codec import decode_chapter_id, encode_chapter_id
from app.storage.db import initialize_database


# ── sample discovery ─────────────────────────────────────────────────────────


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def novel_sample_dir() -> Path:
    env_path = os.environ.get("LEGADO_HUB_TEST_NOVEL_SAMPLE")
    if env_path:
        sample_dir = Path(env_path)
    else:
        sample_dir = _project_root() / "data" / "novels" / "legadohub_ai_aggregate" / "诡秘之主"

    if not sample_dir.exists():
        pytest.skip(
            f"Novel sample not found at {sample_dir}. "
            "Set LEGADO_HUB_TEST_NOVEL_SAMPLE to a directory containing chapter .md files."
        )
    return sample_dir


def _load_chapter_texts(sample_dir: Path, count: int = 2, max_chars: int = 2000) -> list[str]:
    files = sorted(f for f in sample_dir.iterdir() if f.is_file() and f.suffix.lower() == ".md")
    if len(files) < count:
        pytest.skip(
            f"Sample directory {sample_dir} only has {len(files)} chapter files, "
            f"need at least {count}."
        )
    texts = []
    for f in files[:count]:
        full = f.read_text(encoding="utf-8")
        texts.append(full[:max_chars] if len(full) > max_chars else full)
    return texts


# ── DB helpers (local copies so this file can run independently) ─────────────


def _setup_db(db_path: Path, *, purify: str = "conservative") -> Path:
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO admin_settings (key, value_json) VALUES (?, ?)",
            (
                "contentWorkflow",
                json.dumps({
                    "aiEnabled": True,
                    "autoAggregate": True,
                    "processAggregateOnRead": True,
                    "aggregateCheckIntervalMinutes": 10,
                    "purifyMode": purify,
                }, ensure_ascii=False),
            ),
        )
        conn.commit()
    return db_path


def _insert_book(
    db_path: Path,
    book_id: str,
    *,
    primary_source_id: str = "official_src",
    aggregate_payload: dict[str, Any] | None = None,
) -> None:
    payload = aggregate_payload or {
        "name": "诡秘之主",
        "author": "爱潜水的乌贼",
        "sources": [
            {"bookId": f"official_src:{book_id}", "sourceId": "official_src", "score": 100},
            {"bookId": f"candidate_src:{book_id}", "sourceId": "candidate_src", "score": 80},
        ],
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO aggregate_book_tasks
               (aggregate_book_id, name, author, primary_book_id, primary_source_id,
                aggregate_payload_json, status, ai_enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'active', 1, datetime('now'), datetime('now'))""",
            (
                book_id,
                payload.get("name", ""),
                payload.get("author", ""),
                f"{primary_source_id}:{book_id}",
                primary_source_id,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()


def _insert_chapter(
    db_path: Path,
    book_id: str,
    index: int = 1,
    *,
    source_chapter_id: str | None = None,
    title: str = "第一章",
    status: str = "pending",
) -> str:
    ch_id = f"{book_id}:ch{index}"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO aggregate_chapter_tasks
               (chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title, status,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
            (
                ch_id,
                book_id,
                source_chapter_id or f"official_src:ch{index}",
                index,
                title,
                status,
            ),
        )
        conn.commit()
    return ch_id


def _chapter_dict(ch_id: str, book_id: str, index: int = 1) -> dict[str, Any]:
    return {
        "chapterId": ch_id,
        "sourceChapterId": f"official_src:ch{index}",
        "title": f"第{index}章",
        "chapterIndex": index,
        "aggregateBookId": book_id,
    }


def _get_chapter_row(db_path: Path, ch_id: str) -> dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT status, processed_content, source_alignment_json FROM aggregate_chapter_tasks "
            "WHERE chapter_id = ?",
            (ch_id,),
        ).fetchone()
    if not row:
        return {"status": "", "content": "", "alignment": {}}
    alignment = {}
    try:
        alignment = json.loads(row[2] or "{}")
    except Exception:
        pass
    return {"status": row[0], "content": row[1] or "", "alignment": alignment}


# ── fakes ────────────────────────────────────────────────────────────────────


class _FakeAIService:
    """Records calls and returns canned results for real-sample tests."""

    def __init__(self, *, content: str = "", self_score: float = 1.0):
        self._content = content
        self._self_score = self_score
        self.calls: list[dict] = []

    async def process_official_full(self, **kwargs):
        self.calls.append({"method": "official_full", **kwargs})
        return {
            "status": "processed",
            "content": self._content,
            "selfScore": self._self_score,
            "aiModel": "fake-official",
            "promptTokens": 100,
            "completionTokens": 50,
            "totalTokens": 150,
            "latencyMs": 10,
            "plannedAnalysis": True,
        }

    async def process_with_candidates(self, **kwargs):
        self.calls.append({"method": "with_candidates", **kwargs})
        return {
            "status": "processed",
            "content": self._content,
            "selfScore": self._self_score,
            "aiModel": "fake-candidate",
            "promptTokens": 200,
            "completionTokens": 100,
            "totalTokens": 300,
            "latencyMs": 20,
            "plannedAnalysis": False,
        }

    async def process_third_party_primary(self, **kwargs):
        self.calls.append({"method": "third_party_primary", **kwargs})
        return {
            "status": "processed",
            "content": self._content,
            "selfScore": self._self_score,
            "aiModel": "fake-tp",
            "promptTokens": 200,
            "completionTokens": 100,
            "totalTokens": 300,
            "latencyMs": 20,
            "plannedAnalysis": False,
        }


# ── 1. masked/blocked-word detection ─────────────────────────────────────────


def test_lexicon_detects_mask_variants_in_real_chapter(novel_sample_dir: Path):
    """The sensitive-word scanner must catch * / □ / x / space masks inside real prose."""
    from app.ai.lexicon import SensitiveLexiconScanner

    text = _load_chapter_texts(novel_sample_dir, count=1)[0]
    scanner = SensitiveLexiconScanner.from_word_list(["血腥", "暴力", "杀戮", "死亡"])

    # Inject masked variants into real prose.
    injected = (
        text[:200]
        + "空气中弥漫着血*腥的味道，这是一场暴□力的冲突，"
        + "杀x戮从未停止，死亡的阴影笼罩四周。"
        + text[200:400]
    )

    candidates = scanner.scan(injected)
    masked_texts = [c.masked_text for c in candidates]

    assert masked_texts, "Expected masked-word candidates in injected real text"
    assert any("血*腥" in mt for mt in masked_texts), "Expected 血*腥 detection"
    assert any("暴□力" in mt for mt in masked_texts), "Expected 暴□力 detection"


# ── 2. ad / watermark / duplicate-title cleanup ──────────────────────────────


def test_purify_removes_ad_watermark_and_duplicate_title(novel_sample_dir: Path, tmp_path: Path):
    """Aggressive purify must strip ad watermarks and repeated title lines."""
    text = _load_chapter_texts(novel_sample_dir, count=1)[0]
    title = "第一章 绯红"
    contaminated = (
        f"{title}\n\n{text[:500]}\n\n"
        "【小说网】最新网址：www.example.com\n"
        f"{text[500:1000]}\n\n{title}\n\n{text[1000:1500]}"
    )

    aggressive_path = tmp_path / "aggressive.db"
    _setup_db(aggressive_path, purify="aggressive")
    processor_aggressive = AggregateProcessor(aggressive_path)
    cleaned = processor_aggressive._purify_content(contaminated)

    assert "最新网址" not in cleaned, "Aggressive purify should remove ad watermark"
    # Duplicate title lines should be collapsed/normalized by whitespace rules.
    assert cleaned.count(title) <= 1, "Duplicate title should be collapsed"

    conservative_path = tmp_path / "conservative.db"
    _setup_db(conservative_path, purify="conservative")
    processor_conservative = AggregateProcessor(conservative_path)
    conservative = processor_conservative._purify_content(contaminated)
    # Conservative mode intentionally keeps ad lines; verify it at least normalizes whitespace.
    assert "\n\n\n\n" not in conservative


# ── 3. paragraph recovery / whitespace normalization ─────────────────────────


def test_paragraph_recovery_compresses_excessive_blank_lines(novel_sample_dir: Path, tmp_path: Path):
    """Purify should recover reasonable paragraph spacing even from badly formatted source text."""
    text = _load_chapter_texts(novel_sample_dir, count=1)[0]
    broken = text.replace("\n\n", "\n\n\n\n\n\n")

    db_path = tmp_path / "para.db"
    _setup_db(db_path, purify="conservative")
    processor = AggregateProcessor(db_path)
    cleaned = processor._purify_content(broken)

    assert "\n\n\n\n" not in cleaned, "Excessive blank lines should be compressed"
    assert len(cleaned) < len(broken), "Cleaned text should be shorter after blank-line compression"


# ── 4. multi-source preview + candidate aggregation ──────────────────────────


def test_preview_plus_candidate_aggregates_real_chapter(
    novel_sample_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Official preview + aligned candidate built from a real chapter → AI aggregation."""
    full_chapter = _load_chapter_texts(novel_sample_dir, count=1)[0]
    preview = full_chapter[:150]
    candidate = "【笔趣阁】最新网址：www.example.com\n\n" + full_chapter

    db_path = tmp_path / "preview.db"
    _setup_db(db_path, purify="aggressive")
    book_id = "book:guimi_preview"
    _insert_book(db_path, book_id)
    ch_id = _insert_chapter(db_path, book_id, index=1, title="第一章 绯红")

    real_candidate_id = encode_chapter_id("candidate_src", "https://c.example/1.html")

    class Catalog:
        async def chapter(self, chapter_id: str) -> dict:
            if chapter_id.startswith("official_src"):
                return {"content": preview, "title": "第一章 绯红"}
            if chapter_id == real_candidate_id:
                return {"content": candidate, "title": "第一章 绯红"}
            return {"content": "", "title": ""}

        async def toc(self, book_id: str) -> dict:
            return {
                "chapters": [
                    {
                        "chapterId": real_candidate_id,
                        "title": "第一章 绯红",
                        "index": 1,
                        "chapterUrl": "https://c.example/1.html",
                    }
                ]
            }

    ai_service = _FakeAIService(content=full_chapter)
    processor = AggregateProcessor(db_path, ai_service=ai_service)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    result = asyncio.run(
        processor._process_chapter(Catalog(), _chapter_dict(ch_id, book_id, index=1))
    )

    row = _get_chapter_row(db_path, ch_id)
    assert result["success"] is True
    assert row["status"] == "processed"
    assert row["alignment"]["selectedContentSource"] == "ai_aggregate_candidate"
    assert len(ai_service.calls) == 1
    assert ai_service.calls[0]["method"] == "with_candidates"
    assert len(ai_service.calls[0]["official_preview"]) > 0
    assert len(ai_service.calls[0]["candidate_content"]) > len(preview)


# ── 5. third-party candidate TOC window alignment / attribution ──────────────


def test_candidate_window_alignment_rejects_wrong_chapter(
    novel_sample_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """For target chapter N, candidate chapters N-1/N+1 must not be selected by mistake."""
    ch1, ch2 = _load_chapter_texts(novel_sample_dir, count=2)
    preview = ch2[:150]

    db_path = tmp_path / "window.db"
    _setup_db(db_path, purify="aggressive")
    book_id = "book:guimi_window"
    _insert_book(db_path, book_id)
    ch_id = _insert_chapter(db_path, book_id, index=2, title="第二章 情况")

    cand_urls = {
        1: "https://c.example/1.html",
        2: "https://c.example/2.html",
        3: "https://c.example/3.html",
    }
    cand_ids = {i: encode_chapter_id("candidate_src", url) for i, url in cand_urls.items()}
    cand_content = {1: ch1, 2: ch2, 3: ch1}  # ch3 is intentionally wrong for attribution check.

    class Catalog:
        async def chapter(self, chapter_id: str) -> dict:
            if chapter_id.startswith("official_src"):
                return {"content": preview, "title": "第二章 情况"}
            _, url = decode_chapter_id(chapter_id)
            for idx, u in cand_urls.items():
                if u == url:
                    return {"content": cand_content[idx], "title": f"第{idx}章"}
            return {"content": "", "title": ""}

        async def toc(self, book_id: str) -> dict:
            return {
                "chapters": [
                    {
                        "chapterId": cand_ids[i],
                        "title": f"第{i}章",
                        "index": i,
                        "chapterUrl": cand_urls[i],
                    }
                    for i in (1, 2, 3)
                ]
            }

    ai_service = _FakeAIService(content=ch2)
    processor = AggregateProcessor(db_path, ai_service=ai_service)
    monkeypatch.setattr(processor, "_is_official_source", lambda sid: sid == "official_src")

    result = asyncio.run(
        processor._process_chapter(Catalog(), _chapter_dict(ch_id, book_id, index=2))
    )

    row = _get_chapter_row(db_path, ch_id)
    assert result["success"] is True
    assert row["status"] == "processed"
    assert len(ai_service.calls) == 1
    call = ai_service.calls[0]
    assert call["method"] == "with_candidates"
    # The chosen candidate should be chapter 2 content, not chapter 1.
    assert call["candidate_content"] == ch2
    assert row["content"] == ch2


# ── 6. third-party primary source path with real sample ──────────────────────


def test_third_party_primary_processes_real_chapter(
    novel_sample_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A non-official primary source with full real-chapter content goes through attribution path."""
    full_chapter = _load_chapter_texts(novel_sample_dir, count=1)[0]

    db_path = tmp_path / "tp.db"
    _setup_db(db_path, purify="conservative")
    book_id = "book:guimi_tp"
    _insert_book(db_path, book_id, primary_source_id="third_src")
    ch_id = _insert_chapter(
        db_path, book_id, index=1, source_chapter_id="third_src:ch1", title="第一章 绯红"
    )

    class Catalog:
        async def chapter(self, chapter_id: str) -> dict:
            return {"content": full_chapter, "title": "第一章 绯红"}

        async def toc(self, book_id: str) -> dict:
            return {"chapters": []}

    ai_service = _FakeAIService(content=full_chapter)
    processor = AggregateProcessor(db_path, ai_service=ai_service)
    monkeypatch.setattr(processor, "_is_official_source", lambda _sid: False)

    result = asyncio.run(
        processor._process_chapter(
            Catalog(),
            {
                "chapterId": ch_id,
                "sourceChapterId": "third_src:ch1",
                "title": "第一章 绯红",
                "chapterIndex": 1,
                "aggregateBookId": book_id,
            },
        )
    )

    row = _get_chapter_row(db_path, ch_id)
    assert result["success"] is True
    assert row["status"] == "processed"
    assert row["alignment"]["selectedContentSource"] == "third_party_primary_ai"
    assert len(ai_service.calls) == 1
    assert ai_service.calls[0]["method"] == "third_party_primary"
    assert len(ai_service.calls[0]["content"]) >= len(full_chapter) * 0.9
