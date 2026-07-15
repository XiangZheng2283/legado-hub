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
    monkeypatch.setattr("app.api.subscribe.library_books_service", service)
    monkeypatch.setattr("app.services.library_books.library_books_service", service)

    tc = TestClient(app)
    login = tc.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    if login.status_code != 200:
        pytest.skip(f"admin login unavailable: {login.status_code} {login.text}")
    return tc


def _insert_book(db_path: Path, aggregate_book_id: str, name: str, author: str) -> None:
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
        conn.commit()


def _write_shared_files(storage: SharedBookStorage, aggregate_book_id: str, name: str, author: str) -> None:
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
                "chapterCount": 2,
                "readableChapterCount": 2,
                "previewChapterCount": 0,
                "processedChapterCount": 2,
            },
        }
    )
    metadata["sourceMap"] = {
        "summary": metadata.get("sourceMapSummary", []),
        "health": {"lastVerifiedAt": "2026-06-26T00:00:00+00:00", "status": "healthy", "missingCriticalSource": False},
    }

    chapter_files = []
    chapter_entries = []
    for idx, title in [(1, "第一章"), (2, "第二章")]:
        ch_id = f"src:ch{idx}"
        trace = {
            "schemaVersion": 1,
            "chapterIndex": idx,
            "chapterTitle": title,
            "chapterStatus": "readable",
            "previewOnly": False,
            "primarySource": {"sourceId": "src", "chapterId": ch_id, "wordCount": 100},
        }
        markdown = storage.render_chapter_markdown(title=title, body=f"{title} 正文", trace_payload=trace)
        path = storage.chapter_markdown_path(book_name=name, author=author, chapter_index=idx, title=title)
        chapter_files.append((path, markdown))
        chapter_entries.append({"index": idx, "title": title, "file": f"chapters/{path.name}", "status": "readable", "sourceChapterId": ch_id})

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
    assert "bookState" in data
    assert data["bookState"]["readableChapterCount"] == 2

    sources = data.get("sources", [])
    assert len(sources) >= 1
    for source in sources:
        assert "bookUrl" not in source, "private source URLs must not be exposed"
        assert "tocUrl" not in source
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
        "find_card_group",
        lambda _job_id, _candidate_id: {"candidateId": "cand-1", "items": [{}]},
    )
    async def fake_create_or_get_shared_book(*args, **kwargs):
        return created_payload

    monkeypatch.setattr(
        subscribe_api.library_books_service,
        "create_or_get_shared_book",
        fake_create_or_get_shared_book,
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
    config = data["subscriptionConfig"]
    assert "primaryBookUrl" not in config
    assert "primaryTocUrl" not in config
