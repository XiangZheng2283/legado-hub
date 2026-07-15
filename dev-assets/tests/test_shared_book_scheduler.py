from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services.shared_book_scheduler import SharedBookScheduler


class FakeProcessor:
    def __init__(self):
        self.run_calls: list[str] = []
        self.run_call_limits: list[int | None] = []
        self.bootstrap_calls: list[str] = []
        self.due_books: list[dict[str, object]] = []
        self.list_due_books_calls = 0
        self._books: dict[str, dict[str, str]] = {}
        self.pending_counts: dict[str, int] = {}

    def list_due_books(self, limit: int = 10) -> list[dict[str, object]]:
        self.list_due_books_calls += 1
        return list(self.due_books[:limit])

    async def run_book_task(self, aggregate_book_id: str, chapter_limit: int | None = None) -> dict[str, object]:
        self.run_calls.append(aggregate_book_id)
        self.run_call_limits.append(chapter_limit)
        await asyncio.sleep(0)
        return {"bookId": aggregate_book_id, "success": True}

    async def bootstrap_book_until_visible(self, aggregate_book_id: str, max_rounds: int = 20) -> dict[str, object]:
        self.bootstrap_calls.append(aggregate_book_id)
        await asyncio.sleep(0)
        return {"bookId": aggregate_book_id, "success": True, "visible": True}

    def _library_books(self):
        return self

    def get_book(self, aggregate_book_id: str) -> dict[str, str] | None:
        return self._books.get(aggregate_book_id)

    def _pending_chapter_count(self, aggregate_book_id: str) -> int:
        return int(self.pending_counts.get(aggregate_book_id, 0))

    def backlog_chapter_limit(self, aggregate_book_id: str) -> int:
        return 25


class FakeLockService:
    def __init__(self):
        self.active: set[tuple[str, str]] = set()
        self.acquire_calls: list[tuple[str, str]] = []

    def acquire(self, *, book_name: str, author: str):
        key = (book_name, author)
        self.acquire_calls.append(key)
        if key in self.active:
            return None
        self.active.add(key)
        return _FakeLease(self, key)


class _FakeLease:
    def __init__(self, service: FakeLockService, key: tuple[str, str]):
        self._service = service
        self._key = key

    def release(self) -> None:
        self._service.active.discard(self._key)

    @property
    def renewal_interval_seconds(self) -> float:
        return 60.0

    def renew(self) -> bool:
        return True


class FakeLibraryBooks:
    def __init__(self):
        self._states: dict[str, dict[str, object]] = {}

    def source_map_refresh_state(self, aggregate_book_id: str) -> dict[str, object]:
        return dict(self._states.get(aggregate_book_id, {}))

    def mark_completed(self, aggregate_book_id: str) -> None:
        self._states[aggregate_book_id] = {
            "completed": True,
            "lastVerifiedAt": "2026-06-27T00:00:00+08:00",
            "status": "healthy",
            "missingCriticalSource": False,
        }


class FakeSourceMapService:
    def __init__(self):
        self.refresh_calls: list[tuple[str, dict[str, object] | None, bool]] = []
        self.library_books = FakeLibraryBooks()
        self.refresh_started = asyncio.Event()
        self.release_refresh = asyncio.Event()

    def should_refresh(self, aggregate_book_id: str, *, payload=None):
        state = self.library_books.source_map_refresh_state(aggregate_book_id)
        return (not bool(state.get("completed")), "missing_health")

    async def refresh_for_book(self, aggregate_book_id: str, *, payload=None, force: bool = False):
        self.refresh_calls.append((aggregate_book_id, payload, force))
        self.refresh_started.set()
        await self.release_refresh.wait()
        self.library_books.mark_completed(aggregate_book_id)
        return {
            "bookId": aggregate_book_id,
            "success": True,
            "refreshed": True,
        }


