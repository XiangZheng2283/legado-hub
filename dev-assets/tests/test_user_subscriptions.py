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
from app.services.live_acceptance import group_candidates
from app.services.subscription_search import (
    SubscriptionSearchJob,
    SubscriptionSearchService,
)
from app.services.user_auth import UserAuthService
from app.services.user_subscriptions import UserSubscriptionsService
from app.services.user_subscriptions import (
    SubscriptionLimitError,
    SubscriptionRateLimiter,
)
from app.source_plugins.id_codec import encode_book_id
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


def test_qidian_app_and_web_results_share_one_stable_candidate() -> None:
    app_item = {
        "sourceId": "qidian_com_app",
        "sourceName": "起点中文网(App)",
        "name": "测试作品",
        "author": "测试作者",
        "rawBookUrl": "https://m.qidian.com/book/123456/",
        "bookUrl": "http://127.0.0.1/api/legado/book/app-id",
    }
    web_item = {
        "sourceId": "qidian_com_web",
        "sourceName": "起点中文网(Web)",
        "name": "测试作品（Web）",
        "author": "测试作者 著",
        "rawBookUrl": "https://m.qidian.com/book/123456/",
        "bookUrl": "http://127.0.0.1/api/legado/book/web-id",
    }

    app_only = group_candidates([app_item], "测试作品")
    combined = group_candidates([app_item, web_item], "测试作品")

    assert len(combined) == 1
    assert combined[0]["sourceCount"] == 2
    assert combined[0]["candidateId"] == app_only[0]["candidateId"]
    assert {item["sourceId"] for item in combined[0]["items"]} == {
        "qidian_com_app",
        "qidian_com_web",
    }


def test_qidian_results_with_different_work_ids_remain_separate() -> None:
    common = {"name": "同名作品", "author": "同一作者"}
    groups = group_candidates(
        [
            {
                **common,
                "sourceId": "qidian_com_app",
                "rawBookUrl": "https://m.qidian.com/book/111111/",
            },
            {
                **common,
                "sourceId": "qidian_com_web",
                "rawBookUrl": "https://m.qidian.com/book/222222/",
            },
        ],
        "同名作品",
    )

    assert len(groups) == 2


def test_existing_qidian_book_matches_the_sibling_plugin(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    initialize_database(db)
    _insert_book(db)
    canonical_url = "https://m.qidian.com/book/123456/"
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            INSERT INTO aggregate_book_sources (
                aggregate_book_id, source_id, source_book_id, source_name, source_book_url
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "book-1",
                "qidian_com_app",
                encode_book_id("qidian_com_app", canonical_url),
                "起点中文网(App)",
                canonical_url,
            ),
        )
        conn.commit()

    service = LibraryBooksService(db_path=db)
    existing = service.find_existing_book(
        {
            "candidateId": "candidate-web",
            "name": "Book",
            "author": "Author",
            "items": [
                {
                    "sourceId": "qidian_com_web",
                    "sourceName": "起点中文网(Web)",
                    "name": "Book",
                    "author": "Author",
                    "rawBookUrl": canonical_url,
                }
            ],
        }
    )

    assert existing is not None
    assert existing["aggregateBookId"] == "book-1"


def test_discovery_readable_count_does_not_subtract_previews_twice(tmp_path: Path) -> None:
    service = LibraryBooksService(db_path=tmp_path / "app.db")

    assert service._discovery_readable_chapter_count(
        {
            "bookState": {
                "readableChapterCount": 640,
                "previewChapterCount": 19,
            }
        }
    ) == 640


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
    creator = next(
        user
        for user, result in zip((user_a, user_b), results, strict=True)
        if result["created"]
    )
    assert {result["book"]["addedByUserId"] for result in results} == {creator["userId"]}
    assert {result["book"]["addedByUsername"] for result in results} == {creator["username"]}
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM aggregate_book_tasks").fetchone() == (1,)
        assert conn.execute(
            "SELECT added_by_user_id FROM aggregate_book_tasks"
        ).fetchone() == (creator["userId"],)
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


class _OfficialSearchMetadata:
    id = "official-source"
    name = "官方源"
    priority = 1

    @staticmethod
    def is_official_source() -> bool:
        return True


