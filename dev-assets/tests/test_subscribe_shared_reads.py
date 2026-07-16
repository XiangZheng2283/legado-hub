"""Tests that /api/subscribe/books/* reads from shared files, not DB truth."""

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.main import app
from app.services.library_books import LibraryBooksService
from app.services.shared_book_storage import SharedBookStorage
from app.services.user_subscriptions import UserSubscriptionsService
from app.storage.db import initialize_database


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr("app.config.DB_PATH", db)
    monkeypatch.setattr("app.services.cache.DB_PATH", db)
    initialize_database(db)

    # Ensure shared storage writes under the temp directory.
    storage = SharedBookStorage(root=tmp_path / "library")
    service = LibraryBooksService(db_path=db, shared_book_storage=storage)
    subscription_service = UserSubscriptionsService(db_path=db)
    monkeypatch.setattr("app.api.subscribe.library_books_service", service)
    monkeypatch.setattr("app.api.legado.library_books_service", service)
    monkeypatch.setattr("app.api.subscribe.user_subscriptions_service", subscription_service)
    monkeypatch.setattr("app.services.library_books.library_books_service", service)

    tc = TestClient(app)
    login = tc.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    if login.status_code != 200:
        pytest.skip(f"admin login unavailable: {login.status_code} {login.text}")
    return tc