@pytest.mark.asyncio
async def test_startup_recovery_runs_before_periodic_loop():
    events: list[str] = []
    processor = FakeProcessor()
    processor.due_books = [
        {"aggregateBookId": "book-recover", "payload": {"name": "恢复书", "author": "作者甲"}},
        {"aggregateBookId": "book-periodic", "payload": {"name": "周期书", "author": "作者乙"}},
    ]

    def recovery_scanner() -> list[dict[str, object]]:
        events.append("recovery_scan")
        return [
            {"aggregateBookId": "book-recover", "payload": {"name": "恢复书", "author": "作者甲"}},
        ]

    scheduler = SharedBookScheduler(
        processor=processor,
        lock_service=FakeLockService(),
        recovery_scanner=recovery_scanner,
    )

    original_process_book = scheduler._process_book

    async def instrumented_process_book(aggregate_book_id: str, *, trigger: str, payload=None):
        events.append(f"{trigger}:{aggregate_book_id}")
        return await original_process_book(aggregate_book_id, trigger=trigger, payload=payload)

    scheduler._process_book = instrumented_process_book

    recovery_result = await scheduler.startup_recovery_scan()
    periodic_result = await scheduler.run_periodic_once(wait_for_recovery=True)

    assert recovery_result["processedBooks"] == 1
    assert periodic_result["processedBooks"] == 1
    assert periodic_result["skippedStartupRecoveryProcessedBooks"] == 1
    assert events[:2] == [
        "recovery_scan",
        "startup_recovery_scan:book-recover",
    ]
    assert "book_update_check:book-periodic" in events
    assert "book_update_check:book-recover" not in events
    assert processor.run_calls == ["book-recover", "book-periodic"]


@pytest.mark.asyncio
async def test_periodic_loop_waits_for_recovery_completion():
    processor = FakeProcessor()
    processor.due_books = [
        {"aggregateBookId": "book-periodic", "payload": {"name": "周期书", "author": "作者甲"}},
    ]
    recovery_started = asyncio.Event()
    release_recovery = asyncio.Event()

    def recovery_scanner() -> list[dict[str, object]]:
        return [
            {"aggregateBookId": "book-recover", "payload": {"name": "恢复书", "author": "作者乙"}},
        ]

    scheduler = SharedBookScheduler(
        processor=processor,
        lock_service=FakeLockService(),
        recovery_scanner=recovery_scanner,
    )

    original_process_book = scheduler._process_book

    async def instrumented_process_book(aggregate_book_id: str, *, trigger: str, payload=None):
        if trigger == "startup_recovery_scan":
            recovery_started.set()
            await release_recovery.wait()
        return await original_process_book(aggregate_book_id, trigger=trigger, payload=payload)

    scheduler._process_book = instrumented_process_book

    recovery_task = asyncio.create_task(scheduler.startup_recovery_scan())
    await recovery_started.wait()

    periodic_task = asyncio.create_task(scheduler.run_periodic_once())
    await asyncio.sleep(0.05)
    assert periodic_task.done() is False

    release_recovery.set()
    await recovery_task
    periodic_result = await periodic_task

    assert periodic_result["processedBooks"] == 1
    assert processor.run_calls == ["book-recover", "book-periodic"]


@pytest.mark.asyncio
async def test_manual_reenqueue_allows_recovery_processed_book_to_run_again():
    processor = FakeProcessor()
    processor.due_books = [
        {"aggregateBookId": "book-recover", "payload": {"name": "恢复书", "author": "作者甲"}},
    ]
    scheduler = SharedBookScheduler(
        processor=processor,
        lock_service=FakeLockService(),
        recovery_scanner=lambda: [
            {"aggregateBookId": "book-recover", "payload": {"name": "恢复书", "author": "作者甲"}},
        ],
    )

    await scheduler.startup_recovery_scan()
    enqueue_result = scheduler.enqueue_manual_update("book-recover", book_name="恢复书", author="作者甲")
    periodic_result = await scheduler.run_periodic_once(wait_for_recovery=True)

    assert enqueue_result["queued"] is True
    assert periodic_result["processedBooks"] == 1
    assert periodic_result["skippedStartupRecoveryProcessedBooks"] == 0
    assert processor.run_calls == ["book-recover", "book-recover"]


