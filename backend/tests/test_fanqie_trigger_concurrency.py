from __future__ import annotations

import asyncio

from app.api.legado import _aggregate_to_fanqie_chapter
from app.services.aggregate_virtual_source import make_aggregate_chapter_url
from app.services.fanqie_local_trigger import _per_book_lock, ensure_fanqie_download_job
from app.services.reading_limits import _cpu_concurrency_slots
from app.source_plugins.id_codec import encode_chapter_id


def test_per_book_locks_are_distinct_across_books() -> None:
    """Different books must never share a lock (no global serialization)."""
    async def run() -> None:
        lock_a = await _per_book_lock("bookA")
        lock_b = await _per_book_lock("bookB")
        lock_a_again = await _per_book_lock("bookA")
        assert lock_a is lock_a_again  # same book -> same lock (idempotency)
        assert lock_a is not lock_b   # different books -> parallel

    asyncio.run(run())


def test_ensure_fanqie_download_job_rejects_empty_book_id() -> None:
    result = asyncio.run(ensure_fanqie_download_job(""))
    assert result == {"started": False, "job_id": None, "disposition": "error"}


def test_cpu_concurrency_scales_4x(monkeypatch) -> None:
    """4 cores -> 16 parallel slots (cpu * 4)."""
    monkeypatch.setattr("app.services.reading_limits.os.cpu_count", lambda: 4)
    assert _cpu_concurrency_slots() == 16


def test_reading_limit_concurrency_uses_scaled_slots() -> None:
    """The default limits must derive from the same CPU-scaled slot count."""
    from app.services.reading_limits import DEFAULT_READING_LIMITS, _cpu_concurrency_slots

    slots = _cpu_concurrency_slots()
    assert DEFAULT_READING_LIMITS["chapter"].max_concurrency == slots
    assert DEFAULT_READING_LIMITS["reviews"].max_concurrency == min(slots, 16)


def test_aggregate_fanqie_chapter_maps_back_to_fanqie_source() -> None:
    """A virtual/aggregate fanqie chapter must resolve to the source chapter_id
    so the reader can edge-serve from downloader OS files."""
    fanqie_chapter_id = encode_chapter_id(
        "fanqie_local", "http://127.0.0.1:18423/__fanqie__/7158058782700866560/3"
    )
    chapter_url = make_aggregate_chapter_url("aggr-1", fanqie_chapter_id, title="第三章", index=2)
    assert _aggregate_to_fanqie_chapter(chapter_url) == fanqie_chapter_id


def test_aggregate_non_fanqie_chapter_returns_none() -> None:
    other_chapter_id = encode_chapter_id("qidian_com_web", "https://m.qidian.com/book/123/456")
    chapter_url = make_aggregate_chapter_url("aggr-1", other_chapter_id)
    assert _aggregate_to_fanqie_chapter(chapter_url) is None
