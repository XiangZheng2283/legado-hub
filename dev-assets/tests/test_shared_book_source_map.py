from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services.library_books import LibraryBooksService
from app.services.shared_book_scheduler import SharedBookScheduler
from app.services.shared_book_storage import SharedBookStorage
from app.storage.db import initialize_database


def _insert_book(
    db_path: Path,
    *,
    aggregate_book_id: str = "book-1",
    name: str = "测试小说",
    author: str = "作者甲",
    primary_source_id: str = "official-src",
    payload_sources: list[dict] | None = None,
):
    initialize_database(db_path)
    service = LibraryBooksService(db_path=db_path)
    payload = {
        "name": name,
        "author": author,
        "primaryBookId": f"{primary_source_id}:book-1",
        "primarySourceId": primary_source_id,
        "primarySourceName": "官方源",
        "primaryBookUrl": "https://official.example/book/1",
        "primaryTocUrl": "https://official.example/book/1/toc",
        "sources": payload_sources
        or [
            {
                "bookId": f"{primary_source_id}:book-1",
                "sourceId": primary_source_id,
                "sourceName": "官方源",
                "bookUrl": "https://official.example/book/1",
                "tocUrl": "https://official.example/book/1/toc",
                "score": 200,
                "lastChapter": "第100章",
                "chapterCount": 100,
                "bookStatus": "ongoing",
                "author": author,
                "name": name,
            }
        ],
    }
    with service._conn() as conn:
        conn.execute(
            """
            INSERT INTO aggregate_book_tasks (
                aggregate_book_id, canonical_name, canonical_author, name, author,
                aggregate_payload_json, primary_book_id, primary_source_id,
                primary_source_name, primary_book_url, primary_toc_url,
                search_visibility_status, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'visible', 'active', datetime('now'), datetime('now'))
            """,
            (
                aggregate_book_id,
                service._canonical_name(name),
                service._canonical_author(author),
                name,
                author,
                json.dumps(payload, ensure_ascii=False),
                payload["primaryBookId"],
                primary_source_id,
                payload["primarySourceName"],
                payload["primaryBookUrl"],
                payload["primaryTocUrl"],
            ),
        )
        conn.commit()
    return payload


