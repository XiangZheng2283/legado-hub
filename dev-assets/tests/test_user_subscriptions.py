"""Multi-user subscription ownership and progress controls."""

from __future__ import annotations

import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest

from app.services.library_books import LibraryBooksService
from app.services.subscription_search import SubscriptionSearchService
from app.services.user_auth import UserAuthService
from app.services.user_subscriptions import UserSubscriptionsService
from app.services.user_subscriptions import (
    SubscriptionLimitError,
    SubscriptionRateLimiter,
)
from app.storage.db import initialize_database


def _insert_book(db_path: Path, book_id: str = "book-1") -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO aggregate_book_tasks (
                aggregate_book_id, canonical_name, canonical_author, name, author,
                status, search_visibility_status, total_chapters, processed_chapters
            ) VALUES (?, 'book', 'author', 'Book', 'Author', 'active', 'visible', 10, 0)
            """,
            (book_id,),
        )
        conn.commit()


def test_two_users_keep_independent_subscription_settings(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    initialize_database(db)
    auth = UserAuthService(db)
    user_a = auth.create_user("reader-a", "password-a")
    user_b = auth.create_user("reader-b", "password-b")
    _insert_book(db)

    subscriptions = UserSubscriptionsService(db)
    sub_a, created_a = subscriptions.ensure(
        user_a["userId"], "book-1", start_chapter_index=3, auto_archive_on_complete=True
    )
    sub_b, created_b = subscriptions.ensure(
        user_b["userId"], "book-1", start_chapter_index=8, auto_archive_on_complete=False
    )

    assert created_a is True
    assert created_b is True
    assert sub_a["startChapterIndex"] == 3
    assert sub_b["startChapterIndex"] == 8
    assert sub_a["autoArchiveOnComplete"] is True
    assert sub_b["autoArchiveOnComplete"] is False

    subscriptions.update(user_a["userId"], "book-1", {"status": "paused"})
    assert subscriptions.get(user_a["userId"], "book-1")["status"] == "paused"
    assert subscriptions.get(user_b["userId"], "book-1")["status"] == "active"
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT status FROM aggregate_book_tasks WHERE aggregate_book_id = 'book-1'"
        ).fetchone() == ("active",)
        audit_actions = [
            row[0]
            for row in conn.execute(
                "SELECT action FROM audit_events WHERE actor_user_id = ? ORDER BY occurred_at",
                (user_a["userId"],),
            ).fetchall()
        ]
    assert audit_actions == ["subscription.create", "subscription.update"]


def test_completed_book_archives_only_opted_in_users_and_records_audit(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    initialize_database(db)
    auth = UserAuthService(db)
    user_a = auth.create_user("reader-a", "password-a")
    user_b = auth.create_user("reader-b", "password-b")
    _insert_book(db)
    subscriptions = UserSubscriptionsService(db)
    subscriptions.ensure(user_a["userId"], "book-1", auto_archive_on_complete=True)
    subscriptions.ensure(user_b["userId"], "book-1", auto_archive_on_complete=False)

    archived_count = subscriptions.archive_completed_for_book("book-1")

    assert archived_count == 1
    assert subscriptions.get(user_a["userId"], "book-1")["status"] == "archived"
    assert subscriptions.get(user_b["userId"], "book-1")["status"] == "active"
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT status FROM aggregate_book_tasks WHERE aggregate_book_id = 'book-1'"
        ).fetchone() == ("active",)
        audit = conn.execute(
            """
            SELECT actor_role, operation_type, before_json, after_json
            FROM aggregate_operation_logs
            WHERE aggregate_book_id = 'book-1'
              AND operation_type = 'subscription.auto_archive'
            """
        ).fetchone()
    assert audit is not None
    assert audit[0:2] == ("system", "subscription.auto_archive")
    assert '"status": "active"' in audit[2]
    assert '"status": "archived"' in audit[3]


def test_resubscribe_is_idempotent_and_restores_archived_relation(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    initialize_database(db)
    user = UserAuthService(db).create_user("reader", "password")
    _insert_book(db)
    subscriptions = UserSubscriptionsService(db)

    first, created = subscriptions.ensure(user["userId"], "book-1")
    second, created_again = subscriptions.ensure(
        user["userId"], "book-1", start_chapter_index=5, auto_archive_on_complete=False
    )
    subscriptions.update(user["userId"], "book-1", {"status": "archived"})
    restored, restored_created = subscriptions.ensure(user["userId"], "book-1")

    assert created is True
    assert created_again is False
    assert first["aggregateBookId"] == second["aggregateBookId"]
    assert second["startChapterIndex"] == 5
    assert restored_created is False
    assert restored["status"] == "active"


def test_concurrent_ensure_cannot_exceed_user_subscription_limit(tmp_path: Path, monkeypatch) -> None:
    from app.core.app_config import AppConfig

    db = tmp_path / "app.db"
    initialize_database(db)
    user = UserAuthService(db).create_user("reader", "password")
    _insert_book(db, "book-a")
    _insert_book(db, "book-b")
    limits = SimpleNamespace(max_active_per_user=1)
    monkeypatch.setattr(
        AppConfig,
        "get",
        classmethod(lambda _cls: SimpleNamespace(subscription=limits)),
    )
    subscriptions = UserSubscriptionsService(db)
    start = Barrier(2)

    def subscribe(book_id: str):
        start.wait()
        try:
            subscriptions.ensure(user["userId"], book_id)
            return "created"
        except SubscriptionLimitError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(subscribe, ("book-a", "book-b")))

    assert sorted(results) == ["created", "subscription_limit_reached"]
    with sqlite3.connect(db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM user_book_subscriptions WHERE user_id = ? AND status = 'active'",
            (user["userId"],),
        ).fetchone()[0]
    assert count == 1


def test_subscription_rate_limiter_is_scoped_by_user_action_and_window(monkeypatch) -> None:
    from app.core.app_config import AppConfig

    now = [100.0]
    limits = SimpleNamespace(
        rate_limit_window_seconds=60,
        search_rate_limit_per_window=2,
        create_rate_limit_per_window=1,
        update_rate_limit_per_window=1,
    )
    monkeypatch.setattr(
        AppConfig,
        "get",
        classmethod(lambda _cls: SimpleNamespace(subscription=limits)),
    )
    limiter = SubscriptionRateLimiter(clock=lambda: now[0])

    limiter.check("user-a", "search")
    limiter.check("user-a", "search")
    limiter.check("user-b", "search")
    limiter.check("user-a", "create")
    with pytest.raises(SubscriptionLimitError) as captured:
        limiter.check("user-a", "search")
    assert captured.value.code == "subscription_search_rate_limited"
    assert captured.value.retryable is True
    assert captured.value.retry_after_seconds == 60

    now[0] += 61
    limiter.check("user-a", "search")
    limiter.reset()
    limiter.check("user-a", "create")


@pytest.mark.asyncio
async def test_concurrent_users_share_one_new_book_record(tmp_path: Path, monkeypatch) -> None:
    import app.services.library_books as library_books_module

    db = tmp_path / "app.db"
    initialize_database(db)
    auth = UserAuthService(db)
    user_a = auth.create_user("reader-a", "password-a")
    user_b = auth.create_user("reader-b", "password-b")
    service = LibraryBooksService(db_path=db)
    subscriptions = UserSubscriptionsService(db)
    group = {
        "candidateId": "candidate-1",
        "name": "Concurrent Book",
        "author": "Author",
        "items": [
            {
                "sourceId": "source-a",
                "sourceName": "Source A",
                "rawBookUrl": "https://example.com/book/1",
                "bookUrl": "https://example.com/book/1",
                "name": "Concurrent Book",
                "author": "Author",
                "score": 100,
            }
        ],
    }
    monkeypatch.setattr(service, "_plugins", lambda: {})
    monkeypatch.setattr(
        service,
        "_merged_book_settings",
        lambda: {"updateIntervalMinutes": 60, "aiAggregateEnabled": False},
    )
    monkeypatch.setattr(
        library_books_module,
        "primary_book_id_from_payload",
        lambda payload, **_kwargs: payload["sources"][0]["bookId"],
    )
    arrivals = 0
    release_hydration = asyncio.Event()

    async def hydrate(payload, primary_book_id, primary_source_id, primary_source):
        nonlocal arrivals
        arrivals += 1
        if arrivals == 2:
            release_hydration.set()
        await release_hydration.wait()
        return {
            **payload,
            "primaryBookId": primary_book_id,
            "primarySourceId": primary_source_id,
            "primarySourceName": primary_source.get("sourceName", ""),
            "primaryBookUrl": primary_source.get("bookUrl", ""),
            "primaryTocUrl": primary_source.get("tocUrl", ""),
        }

    monkeypatch.setattr(service, "_hydrate_primary_source_payload", hydrate)

    async def create_or_recover(user_id: str):
        try:
            return await service.create_or_get_shared_book(group, actor_user_id=user_id)
        except sqlite3.IntegrityError:
            raced = service.find_existing_book(group)
            assert raced is not None
            return {"created": False, "book": raced}

    results = await asyncio.gather(
        create_or_recover(user_a["userId"]),
        create_or_recover(user_b["userId"]),
    )
    for user, result in zip((user_a, user_b), results, strict=True):
        subscriptions.ensure(user["userId"], result["book"]["aggregateBookId"])

    assert sorted(result["created"] for result in results) == [False, True]
    assert results[0]["book"]["aggregateBookId"] == results[1]["book"]["aggregateBookId"]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM aggregate_book_tasks").fetchone() == (1,)
        assert conn.execute("SELECT COUNT(*) FROM aggregate_book_sources").fetchone() == (1,)
        assert conn.execute("SELECT COUNT(*) FROM user_book_subscriptions").fetchone() == (2,)
        assert conn.execute(
            "SELECT COUNT(*) FROM audit_events WHERE action = 'shared_book.create'"
        ).fetchone() == (1,)


@pytest.mark.asyncio
async def test_new_shared_book_creation_is_serialized(monkeypatch) -> None:
    import app.api.subscribe as subscribe_api

    monkeypatch.setattr(subscribe_api, "_shared_book_creation_lock", Lock())
    monkeypatch.setattr(
        subscribe_api.auth_service,
        "require_user",
        lambda _request: SimpleNamespace(user_id="user-1", role="user"),
    )
    monkeypatch.setattr(subscribe_api.subscription_rate_limiter, "check", lambda *_args: None)
    monkeypatch.setattr(
        subscribe_api.subscription_search_service,
        "find_card_group_for_user",
        lambda _job_id, candidate_id, _user_id: {"candidateId": candidate_id},
    )
    monkeypatch.setattr(
        subscribe_api.library_books_service,
        "find_existing_book",
        lambda _group: None,
    )
    monkeypatch.setattr(
        subscribe_api.user_subscriptions_service,
        "check_capacity",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        subscribe_api.user_subscriptions_service,
        "ensure",
        lambda user_id, book_id, **_kwargs: (
            {
                "userId": user_id,
                "aggregateBookId": book_id,
                "status": "active",
                "startChapterIndex": 1,
                "autoArchiveOnComplete": True,
            },
            True,
        ),
    )
    active_creations = 0
    max_active_creations = 0

    async def create_book(group, *, actor_user_id):
        nonlocal active_creations, max_active_creations
        active_creations += 1
        max_active_creations = max(max_active_creations, active_creations)
        await asyncio.sleep(0.02)
        active_creations -= 1
        return {
            "created": False,
            "book": {
                "aggregateBookId": f"book-{group['candidateId']}",
                "name": group["candidateId"],
                "author": "Author",
            },
        }

    monkeypatch.setattr(
        subscribe_api.library_books_service,
        "create_or_get_shared_book",
        create_book,
    )

    await asyncio.gather(
        subscribe_api.subscribe_candidate(object(), "job", "a"),
        subscribe_api.subscribe_candidate(object(), "job", "b"),
    )

    assert max_active_creations == 1


def test_shared_book_creation_guard_works_across_event_loops(monkeypatch) -> None:
    import app.api.subscribe as subscribe_api

    monkeypatch.setattr(subscribe_api, "_shared_book_creation_lock", Lock())
    counter_lock = Lock()
    active = 0
    max_active = 0

    async def guarded_work():
        nonlocal active, max_active
        async with subscribe_api._shared_book_creation_guard():
            with counter_lock:
                active += 1
                max_active = max(max_active, active)
            await asyncio.sleep(0.03)
            with counter_lock:
                active -= 1

    def run_in_loop(_index: int):
        asyncio.run(guarded_work())

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(run_in_loop, range(2)))

    assert max_active == 1


def test_my_library_is_relationship_scoped(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    initialize_database(db)
    auth = UserAuthService(db)
    user_a = auth.create_user("reader-a", "password-a")
    user_b = auth.create_user("reader-b", "password-b")
    _insert_book(db, "book-a")
    _insert_book(db, "book-b")
    subscriptions = UserSubscriptionsService(db)
    subscriptions.ensure(user_a["userId"], "book-a")
    subscriptions.ensure(user_b["userId"], "book-b")
    library = LibraryBooksService(db_path=db)

    books_a = subscriptions.list_books(user_a["userId"], library)
    books_b = subscriptions.list_books(user_b["userId"], library)

    assert [book["aggregateBookId"] for book in books_a] == ["book-a"]
    assert [book["aggregateBookId"] for book in books_b] == ["book-b"]
    assert books_a[0]["subscription"]["userId"] == user_a["userId"]


class _NoOfficialScheduler:
    def _enabled_plugins(self):
        return []

    def _search_priority_plugins(self, plugins):
        return plugins


def test_subscription_search_jobs_are_owner_scoped(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    initialize_database(db)
    service = SubscriptionSearchService(
        scheduler=_NoOfficialScheduler(),
        library_service=LibraryBooksService(db_path=db),
        subscription_service=UserSubscriptionsService(db_path=db),
    )

    job = service.create_job("Book", owner_user_id="user-a")

    assert service.get_job_for_user(job.job_id, "user-a") is job
    assert service.get_job_for_user(job.job_id, "user-b") is None