@pytest.mark.asyncio
async def test_initial_subscription_runs_source_map_refresh_before_bootstrap():
    processor = FakeProcessor()
    source_map_service = FakeSourceMapService()
    scheduler = SharedBookScheduler(
        processor=processor,
        lock_service=FakeLockService(),
        recovery_scanner=lambda: [],
        source_map_service=source_map_service,
    )
    scheduler._recovery_complete.set()

    enqueue_result = scheduler.enqueue_initial_subscription(
        "book-subscribe",
        payload={"name": "订阅书", "author": "作者甲"},
        book_name="订阅书",
        author="作者甲",
    )
    periodic_task = asyncio.create_task(
        scheduler.run_periodic_once(wait_for_recovery=True, include_due_books=False)
    )

    await source_map_service.refresh_started.wait()
    await asyncio.sleep(0.05)
    assert processor.bootstrap_calls == []

    source_map_service.release_refresh.set()
    periodic_result = await periodic_task

    assert enqueue_result["queued"] is True
    assert [item["trigger"] for item in periodic_result["items"]] == [
        "book_source_map_refresh",
        "book_bootstrap",
    ]
    assert processor.bootstrap_calls == ["book-subscribe"]
    assert periodic_result["deferredBootstrapBooks"] == 0


@pytest.mark.asyncio
async def test_bootstrap_is_deferred_until_source_map_completion():
    processor = FakeProcessor()
    source_map_service = FakeSourceMapService()
    scheduler = SharedBookScheduler(
        processor=processor,
        lock_service=FakeLockService(),
        recovery_scanner=lambda: [],
        source_map_service=source_map_service,
    )
    scheduler._recovery_complete.set()
    scheduler._initial_source_map_pending_books.add("book-subscribe")
    scheduler.enqueue_manual_update(
        "book-subscribe",
        reason="book_bootstrap",
        payload={"name": "订阅书", "author": "作者甲"},
        book_name="订阅书",
        author="作者甲",
    )

    first_result = await scheduler.run_periodic_once(wait_for_recovery=True, include_due_books=False)

    assert first_result["processedBooks"] == 0
    assert first_result["deferredBootstrapBooks"] == 1
    assert processor.bootstrap_calls == []

    scheduler.enqueue_manual_update(
        "book-subscribe",
        reason="book_source_map_refresh",
        payload={"name": "订阅书", "author": "作者甲"},
        book_name="订阅书",
        author="作者甲",
    )
    source_map_service.release_refresh.set()
    second_result = await scheduler.run_periodic_once(wait_for_recovery=True, include_due_books=False)
    third_result = await scheduler.run_periodic_once(wait_for_recovery=True, include_due_books=False)

    assert [item["trigger"] for item in second_result["items"]] == ["book_source_map_refresh"]
    assert third_result["processedBooks"] == 1
    assert [item["trigger"] for item in third_result["items"]] == ["book_bootstrap"]
    assert processor.bootstrap_calls == ["book-subscribe"]


@pytest.mark.asyncio
async def test_periodic_pass_skips_books_already_in_recovery_queue():
    processor = FakeProcessor()
    processor.due_books = [
        {"aggregateBookId": "book-recover", "payload": {"name": "恢复书", "author": "作者甲"}},
        {"aggregateBookId": "book-other", "payload": {"name": "其他书", "author": "作者乙"}},
    ]
    scheduler = SharedBookScheduler(
        processor=processor,
        lock_service=FakeLockService(),
        recovery_scanner=lambda: [],
    )

    scheduler._recovery_complete.set()
    scheduler.enqueue_recovery_book("book-recover", book_name="恢复书", author="作者甲")

    result = await scheduler.run_periodic_once(wait_for_recovery=True)

    assert result["skippedRecoveryBooks"] == 1
    assert result["processedBooks"] == 1
    assert processor.run_calls == ["book-other"]


@pytest.mark.asyncio
async def test_per_book_mutual_exclusion_still_applies():
    processor = FakeProcessor()
    processor._books["book-1"] = {"aggregateBookId": "book-1", "name": "同一本书", "author": "作者甲"}
    lock_service = FakeLockService()
    scheduler = SharedBookScheduler(
        processor=processor,
        lock_service=lock_service,
        recovery_scanner=lambda: [],
    )

    busy_lease = lock_service.acquire(book_name="同一本书", author="作者甲")
    assert busy_lease is not None

    result = await scheduler._process_book("book-1", trigger="book_update_check")

    assert result["skipped"] is True
    assert result["reason"] == "lock_busy"
    assert processor.run_calls == []
    busy_lease.release()