class _OfficialSearchScheduler:
    config = {"max_concurrency": 1}

    def __init__(self):
        self.plugin = SimpleNamespace(
            metadata=_OfficialSearchMetadata(),
            capabilities=["search"],
        )

    def _enabled_plugins(self):
        return [self.plugin]

    def _search_priority_plugins(self, plugins):
        return plugins

    async def search_one(self, source_id: str, keyword: str, page: int):
        return {
            "items": [
                {
                    "sourceId": source_id,
                    "sourceName": "官方源",
                    "name": keyword,
                    "author": "作者",
                    "bookUrl": "https://example.test/book/1",
                    "rawBookUrl": "https://example.test/book/1",
                }
            ],
            "error": None,
        }


class _SearchCardLibrary:
    @staticmethod
    def build_subscription_card(group):
        return {
            "candidateId": group["candidateId"],
            "name": group["name"],
            "author": group.get("author", ""),
            "aggregateBookId": "",
        }


class _NoSubscriptions:
    @staticmethod
    def get(user_id: str, book_id: str):
        return None


def test_subscription_search_jobs_are_owner_scoped(tmp_path: Path) -> None:
    db = tmp_path / "app.db"
    initialize_database(db)
    auth = UserAuthService(db)
    user_a = auth.create_user("search-owner-a", "password-a")
    user_b = auth.create_user("search-owner-b", "password-b")
    service = SubscriptionSearchService(
        scheduler=_NoOfficialScheduler(),
        library_service=LibraryBooksService(db_path=db),
        subscription_service=UserSubscriptionsService(db_path=db),
        db_path=db,
    )

    job = service.create_job("Book", owner_user_id=user_a["userId"])

    assert service.get_job_for_user(job.job_id, user_a["userId"]) is job
    assert service.get_job_for_user(job.job_id, user_b["userId"]) is None


@pytest.mark.asyncio
async def test_completed_subscription_search_survives_service_restart(
    tmp_path: Path,
) -> None:
    db = tmp_path / "app.db"
    initialize_database(db)
    user = UserAuthService(db).create_user("search-reload", "password")
    service = SubscriptionSearchService(
        scheduler=_OfficialSearchScheduler(),
        library_service=_SearchCardLibrary(),
        subscription_service=_NoSubscriptions(),
        db_path=db,
    )

    job = service.create_job("持久化测试书", owner_user_id=user["userId"])
    while service.snapshot(job.job_id)["liveSearchPending"]:
        await asyncio.sleep(0.01)
    before = service.snapshot(job.job_id)
    assert "cardGroups" not in before
    assert "card_groups" not in before

    reloaded = SubscriptionSearchService(
        scheduler=_NoOfficialScheduler(),
        library_service=_SearchCardLibrary(),
        subscription_service=_NoSubscriptions(),
        db_path=db,
    )
    after = reloaded.snapshot(job.job_id)

    assert after["status"] == "completed"
    assert after["cards"] == before["cards"]
    assert "cardGroups" not in after
    assert "card_groups" not in after
    candidate_id = after["cards"][0]["candidateId"]
    assert reloaded.find_card_group_for_user(
        job.job_id, candidate_id, user["userId"]
    ) is not None
    assert reloaded.find_card_group_for_user(job.job_id, candidate_id, "other-user") is None


def test_running_subscription_search_becomes_interrupted_after_restart(
    tmp_path: Path,
) -> None:
    db = tmp_path / "app.db"
    initialize_database(db)
    user = UserAuthService(db).create_user("search-interrupted", "password")
    service = SubscriptionSearchService(
        scheduler=_NoOfficialScheduler(),
        library_service=_SearchCardLibrary(),
        subscription_service=_NoSubscriptions(),
        db_path=db,
    )
    job = SubscriptionSearchJob(
        job_id="interrupted-job",
        owner_user_id=user["userId"],
        keyword="中断测试",
        page=1,
        status="running",
        official_status="running",
        message="正在搜索官方源。",
    )
    service._persist_job(job)

    reloaded = SubscriptionSearchService(
        scheduler=_NoOfficialScheduler(),
        library_service=_SearchCardLibrary(),
        subscription_service=_NoSubscriptions(),
        db_path=db,
    )

    assert reloaded.recover_interrupted_jobs() == 1
    snapshot = reloaded.snapshot(job.job_id)
    assert snapshot["status"] == "interrupted"
    assert snapshot["officialStatus"] == "interrupted"
    assert snapshot["liveSearchPending"] is False
    assert snapshot["message"] == "服务重启，搜索任务已中断，请重新搜索。"
    assert snapshot["events"][-1]["type"] == "job_interrupted"


