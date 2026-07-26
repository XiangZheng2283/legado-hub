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
from app.source_plugins.id_codec import encode_book_id
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


class FakeCatalog:
    def __init__(self, chapters_by_book_id: dict[str, list[dict]]):
        self.chapters_by_book_id = chapters_by_book_id
        self.detail_calls: list[str] = []
        self.toc_calls: list[str] = []

    async def book_detail(self, book_id: str, user_agent: str = "") -> dict:
        self.detail_calls.append(book_id)
        return {
            "implemented": True,
            "data": {
                "rawTocUrl": "https://m.qidian.com/book/1030000000/catalog/",
                "chapterCount": 1,
            },
            "debug": {},
        }

    async def toc(self, book_id: str, user_agent: str = "") -> dict:
        self.toc_calls.append(book_id)
        chapters = self.chapters_by_book_id.get(book_id)
        if chapters is None:
            return {"implemented": True, "chapters": [], "debug": {"error": "toc unavailable"}}
        return {"implemented": True, "chapters": list(chapters), "debug": {}}


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
                    "author": "作者：作者甲",
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
    assert source_refs["sourceMapRefs"][1]["lastChapter"] == "第101章"
    assert source_refs["sourceMapRefs"][1]["chapterCount"] == 101

    refreshed_payload = LibraryBooksService(db_path=db_path, shared_book_storage=storage).load_payload("book-1")
    assert {item["sourceId"] for item in refreshed_payload["sources"]} == {"official-src", "third-src"}


@pytest.mark.asyncio
async def test_source_map_refresh_fills_missing_web_chapter_count_from_toc(tmp_path: Path):
    db_path = tmp_path / "library.db"
    storage = SharedBookStorage(tmp_path / "library")
    web_book_url = "https://m.qidian.com/book/1030000000/"
    web_book_id = encode_book_id("qidian_com_web", web_book_url)
    payload = _insert_book(
        db_path,
        primary_source_id="qidian_com_web",
        payload_sources=[
            {
                "bookId": web_book_id,
                "sourceId": "qidian_com_web",
                "sourceName": "起点中文网(Web)",
                "bookUrl": web_book_url,
                "tocUrl": "",
                "score": 221,
                "lastChapter": "第九百九十九章 关底boss",
                "chapterCount": 0,
                "author": "作者甲",
                "name": "测试小说",
            }
        ],
    )
    catalog = FakeCatalog(
        {
            web_book_id: [
                {"index": index, "title": f"第{index}章"}
                for index in range(1, 120)
            ]
        }
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
                    "name": "测试小说",
                    "author": "作者甲",
                    "score": 155,
                    "lastChapter": "第101章",
                    "chapterCount": 101,
                }
            ]
        ),
        storage=storage,
        catalog=catalog,
    )

    result = await service.refresh_for_book("book-1", payload=payload, force=True)

    assert result["success"] is True
    assert catalog.detail_calls == [web_book_id]
    assert catalog.toc_calls == [web_book_id]
    refreshed_payload = LibraryBooksService(db_path=db_path, shared_book_storage=storage).load_payload("book-1")
    web_source = next(item for item in refreshed_payload["sources"] if item["sourceId"] == "qidian_com_web")
    assert web_source["chapterCount"] == 119
    assert web_source["tocUrl"] == "https://m.qidian.com/book/1030000000/catalog/"


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


@pytest.mark.asyncio
async def test_source_map_refresh_replaces_stale_third_party_sources(tmp_path: Path):
    db_path = tmp_path / "library.db"
    storage = SharedBookStorage(tmp_path / "library")
    payload = _insert_book(
        db_path,
        payload_sources=[
            {
                "bookId": "official-src:book-1",
                "sourceId": "official-src",
                "sourceName": "官方源",
                "bookUrl": "https://official.example/book/1",
            },
            {
                "bookId": "third-src:book-old",
                "sourceId": "third-src",
                "sourceName": "旧第三方源",
                "bookUrl": "https://third.example/book/old",
            },
            {
                "bookId": "mirror-src:book-keep",
                "sourceId": "mirror-src",
                "sourceName": "暂未返回的历史源",
                "bookUrl": "https://mirror.example/book/keep",
            },
        ],
    )

    metadata_path = storage.metadata_path(book_name="测试小说", author="作者甲")
    storage.atomic_write_json(
        metadata_path,
        {
            **storage.build_shared_metadata(payload),
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
        },
    )

    from app.services.shared_book_source_map import SharedBookSourceMapService

    service = SharedBookSourceMapService(
        library_books=LibraryBooksService(db_path=db_path, shared_book_storage=storage),
        search_coordinator=FakeSearchCoordinator(
            [
                {
                    "sourceId": "third-src",
                    "sourceName": "第三方源",
                    "bookId": "third-src:book-10",
                    "rawBookUrl": "https://third.example/book/10",
                    "bookUrl": "https://third.example/book/10",
                    "tocUrl": "https://third.example/book/10/toc",
                    "name": "测试小说",
                    "author": "作者甲",
                    "score": 160,
                    "lastChapter": "第102章",
                    "chapterCount": 102,
                    "status": "ongoing",
                }
            ]
        ),
        storage=storage,
    )

    result = await service.refresh_for_book("book-1", payload=payload, force=True)

    assert result["success"] is True
    refreshed_payload = LibraryBooksService(db_path=db_path, shared_book_storage=storage).load_payload("book-1")
    assert [item["sourceId"] for item in refreshed_payload["sources"]] == ["official-src", "third-src"]
    assert refreshed_payload["sources"][1]["bookId"] == "third-src:book-10"


@pytest.mark.asyncio
async def test_source_map_refresh_keeps_old_sources_as_stale_when_search_is_empty(tmp_path: Path):
    db_path = tmp_path / "library.db"
    storage = SharedBookStorage(tmp_path / "library")
    payload = _insert_book(
        db_path,
        payload_sources=[
            {
                "bookId": "official-src:book-1",
                "sourceId": "official-src",
                "sourceName": "官方源",
                "bookUrl": "https://official.example/book/1",
            },
            {
                "bookId": "mirror-src:book-old",
                "sourceId": "mirror-src",
                "sourceName": "历史候补源",
                "bookUrl": "https://mirror.example/book/old",
            },
        ],
    )

    from app.services.shared_book_source_map import SharedBookSourceMapService

    service = SharedBookSourceMapService(
        library_books=LibraryBooksService(db_path=db_path, shared_book_storage=storage),
        search_coordinator=FakeSearchCoordinator(),
        storage=storage,
    )

    result = await service.refresh_for_book("book-1", payload=payload, force=True)

    assert service.refresh_ttl == timedelta(hours=6)
    assert result["health"]["status"] == "stale"
    assert service.should_refresh("book-1", payload=payload) == (False, "stale_waiting_ttl")
    refreshed_payload = LibraryBooksService(
        db_path=db_path,
        shared_book_storage=storage,
    ).load_payload("book-1")
    assert [item["sourceId"] for item in refreshed_payload["sources"]] == [
        "official-src",
        "mirror-src",
    ]
    source_refs = json.loads(
        storage.source_refs_path(book_name="测试小说", author="作者甲").read_text(encoding="utf-8")
    )
    statuses = {item["sourceId"]: item["status"] for item in source_refs["sourceMapRefs"]}
    assert statuses == {"official-src": "healthy", "mirror-src": "stale"}