class FakeSearchCoordinator:
    def __init__(self, items: list[dict] | None = None):
        self.items = items or []
        self.search_calls: list[dict] = []

    def resolve_third_party_source_ids(self, limit: int | None = None) -> list[str]:
        return ["third-src", "mirror-src"][: limit or 10]

    async def search_source_map_candidates(
        self,
        keyword: str,
        *,
        source_ids: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        self.search_calls.append(
            {
                "keyword": keyword,
                "source_ids": list(source_ids or []),
                "limit": limit,
            }
        )
        return list(self.items)


class FakeSourceMapService:
    def __init__(self, refresh_book_ids: set[str] | None = None):
        self.refresh_book_ids = refresh_book_ids or set()
        self.should_refresh_calls: list[str] = []
        self.refresh_calls: list[str] = []

    def should_refresh(self, aggregate_book_id: str, *, payload: dict | None = None) -> tuple[bool, str]:
        self.should_refresh_calls.append(aggregate_book_id)
        return aggregate_book_id in self.refresh_book_ids, "ttl_expired"

    async def refresh_for_book(self, aggregate_book_id: str, *, payload: dict | None = None, force: bool = False) -> dict:
        self.refresh_calls.append(aggregate_book_id)
        return {"bookId": aggregate_book_id, "success": True, "refreshed": True}


@pytest.mark.asyncio
async def test_source_map_refresh_writes_sanitized_metadata_and_private_refs(tmp_path: Path):
    db_path = tmp_path / "library.db"
    storage = SharedBookStorage(tmp_path / "library")
    payload = _insert_book(db_path)

    metadata_path = storage.metadata_path(book_name="测试小说", author="作者甲")
    storage.atomic_write_json(
        metadata_path,
        storage.build_shared_metadata(
            {
                **payload,
                "bookState": {
                    "status": "active",
                    "searchVisibilityStatus": "visible",
                    "chapterCount": 0,
                    "processedChapterCount": 0,
                    "readableChapterCount": 0,
                    "previewChapterCount": 0,
                    "proofreadCompleteCount": 0,
                    "suspectChapterCount": 0,
                    "failedChapterCount": 0,
                    "latestChapterIndex": 0,
                    "latestChapterTitle": "",
                    "lastUpdateCheckAt": "",
                },
            }
        ),
    )

    from app.services.shared_book_source_map import SharedBookSourceMapService

    service = SharedBookSourceMapService(
        library_books=LibraryBooksService(db_path=db_path, shared_book_storage=storage),
        search_coordinator=FakeSearchCoordinator(
            [
                {
                    "sourceId": "third-src",
                    "sourceName": "第三方源",
                    "bookId": "third-src:book-9",
                    "rawBookUrl": "https://third.example/book/9",
                    "bookUrl": "https://third.example/book/9",
                    "tocUrl": "https://third.example/book/9/toc",
                    "name": "测试小说",
                    "author": "作者甲",
                    "score": 155,
                    "lastChapter": "第101章",
                    "chapterCount": 101,
                    "status": "ongoing",
                }
            ]
        ),
        storage=storage,
    )

    result = await service.refresh_for_book("book-1")

    assert result["success"] is True
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source_refs = json.loads(storage.source_refs_path(book_name="测试小说", author="作者甲").read_text(encoding="utf-8"))

    assert metadata["sourceMap"]["health"]["status"] == "healthy"
    assert metadata["sourceMap"]["health"]["missingCriticalSource"] is False
    assert len(metadata["sourceMap"]["summary"]) == 2
    assert "bookUrl" not in json.dumps(metadata["sourceMap"], ensure_ascii=False)
    assert metadata["sourceMapSummary"] == metadata["sourceMap"]["summary"]

    assert source_refs["primarySource"]["sourceId"] == "official-src"
    assert {item["sourceId"] for item in source_refs["sourceMapRefs"]} == {"official-src", "third-src"}
    assert source_refs["sourceMapRefs"][1]["bookUrl"] == "https://third.example/book/9"

    refreshed_payload = LibraryBooksService(db_path=db_path, shared_book_storage=storage).load_payload("book-1")
    assert {item["sourceId"] for item in refreshed_payload["sources"]} == {"official-src", "third-src"}


def test_source_map_refresh_ttl_and_missing_critical_source_conditions(tmp_path: Path):
    db_path = tmp_path / "library.db"
    storage = SharedBookStorage(tmp_path / "library")
    payload = _insert_book(db_path)
    service = LibraryBooksService(db_path=db_path, shared_book_storage=storage)

    metadata_path = storage.metadata_path(book_name="测试小说", author="作者甲")
    storage.atomic_write_json(
        metadata_path,
        {
            **storage.build_shared_metadata(payload),
            "sourceMap": {
                "summary": [],
                "health": {
                    "lastVerifiedAt": "2026-06-20T00:00:00+00:00",
                    "status": "missing_critical_source",
                    "missingCriticalSource": True,
                },
            },
        },
    )

    from app.services.shared_book_source_map import SharedBookSourceMapService

    fixed_now = datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc)

    source_map_service = SharedBookSourceMapService(
        library_books=service,
        search_coordinator=FakeSearchCoordinator(),
        storage=storage,
        refresh_ttl_hours=24,
        now_provider=lambda: fixed_now,
    )

    should_refresh, reason = source_map_service.should_refresh("book-1", payload=payload)
    assert should_refresh is True
    assert reason == "missing_critical_source"

    storage.atomic_write_json(
        metadata_path,
        {
            **storage.build_shared_metadata(payload),
            "sourceMap": {
                "summary": [],
                "health": {
                    "lastVerifiedAt": (fixed_now - timedelta(hours=1)).isoformat(),
                    "status": "search_failed",
                    "missingCriticalSource": False,
                },
            },
        },
    )

    should_refresh, reason = source_map_service.should_refresh("book-1", payload=payload)
    assert should_refresh is True
    assert reason == "unhealthy_status"

    storage.atomic_write_json(
        metadata_path,
        {
            **storage.build_shared_metadata(payload),
            "sourceMap": {
                "summary": [],
                "health": {
                    "lastVerifiedAt": (fixed_now - timedelta(hours=25)).isoformat(),
                    "status": "healthy",
                    "missingCriticalSource": False,
                },
            },
        },
    )

    should_refresh, reason = source_map_service.should_refresh("book-1", payload=payload)
    assert should_refresh is True
    assert reason == "ttl_expired"

    storage.atomic_write_json(
        metadata_path,
        {
            **storage.build_shared_metadata(payload),
            "sourceMap": {
                "summary": [],
                "health": {
                    "lastVerifiedAt": (fixed_now - timedelta(hours=1)).isoformat(),
                    "status": "healthy",
                    "missingCriticalSource": False,
                },
            },
        },
    )

    should_refresh, reason = source_map_service.should_refresh("book-1", payload=payload)
    assert should_refresh is False
    assert reason == "fresh"


@pytest.mark.asyncio
async def test_scheduler_uses_book_source_map_refresh_trigger_when_book_needs_refresh():
    class FakeProcessor:
        def __init__(self):
            self.due_books = [
                {"aggregateBookId": "book-stale", "payload": {"name": "测试小说", "author": "作者甲"}},
                {"aggregateBookId": "book-fresh", "payload": {"name": "另一本", "author": "作者乙"}},
            ]
            self.run_calls: list[str] = []

        def list_due_books(self, limit: int = 10):
            return list(self.due_books[:limit])

        async def run_book_task(self, aggregate_book_id: str):
            self.run_calls.append(aggregate_book_id)
            return {"bookId": aggregate_book_id, "success": True}

        def _library_books(self):
            return self

        def get_book(self, aggregate_book_id: str):
            return {"aggregateBookId": aggregate_book_id, "name": aggregate_book_id, "author": "作者"}

    processor = FakeProcessor()
    source_map_service = FakeSourceMapService(refresh_book_ids={"book-stale"})
    scheduler = SharedBookScheduler(
        processor=processor,
        recovery_scanner=lambda: [],
        source_map_service=source_map_service,
    )
    scheduler._recovery_complete.set()

    result = await scheduler.run_periodic_once(wait_for_recovery=True)

    assert result["processedBooks"] == 2
    assert source_map_service.refresh_calls == ["book-stale"]
    assert processor.run_calls == ["book-fresh"]
    assert [item["trigger"] for item in result["items"]] == [
        "book_source_map_refresh",
        "book_update_check",
    ]