def test_subscription_search_loads_malformed_numeric_snapshot_safely(
    tmp_path: Path,
) -> None:
    db = tmp_path / "app.db"
    initialize_database(db)
    user = UserAuthService(db).create_user("search-damaged", "password")
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            INSERT INTO subscription_search_jobs (
                job_id, owner_user_id, keyword, page, status, payload_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, 1, 'running', ?, ?, ?)
            """,
            (
                "damaged-job",
                user["userId"],
                "损坏快照",
                '{"official_status":"running","success_count":"not-a-number"}',
                "not-a-timestamp",
                "not-a-timestamp",
            ),
        )
        conn.commit()

    service = SubscriptionSearchService(
        scheduler=_NoOfficialScheduler(),
        library_service=_SearchCardLibrary(),
        subscription_service=_NoSubscriptions(),
        db_path=db,
    )

    assert service.recover_interrupted_jobs() == 1
    snapshot = service.snapshot("damaged-job")
    assert snapshot["status"] == "interrupted"
    assert snapshot["progress"]["successCount"] == 0


def test_subscription_search_removes_unreadable_running_snapshot(
    tmp_path: Path,
) -> None:
    db = tmp_path / "app.db"
    initialize_database(db)
    user = UserAuthService(db).create_user("search-unreadable", "password")
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            INSERT INTO subscription_search_jobs (
                job_id, owner_user_id, keyword, page, status, payload_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, 1, 'running', ?, 1, 1)
            """,
            ("unreadable-job", user["userId"], "不可读快照", "{invalid-json"),
        )
        conn.commit()

    service = SubscriptionSearchService(
        scheduler=_NoOfficialScheduler(),
        library_service=_SearchCardLibrary(),
        subscription_service=_NoSubscriptions(),
        db_path=db,
    )

    assert service.recover_interrupted_jobs() == 0
    assert service.snapshot("unreadable-job")["status"] == "unknown"
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT 1 FROM subscription_search_jobs WHERE job_id = 'unreadable-job'"
        ).fetchone() is None


def test_subscription_search_rejects_stale_or_conflicting_snapshots(
    tmp_path: Path,
) -> None:
    db = tmp_path / "app.db"
    initialize_database(db)
    user = UserAuthService(db).create_user("search-stale", "password")
    service = SubscriptionSearchService(
        scheduler=_NoOfficialScheduler(),
        library_service=_SearchCardLibrary(),
        subscription_service=_NoSubscriptions(),
        db_path=db,
    )
    current = SubscriptionSearchJob(
        job_id="stale-job",
        owner_user_id=user["userId"],
        keyword="当前快照",
        page=1,
        status="completed",
        message="当前状态",
        created_at=100.0,
        updated_at=200.0,
    )
    stale = SubscriptionSearchJob(
        job_id="stale-job",
        owner_user_id=user["userId"],
        keyword="当前快照",
        page=1,
        status="running",
        message="旧状态",
        created_at=100.0,
        updated_at=150.0,
    )

    assert service._persist_job(current) is True
    assert service._persist_job(stale) is False
    reloaded = SubscriptionSearchService(
        scheduler=_NoOfficialScheduler(),
        library_service=_SearchCardLibrary(),
        subscription_service=_NoSubscriptions(),
        db_path=db,
    )
    snapshot = reloaded.snapshot("stale-job")
    assert snapshot["status"] == "completed"
    assert snapshot["message"] == "当前状态"


def test_subscription_search_creation_discards_memory_job_when_persistence_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db = tmp_path / "app.db"
    initialize_database(db)
    user = UserAuthService(db).create_user("search-write-failure", "password")
    service = SubscriptionSearchService(
        scheduler=_NoOfficialScheduler(),
        library_service=_SearchCardLibrary(),
        subscription_service=_NoSubscriptions(),
        db_path=db,
    )
    monkeypatch.setattr(
        service,
        "_persist_job",
        lambda _job: (_ for _ in ()).throw(sqlite3.OperationalError("disk unavailable")),
    )

    with pytest.raises(sqlite3.OperationalError, match="disk unavailable"):
        service.create_job("写入失败", owner_user_id=user["userId"])
    assert service._jobs == {}