def _insert_book(
    db_path: Path,
    aggregate_book_id: str,
    name: str,
    author: str,
    *,
    published: bool = False,
    chapter_count: int = 0,
    visible_chapter_count: int = 0,
) -> None:
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO aggregate_book_tasks (
                aggregate_book_id, canonical_name, canonical_author, name, author,
                cover_url, intro, word_count, aggregate_payload_json, primary_book_id,
                primary_source_id, primary_source_name, primary_book_url, primary_toc_url,
                added_by_user_id, start_chapter_index, total_chapters_at_subscribe,
                initial_snapshot_last_index, backfill_started, auto_archive_on_complete,
                search_visibility_status, book_status, total_chapters, processed_chapters,
                visible_processed_chapters, failed_chapters, total_tokens, status,
                settings_json, current_policy_version, interval_minutes, last_check_time,
                next_check_time, error_count, last_error, ai_enabled, last_processed_at,
                archived_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, '', '', '', ?, 'src:book', 'src', 'src', '', '',
                      'user-1', 1, 10, 0, 0, 1, 'hidden', 'ongoing', 0, 0, 0, 0, 0, 'active',
                      '{}', 1, 60, NULL, NULL, 0, '', 1, NULL, NULL, datetime('now'), datetime('now'))
            """,
            (
                aggregate_book_id,
                name,
                author,
                name,
                author,
                json.dumps({"name": name, "author": author, "primarySourceId": "src"}, ensure_ascii=False),
            ),
        )
        if published:
            conn.execute(
                """
                UPDATE aggregate_book_tasks
                SET search_visibility_status = 'visible', total_chapters = ?,
                    processed_chapters = ?, visible_processed_chapters = ?
                WHERE aggregate_book_id = ?
                """,
                (chapter_count, chapter_count, visible_chapter_count, aggregate_book_id),
            )
        conn.commit()


def _write_shared_files(
    storage: SharedBookStorage,
    aggregate_book_id: str,
    name: str,
    author: str,
    *,
    chapter_specs: list[tuple[int, str, bool]] | None = None,
    include_source_ids: bool = True,
) -> None:
    specs = chapter_specs or [(1, "第一章", False), (2, "第二章", False)]
    preview_count = sum(1 for _, _, preview_only in specs if preview_only)
    metadata = storage.build_shared_metadata(
        {
            "name": name,
            "author": author,
            "primarySourceId": "src",
            "primarySourceName": "Src",
            "sources": [
                {
                    "sourceId": "src",
                    "sourceName": "Source",
                    "bookId": "src:book",
                    "bookUrl": "https://example.com/book",
                    "tocUrl": "https://example.com/toc",
                    "score": 100,
                }
            ],
            "bookState": {
                "chapterCount": len(specs),
                "readableChapterCount": len(specs),
                "previewChapterCount": preview_count,
                "processedChapterCount": len(specs),
            },
        }
    )
    metadata["sourceMap"] = {
        "summary": metadata.get("sourceMapSummary", []),
        "health": {"lastVerifiedAt": "2026-06-26T00:00:00+00:00", "status": "healthy", "missingCriticalSource": False},
    }

    chapter_files = []
    chapter_entries = []
    for idx, title, preview_only in specs:
        ch_id = f"src:ch{idx}"
        trace = {
            "schemaVersion": 1,
            "chapterIndex": idx,
            "chapterTitle": title,
            "chapterStatus": "readable",
            "previewOnly": preview_only,
            "isVip": preview_only,
            "primarySource": {"sourceId": "src", "chapterId": ch_id, "wordCount": 100},
        }
        body = f"{title} {'付费预览正文' if preview_only else '完整免费正文'}"
        markdown = storage.render_chapter_markdown(title=title, body=body, trace_payload=trace)
        path = storage.chapter_markdown_path(book_name=name, author=author, chapter_index=idx, title=title)
        chapter_files.append((path, markdown))
        chapter_entries.append(
            {
                "index": idx,
                "title": title,
                "file": f"chapters/{path.name}",
                "status": "readable",
                "sourceChapterId": ch_id if include_source_ids else "",
                "isVip": preview_only,
            }
        )

    chapter_index = {"schemaVersion": 1, "bookId": aggregate_book_id, "chapters": chapter_entries}
    storage.write_book_bundle(
        metadata_path=storage.metadata_path(book_name=name, author=author),
        metadata_payload=metadata,
        chapter_index_path=storage.chapter_index_path(book_name=name, author=author),
        chapter_index_payload=chapter_index,
        chapter_files=chapter_files,
    )


def test_get_library_book_reads_shared_metadata_not_db_sources(client, tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    storage = SharedBookStorage(root=tmp_path / "library")
    service = LibraryBooksService(db_path=db, shared_book_storage=storage)
    monkeypatch.setattr("app.api.subscribe.library_books_service", service)

    book_id = "book-shared-read-1"
    _insert_book(db, book_id, "测试书", "作者")
    _write_shared_files(storage, book_id, "测试书", "作者")

    response = client.get(f"/api/subscribe/books/{book_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["found"] is True
    assert data["book"]["aggregateBookId"] == book_id
    assert "primaryBookUrl" not in data["book"]
    assert "primaryTocUrl" not in data["book"]
    assert "settingsJson" not in data["book"]
    assert "addedByUserId" not in data["book"]
    assert "bookState" in data
    assert data["bookState"]["readableChapterCount"] == 2

    assert "sources" not in data
    assert "sourceMap" not in data
    assert "sourceMapRefresh" not in data
    payload = data.get("payload")
    assert payload is None, "private payload must not be exposed to subscribe endpoint"


def test_list_library_book_chapters_reads_shared_files(client, tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    storage = SharedBookStorage(root=tmp_path / "library")
    service = LibraryBooksService(db_path=db, shared_book_storage=storage)
    monkeypatch.setattr("app.api.subscribe.library_books_service", service)

    book_id = "book-shared-read-2"
    _insert_book(db, book_id, "测试书二", "作者二")
    _write_shared_files(storage, book_id, "测试书二", "作者二")

    response = client.get(f"/api/subscribe/books/{book_id}/chapters")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    items = data["items"]
    assert len(items) == 2
    assert items[0]["chapterIndex"] == 1
    assert items[0]["hasContent"] is True
    assert items[0]["status"] == "readable"
    assert items[0]["readChapterId"].startswith("legadohub_ai_aggregate:"), f"readChapterId must be encoded aggregate ID, got: {items[0]['readChapterId']}"
    assert not items[0]["readChapterId"].isdigit(), "readChapterId must not be a numeric chapter index"
    assert "sourceChapterId" not in items[0]
    assert "primarySourceChapterUrl" not in items[0]
    assert "processed_content" not in items[0]

    filtered = client.get(
        f"/api/subscribe/books/{book_id}/chapters",
        params={"keyword": "第二"},
    )
    assert filtered.status_code == 200
    assert [item["title"] for item in filtered.json()["items"]] == ["第二章"]


def test_legado_reads_only_published_shared_content_without_db_side_effects(
    client, tmp_path, monkeypatch
):
    import sqlite3

    from app.core.legado_source import generate_legado_source
    from app.services.library_books import make_library_book_id

    db = tmp_path / "test.db"
    storage = SharedBookStorage(root=tmp_path / "library")
    service = LibraryBooksService(db_path=db, shared_book_storage=storage)
    monkeypatch.setattr("app.api.subscribe.library_books_service", service)
    monkeypatch.setattr("app.api.legado.library_books_service", service)

    hidden_id = "book-reading-hidden"
    published_id = "book-reading-published"
    _insert_book(db, hidden_id, "阅读契约测试书隐藏", "作者")
    _insert_book(
        db,
        published_id,
        "阅读契约测试书",
        "作者",
        published=True,
        chapter_count=4,
        visible_chapter_count=3,
    )
    _write_shared_files(
        storage,
        published_id,
        "阅读契约测试书",
        "作者",
        chapter_specs=[
            (1, "第一章", False),
            (2, "第二章", False),
            (3, "第三章", False),
            (4, "第四章 付费", True),
        ],
        include_source_ids=False,
    )
    from app.services.aggregate_virtual_source import (
        VIRTUAL_SOURCE_ID,
        make_aggregate_chapter_url,
    )
    from app.source_plugins.id_codec import encode_chapter_id

    with sqlite3.connect(db) as conn:
        for index, title in enumerate(("第一章", "第二章", "第三章", "第四章 付费"), start=1):
            source_chapter_id = f"src:ch{index}"
            aggregate_url = make_aggregate_chapter_url(
                aggregate_book_id=published_id,
                source_chapter_id=source_chapter_id,
                title=title,
                index=index,
            )
            conn.execute(
                """
                INSERT INTO aggregate_chapter_tasks (
                    chapter_id, aggregate_book_id, source_chapter_id,
                    chapter_index, title, status, preview_only
                ) VALUES (?, ?, ?, ?, ?, 'processed', ?)
                """,
                (
                    encode_chapter_id(VIRTUAL_SOURCE_ID, aggregate_url),
                    published_id,
                    source_chapter_id,
                    index,
                    title,
                    int(index == 4),
                ),
            )
        conn.commit()

    source = generate_legado_source("http://testserver")[0]
    assert source["searchUrl"].startswith("http://testserver/api/subscribe/legado/search")
    assert "waitMs" not in source["searchUrl"]
    assert source["exploreUrl"].startswith("已发布书库::http://testserver/api/subscribe/legado/explore")

    search = client.get("/api/subscribe/legado/search", params={"keyword": "阅读契约测试书"})
    assert search.status_code == 200
    search_data = search.json()
    assert search_data["status"] == "completed"
    assert search_data["jobId"] == ""
    assert [item["aggregateBookId"] for item in search_data["items"]] == [published_id]
    assert "addedByUserId" not in search_data["items"][0]
    assert "addedByUsername" not in search_data["items"][0]

    book_id = make_library_book_id(published_id)
    with sqlite3.connect(db) as conn:
        before = {
            "books": conn.execute("SELECT COUNT(*) FROM aggregate_book_tasks").fetchone()[0],
            "chapters": conn.execute("SELECT COUNT(*) FROM aggregate_chapter_tasks").fetchone()[0],
            "logs": conn.execute("SELECT COUNT(*) FROM aggregate_operation_logs").fetchone()[0],
        }

    detail = client.get(f"/api/legado/book/{book_id}")
    assert detail.status_code == 200
    detail_data = detail.json()["data"]
    assert detail_data["name"] == "阅读契约测试书"
    assert "primaryBookUrl" not in detail_data
    assert "sources" not in detail_data

    toc = client.get(f"/api/legado/book/{book_id}/toc")
    assert toc.status_code == 200
    chapters = toc.json()["chapters"]
    assert len(chapters) == 4
    assert chapters[0]["isVip"] is False
    assert chapters[0]["previewOnly"] is False
    assert chapters[-1]["isVip"] is True
    assert chapters[-1]["previewOnly"] is True

    free = client.get(chapters[0]["chapterUrl"].replace("http://testserver", ""))
    assert free.status_code == 200
    assert "完整免费正文" in free.json()["content"]
    assert free.json()["extra"]["contentAccess"] == "full"
    assert free.json()["isVip"] is False

    preview = client.get(chapters[-1]["chapterUrl"].replace("http://testserver", ""))
    assert preview.status_code == 200
    assert "付费预览正文" in preview.json()["content"]
    assert preview.json()["extra"]["contentAccess"] == "preview"
    assert preview.json()["isVip"] is True
    assert preview.json()["extra"]["previewOnly"] is True

    with sqlite3.connect(db) as conn:
        after = {
            "books": conn.execute("SELECT COUNT(*) FROM aggregate_book_tasks").fetchone()[0],
            "chapters": conn.execute("SELECT COUNT(*) FROM aggregate_chapter_tasks").fetchone()[0],
            "logs": conn.execute("SELECT COUNT(*) FROM aggregate_operation_logs").fetchone()[0],
        }
    assert after == before

    hidden_book_id = make_library_book_id(hidden_id)
    assert client.get(f"/api/legado/book/{hidden_book_id}").status_code == 404


def test_known_official_free_short_chapter_is_not_misclassified_as_preview():
    from app.services.aggregate_alignment import classify_source_content

    result = classify_source_content(
        "欢迎收藏本书",
        source_id="qidian_com_app",
        is_official=True,
        preview_only_hint=True,
        is_paid=True,
        is_vip=False,
    )

    assert result["classification"] == "full"


def test_subscribe_candidate_response_does_not_expose_private_primary_urls(client, monkeypatch):
    import app.api.subscribe as subscribe_api

    created_payload = {
        "created": True,
        "payload": {"name": "测试书", "author": "作者", "sources": []},
        "book": {
            "aggregateBookId": "book-new-1",
            "coverUrl": "",
            "name": "测试书",
            "author": "作者",
            "intro": "简介",
            "bookStatus": "ongoing",
            "totalChaptersAtSubscribe": 10,
            "startChapterIndex": 1,
            "autoArchiveOnComplete": True,
            "primarySourceId": "src",
            "primarySourceName": "来源",
            "primaryBookId": "src:book",
            "primaryBookUrl": "https://private.example/book",
            "primaryTocUrl": "https://private.example/toc",
            "settingsJson": "{}",
        },
    }

    monkeypatch.setattr(
        subscribe_api.subscription_search_service,
        "find_card_group_for_user",
        lambda _job_id, _candidate_id, _user_id: {"candidateId": "cand-1", "items": [{}]},
    )
    async def fake_create_or_get_shared_book(*args, **kwargs):
        return created_payload

    monkeypatch.setattr(
        subscribe_api.library_books_service,
        "create_or_get_shared_book",
        fake_create_or_get_shared_book,
    )
    monkeypatch.setattr(
        subscribe_api.library_books_service,
        "find_existing_book",
        lambda _group: None,
    )
    monkeypatch.setattr(
        subscribe_api.user_subscriptions_service,
        "check_capacity",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        subscribe_api.user_subscriptions_service,
        "ensure",
        lambda *args, **kwargs: (
            {
                "userId": "admin",
                "aggregateBookId": "book-new-1",
                "status": "active",
                "startChapterIndex": 1,
                "autoArchiveOnComplete": True,
                "createdAt": "",
                "updatedAt": "",
            },
            True,
        ),
    )
    monkeypatch.setattr(
        subscribe_api.AggregateProcessor,
        "enqueue_book",
        lambda self, aggregate_book_id, payload, **kwargs: {"queued": True, "bookId": aggregate_book_id},
    )
    monkeypatch.setattr(
        subscribe_api.SharedBookScheduler,
        "enqueue_initial_subscription",
        lambda self, aggregate_book_id, **kwargs: {"queued": True, "bookId": aggregate_book_id},
    )
    monkeypatch.setattr(
        subscribe_api.SharedBookScheduler,
        "run_periodic_once",
        lambda self, **kwargs: None,
    )
    monkeypatch.setattr(
        subscribe_api.asyncio,
        "create_task",
        lambda coro: None,
    )

    response = client.post(
        "/api/subscribe/search/job-1/cards/cand-1/subscribe",
        json={"startChapterIndex": 1, "autoArchiveOnComplete": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert "primaryBookUrl" not in data["book"]
    assert "primaryTocUrl" not in data["book"]
    assert "settingsJson" not in data["book"]
    config = data["subscriptionConfig"]
    assert "primaryBookUrl" not in config
    assert "primaryTocUrl" not in config
    assert "primarySourceId" not in config
    assert "primaryBookId" not in config
    assert "supplementSourceConfig" not in config


def test_reader_access_requires_own_subscription(client, tmp_path):
    import sqlite3

    from fastapi.testclient import TestClient

    import app.api.subscribe as subscribe_api
    from app.services.user_auth import auth_service

    db = tmp_path / "test.db"
    book_id = "book-owner-scope"
    _insert_book(db, book_id, "归属测试书", "作者")

    username = "reader-owner-scope"
    user = auth_service.get_user_by_username(username)
    if not user:
        user = auth_service.create_user(username, "reader-password", role="user")
    with sqlite3.connect(db) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO users (user_id, username, password_hash, role)
            VALUES (?, ?, 'test-hash', 'user')
            """,
            (user["userId"], username),
        )
        conn.commit()
    reader = TestClient(app)
    login = reader.post(
        "/api/auth/login",
        json={"username": username, "password": "reader-password"},
    )
    assert login.status_code == 200

    assert reader.get(f"/api/subscribe/books/{book_id}").status_code == 404
    assert reader.get("/api/subscribe/library").status_code == 403

    subscribe_api.user_subscriptions_service.ensure(user["userId"], book_id)
    response = reader.get(f"/api/subscribe/books/{book_id}")
    assert response.status_code == 200
    assert response.json()["subscription"]["userId"] == user["userId"]
    mine = reader.get("/api/subscribe/library/mine")
    assert mine.status_code == 200
    mine_book = mine.json()["items"][0]
    assert mine_book["aggregateBookId"] == book_id
    assert "primaryBookUrl" not in mine_book
    assert "primaryTocUrl" not in mine_book
    assert "settingsJson" not in mine_book
    assert "addedByUserId" not in mine_book
    assert reader.get(f"/api/console/library-books/{book_id}/summary").status_code == 403
    assert reader.get(f"/api/console/library-books/{book_id}/chapters").status_code == 403
    assert reader.get(f"/api/console/library-books/{book_id}/logs").status_code == 403