@pytest.mark.asyncio
async def test_update_check_uses_backlog_window_when_pending_chapters_exist():
    processor = FakeProcessor()
    processor._books["book-backlog"] = {"aggregateBookId": "book-backlog", "name": "积压书", "author": "作者甲"}
    processor.pending_counts["book-backlog"] = 120
    scheduler = SharedBookScheduler(
        processor=processor,
        lock_service=FakeLockService(),
        recovery_scanner=lambda: [],
    )

    result = await scheduler._process_book("book-backlog", trigger="book_update_check")

    assert result["success"] is True
    assert processor.run_calls == ["book-backlog"]
    assert processor.run_call_limits == [25]


@pytest.mark.asyncio
async def test_initial_subscription_jobs_requeue_when_lock_busy():
    processor = FakeProcessor()
    processor._books["book-locked"] = {"aggregateBookId": "book-locked", "name": "锁中书", "author": "作者甲"}
    lock_service = FakeLockService()
    scheduler = SharedBookScheduler(
        processor=processor,
        lock_service=lock_service,
        recovery_scanner=lambda: [],
    )

    busy_lease = lock_service.acquire(book_name="锁中书", author="作者甲")
    assert busy_lease is not None

    result = await scheduler._process_book("book-locked", trigger="book_bootstrap")

    assert result["skipped"] is True
    assert result["reason"] == "lock_busy"
    assert processor.bootstrap_calls == []
    assert len(scheduler._manual_queue) == 1
    assert scheduler._manual_queue[0][0] == "book-locked"
    assert scheduler._manual_queue[0][1] == "book_bootstrap"
    busy_lease.release()


@pytest.mark.asyncio
async def test_main_lifespan_starts_shared_book_scheduler(monkeypatch):
    import app.main as main_module

    started: list[tuple[str, object]] = []

    class FakeScheduler:
        async def run_forever(self, stop_event):
            started.append(("scheduler", stop_event))
            await stop_event.wait()

    class FakePingScheduler:
        async def run_forever(self, stop_event):
            started.append(("ping", stop_event))
            await stop_event.wait()

    async def fake_update_lexicon_on_startup():
        started.append(("lexicon", None))

    class FakeAuthService:
        def ensure_default_admin(self):
            return None

    class FakeOfficialAuthManager:
        async def probe_saved_cookie_file(self, plugin_id: str):
            return None

    class FakeSearchJobService:
        def list_jobs(self, limit=500):
            return []

        def cancel_job(self, job_id):
            return None

    class FakeCookieStore:
        def list_plugin_ids(self):
            return []

    monkeypatch.setattr(main_module, "initialize_database", lambda: None)
    monkeypatch.setattr(main_module, "SharedBookScheduler", lambda: FakeScheduler())
    monkeypatch.setattr(main_module, "SourcePingScheduler", lambda: FakePingScheduler())
    monkeypatch.setattr(main_module, "_update_lexicon_on_startup", fake_update_lexicon_on_startup)

    import types

    monkeypatch.setitem(sys.modules, "app.services.user_auth", types.SimpleNamespace(auth_service=FakeAuthService()))
    monkeypatch.setitem(
        sys.modules,
        "app.services.official_auth.manager",
        types.SimpleNamespace(official_auth_manager=FakeOfficialAuthManager()),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.search_jobs",
        types.SimpleNamespace(SearchJobService=FakeSearchJobService),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.services.cookie_store",
        types.SimpleNamespace(
            migrate_legacy_plugin_cookies=lambda: None,
            CookieStore=FakeCookieStore,
        ),
    )
    async with main_module.lifespan(main_module.app):
        await asyncio.sleep(0)

    assert len(started) == 3
    assert started[0][0] == "scheduler"
    assert started[1][0] == "ping"
    assert started[2][0] == "lexicon"
