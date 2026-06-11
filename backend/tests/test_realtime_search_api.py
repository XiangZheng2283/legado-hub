"""Tests for realtime search job API."""

import pytest
import asyncio
import sqlite3
import json
from fastapi.testclient import TestClient
from app.main import app
from app.storage.db import initialize_database
from app.services.search_jobs import SearchJobService
from app.source_plugins.errors import BrowserRequired
from app.source_plugins.models import PluginMetadata

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr("app.config.DB_PATH", db)
    monkeypatch.setattr("app.services.cache.DB_PATH", db)
    initialize_database(db)
    yield


def test_create_search_job():
    response = client.post("/api/console/search-jobs", json={"keyword": "凡人修仙传", "page": 1, "limit": 3})
    assert response.status_code == 200
    data = response.json()
    assert "jobId" in data
    assert data["status"] == "running"
    assert data["sourceCount"] == 3
    assert data["completedCount"] == 0
    assert data["events"][0]["type"] == "queued"


def test_create_search_job_exposes_immediate_progress_event():
    response = client.post("/api/console/search-jobs", json={"keyword": "凡人修仙传", "page": 1, "limit": 2})
    job_id = response.json()["jobId"]

    events_response = client.get(f"/api/console/search-jobs/{job_id}/events")

    assert events_response.status_code == 200
    events = events_response.json()["events"]
    assert events
    assert events[0]["type"] == "queued"
    assert events[0]["sourceCount"] == 2


def test_get_search_job():
    create = client.post("/api/console/search-jobs", json={"keyword": "test", "page": 1, "limit": 2})
    job_id = create.json()["jobId"]
    response = client.get(f"/api/console/search-jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["jobId"] == job_id


def test_cancel_search_job():
    create = client.post("/api/console/search-jobs", json={"keyword": "test", "page": 1, "limit": 2})
    job_id = create.json()["jobId"]
    response = client.post(f"/api/console/search-jobs/{job_id}/cancel")
    assert response.status_code == 200
    data = response.json()
    assert data["cancelled"] is True


def test_cancel_completed_search_job_is_noop():
    service = SearchJobService()
    job = service.create_job("test", page=1, limit=0)
    job.status = "completed"

    assert service.cancel_job(job.job_id) is False
    assert job.status == "completed"


@pytest.mark.asyncio
async def test_search_job_exposes_first_source_result_before_all_sources_finish(monkeypatch):
    service = SearchJobService()
    slow_started = asyncio.Event()
    slow_can_finish = asyncio.Event()

    class FastSource:
        async def search(self, ctx, keyword, page):
            return [{"name": keyword, "author": "作者甲", "bookUrl": "https://fast.example/book/1"}]

    class SlowSource:
        async def search(self, ctx, keyword, page):
            slow_started.set()
            await slow_can_finish.wait()
            return [{"name": f"{keyword} 慢源", "author": "作者乙", "bookUrl": "https://slow.example/book/1"}]

    class FakeContext:
        class Fetcher:
            async def close(self):
                return None

        _fetcher = Fetcher()

    class FakeScheduler:
        def __init__(self):
            self.plugins = [
                type("Plugin", (), {
                    "metadata": PluginMetadata.from_dict({
                        "contractVersion": "1.0",
                        "id": "fast_source",
                        "name": "Fast Source",
                        "version": "0.1.0",
                        "type": "source",
                        "domains": ["fast.example"],
                        "baseUrls": ["https://fast.example"],
                        "capabilities": ["search"],
                        "auth": {"mode": "none"},
                        "content": {"access": "free"},
                        "tags": [],
                    }),
                    "source": FastSource(),
                    "capabilities": ["search"],
                })(),
                type("Plugin", (), {
                    "metadata": PluginMetadata.from_dict({
                        "contractVersion": "1.0",
                        "id": "slow_source",
                        "name": "Slow Source",
                        "version": "0.1.0",
                        "type": "source",
                        "domains": ["slow.example"],
                        "baseUrls": ["https://slow.example"],
                        "capabilities": ["search"],
                        "auth": {"mode": "none"},
                        "content": {"access": "free"},
                        "tags": [],
                    }),
                    "source": SlowSource(),
                    "capabilities": ["search"],
                })(),
            ]

        def _enabled_plugins(self):
            return self.plugins

        def _make_ctx(self, source_id):
            return FakeContext()

        def search_timeout_for_plugin(self, plugin):
            return 30

    service.scheduler = FakeScheduler()
    monkeypatch.setattr(service, "_get_search_config", lambda: {
        "max_concurrency": 2,
        "source_batch_size": 2,
        "overall_search_timeout_seconds": 30,
    })
    monkeypatch.setattr(service, "_record_attempt", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._repo, "record_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._cache, "set_search", lambda *args, **kwargs: None)
    job = service.create_job("剑宗外门", page=1, limit=2)

    runner = asyncio.create_task(service.run_job(job.job_id))
    await asyncio.wait_for(slow_started.wait(), timeout=1)

    for _ in range(20):
        if job.candidate_groups:
            break
        await asyncio.sleep(0.05)

    assert job.status == "running"
    assert job.candidate_groups
    assert job.candidate_groups[0]["items"][0]["sourceId"] == "fast_source"
    assert "done" not in [event["type"] for event in job.events]

    slow_can_finish.set()
    await runner


@pytest.mark.asyncio
async def test_search_job_honors_max_concurrency(monkeypatch):
    service = SearchJobService()
    active_count = 0
    max_active_count = 0

    class CountingSource:
        async def search(self, ctx, keyword, page):
            nonlocal active_count, max_active_count
            active_count += 1
            max_active_count = max(max_active_count, active_count)
            await asyncio.sleep(0.02)
            active_count -= 1
            return [{"name": keyword, "author": "作者", "bookUrl": f"https://{ctx.source_id}.example/book/1"}]

    class FakeContext:
        def __init__(self, source_id):
            self.source_id = source_id
            self._fetcher = self.Fetcher()

        class Fetcher:
            async def close(self):
                return None

    def make_plugin(index):
        source_id = f"source_{index}"
        return type("Plugin", (), {
            "metadata": PluginMetadata.from_dict({
                "contractVersion": "1.0",
                "id": source_id,
                "name": f"Source {index}",
                "version": "0.1.0",
                "type": "source",
                "domains": [f"{source_id}.example"],
                "baseUrls": [f"https://{source_id}.example"],
                "capabilities": ["search"],
                "auth": {"mode": "none"},
                "content": {"access": "free"},
                "tags": [],
            }),
            "source": CountingSource(),
            "capabilities": ["search"],
        })()

    class FakeScheduler:
        plugins = [make_plugin(index) for index in range(5)]

        def _enabled_plugins(self):
            return self.plugins

        def _make_ctx(self, source_id):
            return FakeContext(source_id)

        def search_timeout_for_plugin(self, plugin):
            return 30

    service.scheduler = FakeScheduler()
    monkeypatch.setattr(service, "_get_search_config", lambda: {
        "max_concurrency": 2,
        "source_batch_size": 5,
        "overall_search_timeout_seconds": 30,
    })
    monkeypatch.setattr(service, "_record_attempt", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._repo, "record_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._cache, "set_search", lambda *args, **kwargs: None)
    job = service.create_job("并发样例", page=1, limit=5)

    await service.run_job(job.job_id)

    assert job.status == "completed"
    assert job.success_count == 5
    assert max_active_count == 2


@pytest.mark.asyncio
async def test_cancel_search_job_stops_pending_sources(monkeypatch):
    service = SearchJobService()
    source_started = asyncio.Event()
    source_cancelled = asyncio.Event()

    class BlockingSource:
        async def search(self, ctx, keyword, page):
            source_started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                source_cancelled.set()
                raise

    class FakeContext:
        class Fetcher:
            async def close(self):
                return None

        _fetcher = Fetcher()

    class FakeScheduler:
        plugin = type("Plugin", (), {
            "metadata": PluginMetadata.from_dict({
                "contractVersion": "1.0",
                "id": "blocking_source",
                "name": "Blocking Source",
                "version": "0.1.0",
                "type": "source",
                "domains": ["blocking.example"],
                "baseUrls": ["https://blocking.example"],
                "capabilities": ["search"],
                "auth": {"mode": "none"},
                "content": {"access": "free"},
                "tags": [],
            }),
            "source": BlockingSource(),
            "capabilities": ["search"],
        })()

        def _enabled_plugins(self):
            return [self.plugin]

        def _make_ctx(self, source_id):
            return FakeContext()

        def search_timeout_for_plugin(self, plugin):
            return 30

    service.scheduler = FakeScheduler()
    monkeypatch.setattr(service, "_get_search_config", lambda: {
        "max_concurrency": 1,
        "source_batch_size": 1,
        "overall_search_timeout_seconds": 30,
    })
    monkeypatch.setattr(service, "_record_attempt", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._cache, "set_search", lambda *args, **kwargs: None)
    job = service.create_job("剑宗外门", page=1, limit=1)

    runner = asyncio.create_task(service.run_job(job.job_id))
    await asyncio.wait_for(source_started.wait(), timeout=1)

    assert service.cancel_job(job.job_id) is True
    await asyncio.wait_for(source_cancelled.wait(), timeout=1)
    await runner

    assert job.status == "cancelled"
    assert "cancelled" in [event["type"] for event in job.events]


def test_search_stream():
    response = client.get("/api/console/search/stream?keyword=test&limit=2")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"


def test_search_job_candidates_endpoint():
    create = client.post("/api/console/search-jobs", json={"keyword": "test", "page": 1, "limit": 2})
    job_id = create.json()["jobId"]
    response = client.get(f"/api/console/search-jobs/{job_id}/candidates")
    assert response.status_code == 200
    data = response.json()
    assert data["jobId"] == job_id
    assert "items" in data


@pytest.mark.asyncio
async def test_search_job_marks_browser_required_as_bypass_error(monkeypatch):
    service = SearchJobService()

    class FakeSource:
        async def search(self, ctx, keyword, page):
            raise BrowserRequired("browser verification required", url="https://example.com/search")

    class FakeContext:
        class Fetcher:
            async def close(self):
                return None

        _fetcher = Fetcher()

    class FakeScheduler:
        def __init__(self):
            self._plugins = {"fixture_browser": self.plugin}

        plugin = type("Plugin", (), {
            "metadata": PluginMetadata.from_dict({
                "contractVersion": "1.0",
                "id": "fixture_browser",
                "name": "Fixture Browser",
                "version": "0.1.0",
                "type": "source",
                "domains": ["example.com"],
                "baseUrls": ["https://example.com"],
                "capabilities": ["search"],
                "auth": {"mode": "none"},
                "content": {"access": "free"},
                "browser": {"mode": "required"},
                "tags": [],
            }),
            "source": FakeSource(),
            "capabilities": ["search"],
        })()

        def _enabled_plugins(self):
            return [self.plugin]

        def _make_ctx(self, source_id):
            return FakeContext()

        def search_timeout_for_plugin(self, plugin):
            return 30

    service.scheduler = FakeScheduler()
    monkeypatch.setattr(service, "_record_attempt", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._repo, "record_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._cache, "set_search", lambda *args, **kwargs: None)
    job = service.create_job("剑宗外门", page=1, limit=1)

    await service.run_job(job.job_id)

    event_types = [event["type"] for event in job.events]
    assert "source_error" in event_types
    assert "source_timeout" not in event_types
    error_event = next(event for event in job.events if event["type"] == "source_error")
    assert error_event["error"]["code"] == "BROWSER_REQUIRED"
    assert error_event["error"]["extra"]["bypassRequired"] is True


@pytest.mark.asyncio
async def test_search_job_does_not_preflight_cloudflare_browser_source(monkeypatch):
    service = SearchJobService()

    class FakeSource:
        async def search(self, ctx, keyword, page):
            raise BrowserRequired("browser bypass required", url="https://example.com/rank")

    class FakeContext:
        class Fetcher:
            async def close(self):
                return None

        _fetcher = Fetcher()

    class FakeScheduler:
        plugin = type("Plugin", (), {
            "metadata": PluginMetadata.from_dict({
                "contractVersion": "1.0",
                "id": "fixture_cf",
                "name": "Fixture CF",
                "version": "0.1.0",
                "type": "source",
                "domains": ["example.com"],
                "baseUrls": ["https://example.com"],
                "capabilities": ["search"],
                "auth": {"mode": "none"},
                "content": {"access": "free"},
                    "browser": {
                        "mode": "required",
                        "reason": "cloudflare_verification",
                    },
                "tags": [],
            }),
            "source": FakeSource(),
            "capabilities": ["search"],
        })()

        def __init__(self):
            self._plugins = {"fixture_cf": self.plugin}

        def _enabled_plugins(self):
            return [self.plugin]

        def _make_ctx(self, source_id):
            return FakeContext()

        def search_timeout_for_plugin(self, plugin):
            return 30

    service.scheduler = FakeScheduler()
    monkeypatch.setattr(service, "_record_attempt", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._cache, "set_search", lambda *args, **kwargs: None)
    job = service.create_job("剑宗外门", page=1, limit=1)

    await service.run_job(job.job_id)

    event_types = [event["type"] for event in job.events]
    assert "source_error" in event_types
    assert job.completed_count == 1
    error_event = next(event for event in job.events if event["type"] == "source_error")
    assert error_event["error"]["extra"]["bypassRequired"] is True


@pytest.mark.asyncio
async def test_search_job_skips_cloudflare_preflight_when_search_provider_fallback_declared(monkeypatch):
    service = SearchJobService()

    class FakeSource:
        async def search(self, ctx, keyword, page):
            return [{
                "sourceId": "fixture_cf_fallback",
                "name": keyword,
                "author": "作者",
                "bookUrl": "https://www.69shuba.com/book/1.htm",
            }]

    class FakeContext:
        class Fetcher:
            async def close(self):
                return None

        _fetcher = Fetcher()

    class FakeScheduler:
        plugin = type("Plugin", (), {
            "metadata": PluginMetadata.from_dict({
                "contractVersion": "1.0",
                "id": "fixture_cf_fallback",
                "name": "Fixture CF Fallback",
                "version": "0.1.0",
                "type": "source",
                "domains": ["69shuba.com"],
                "baseUrls": ["https://www.69shuba.com"],
                "capabilities": ["search"],
                "auth": {"mode": "none"},
                "content": {"access": "free"},
                    "browser": {
                        "mode": "required",
                        "reason": "cloudflare_verification",
                    },
                "accessStrategy": {"search": "search_provider"},
                "tags": [],
            }),
            "source": FakeSource(),
            "capabilities": ["search"],
        })()

        def __init__(self):
            self._plugins = {"fixture_cf_fallback": self.plugin}

        def _enabled_plugins(self):
            return [self.plugin]

        def _make_ctx(self, source_id):
            return FakeContext()

        def search_timeout_for_plugin(self, plugin):
            return 30

    service.scheduler = FakeScheduler()
    monkeypatch.setattr(service, "_record_attempt", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._repo, "record_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._cache, "set_search", lambda *args, **kwargs: None)
    job = service.create_job("剑宗外门", page=1, limit=1)

    await service.run_job(job.job_id)

    event_types = [event["type"] for event in job.events]
    assert "source_verification_required" not in event_types
    assert job.completed_count == 1
    assert job.success_count == 1
    assert job.candidate_groups[0]["name"] == "剑宗外门"


@pytest.mark.asyncio
async def test_search_job_records_candidate_books_for_bookshelf(monkeypatch):
    import app.config as config

    service = SearchJobService()

    class FakeSource:
        async def search(self, ctx, keyword, page):
            return [{
                "sourceId": "fixture_bookshelf",
                "sourceName": "Fixture Bookshelf",
                "name": keyword,
                "author": "作者甲",
                "bookUrl": "https://bookshelf.example/book/1",
                "lastChapter": "第一章 起点",
            }]

    class FakeContext:
        class Fetcher:
            async def close(self):
                return None

        _fetcher = Fetcher()

    class FakeScheduler:
        plugin = type("Plugin", (), {
            "metadata": PluginMetadata.from_dict({
                "contractVersion": "1.0",
                "id": "fixture_bookshelf",
                "name": "Fixture Bookshelf",
                "version": "0.1.0",
                "type": "source",
                "domains": ["bookshelf.example"],
                "baseUrls": ["https://bookshelf.example"],
                "capabilities": ["search"],
                "auth": {"mode": "none"},
                "content": {"access": "free"},
                "tags": [],
            }),
            "source": FakeSource(),
            "capabilities": ["search"],
        })()

        def _enabled_plugins(self):
            return [self.plugin]

        def _make_ctx(self, source_id):
            return FakeContext()

        def search_timeout_for_plugin(self, plugin):
            return 30

    service.scheduler = FakeScheduler()
    monkeypatch.setattr(service, "_get_search_config", lambda: {
        "max_concurrency": 1,
        "source_batch_size": 1,
        "overall_search_timeout_seconds": 30,
    })
    monkeypatch.setattr(service, "_record_attempt", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._repo, "record_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._cache, "set_search", lambda *args, **kwargs: None)
    job = service.create_job("书架样例", page=1, limit=1)

    await service.run_job(job.job_id)

    assert job.status == "completed"
    book_id = job.result["items"][0]["bookId"]
    with sqlite3.connect(config.DB_PATH) as conn:
        row = conn.execute(
            "SELECT book_id, name, author, selected_source_id, last_chapter FROM book_records WHERE book_id = ?",
            (book_id,),
        ).fetchone()

    assert row == (book_id, "书架样例", "作者甲", "fixture_bookshelf", "第一章 起点")


@pytest.mark.asyncio
async def test_search_snapshot_includes_raw_items_and_virtual_aggregate_source(monkeypatch):
    service = SearchJobService()

    class SourceA:
        async def search(self, ctx, keyword, page):
            return [{
                "name": keyword,
                "author": "作者甲",
                "bookUrl": "https://a.example/book/1",
                "lastChapter": "第一章",
            }]

    class SourceB:
        async def search(self, ctx, keyword, page):
            return [{
                "name": keyword,
                "author": "作者甲",
                "bookUrl": "https://b.example/book/1",
                "lastChapter": "第二章",
            }]

    class FakeContext:
        class Fetcher:
            async def close(self):
                return None

        _fetcher = Fetcher()

    def plugin(source_id, name, source):
        return type("Plugin", (), {
            "metadata": PluginMetadata.from_dict({
                "contractVersion": "1.0",
                "id": source_id,
                "name": name,
                "version": "0.1.0",
                "type": "source",
                "domains": [f"{source_id}.example"],
                "baseUrls": [f"https://{source_id}.example"],
                "capabilities": ["search"],
                "auth": {"mode": "none"},
                "content": {"access": "free"},
                "tags": [],
            }),
            "source": source,
            "capabilities": ["search"],
        })()

    class FakeScheduler:
        plugins = [
            plugin("source_a", "Source A", SourceA()),
            plugin("source_b", "Source B", SourceB()),
        ]

        def _enabled_plugins(self):
            return self.plugins

        def _make_ctx(self, source_id):
            return FakeContext()

        def search_timeout_for_plugin(self, plugin):
            return 30

    service.scheduler = FakeScheduler()
    monkeypatch.setattr(service, "_get_search_config", lambda: {
        "max_concurrency": 2,
        "source_batch_size": 2,
        "overall_search_timeout_seconds": 30,
    })
    monkeypatch.setattr(service, "_record_attempt", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._repo, "record_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._cache, "set_search", lambda *args, **kwargs: None)
    job = service.create_job("聚合样例", page=1, limit=2)

    await service.run_job(job.job_id)

    result_source_ids = [item["sourceId"] for item in job.result["items"]]
    assert result_source_ids.count("source_a") == 1
    assert result_source_ids.count("source_b") == 1
    assert "legadohub_ai_aggregate" not in result_source_ids

    snapshot = service.snapshot(job)
    source_ids = [item["sourceId"] for item in snapshot["items"]]
    assert source_ids.count("source_a") == 1
    assert source_ids.count("source_b") == 1
    assert source_ids.count("legadohub_ai_aggregate") == 1

    aggregate = next(item for item in snapshot["items"] if item["sourceId"] == "legadohub_ai_aggregate")
    assert aggregate["sourceName"] == "LegadoHub AI聚合"
    assert aggregate["aggregate"] is True
    assert aggregate["sourceCount"] == 2
    assert "/api/legado/book/legadohub_ai_aggregate:" in aggregate["bookUrl"]


@pytest.mark.asyncio
async def test_search_snapshot_can_return_only_virtual_aggregate_source(monkeypatch):
    import app.config as config

    service = SearchJobService()

    class FakeSource:
        async def search(self, ctx, keyword, page):
            return [{
                "name": keyword,
                "author": "作者甲",
                "bookUrl": "https://a.example/book/1",
            }]

    class FakeContext:
        class Fetcher:
            async def close(self):
                return None

        _fetcher = Fetcher()

    class FakeScheduler:
        plugin = type("Plugin", (), {
            "metadata": PluginMetadata.from_dict({
                "contractVersion": "1.0",
                "id": "source_a",
                "name": "Source A",
                "version": "0.1.0",
                "type": "source",
                "domains": ["a.example"],
                "baseUrls": ["https://a.example"],
                "capabilities": ["search"],
                "auth": {"mode": "none"},
                "content": {"access": "free"},
                "tags": [],
            }),
            "source": FakeSource(),
            "capabilities": ["search"],
        })()

        def _enabled_plugins(self):
            return [self.plugin]

        def _make_ctx(self, source_id):
            return FakeContext()

        def search_timeout_for_plugin(self, plugin):
            return 30

    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO admin_settings (key, value_json) VALUES (?, ?)",
            (
                "contentWorkflow",
                json.dumps({"returnOnlyAggregateSource": True}, ensure_ascii=False),
            ),
        )
        conn.commit()

    service.scheduler = FakeScheduler()
    monkeypatch.setattr(service, "_get_search_config", lambda: {
        "max_concurrency": 1,
        "source_batch_size": 1,
        "overall_search_timeout_seconds": 30,
    })
    monkeypatch.setattr(service, "_record_attempt", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._repo, "record_success", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._cache, "set_search", lambda *args, **kwargs: None)
    job = service.create_job("聚合样例", page=1, limit=1)

    await service.run_job(job.job_id)

    snapshot = service.snapshot(job)
    assert [item["sourceId"] for item in snapshot["items"]] == ["legadohub_ai_aggregate"]


@pytest.mark.asyncio
async def test_search_job_persists_completed_result_and_events(monkeypatch):
    service = SearchJobService()

    class FakeSource:
        async def search(self, ctx, keyword, page):
            return [{
                "name": keyword,
                "author": "作者甲",
                "bookUrl": "https://persist.example/book/1",
            }]

    class FakeContext:
        class Fetcher:
            async def close(self):
                return None

        _fetcher = Fetcher()

    class FakeScheduler:
        plugin = type("Plugin", (), {
            "metadata": PluginMetadata.from_dict({
                "contractVersion": "1.0",
                "id": "persist_source",
                "name": "Persist Source",
                "version": "0.1.0",
                "type": "source",
                "domains": ["persist.example"],
                "baseUrls": ["https://persist.example"],
                "capabilities": ["search"],
                "auth": {"mode": "none"},
                "content": {"access": "free"},
                "tags": [],
            }),
            "source": FakeSource(),
            "capabilities": ["search"],
        })()

        def _enabled_plugins(self):
            return [self.plugin]

        def _make_ctx(self, source_id):
            return FakeContext()

        def search_timeout_for_plugin(self, plugin):
            return 30

    service.scheduler = FakeScheduler()
    monkeypatch.setattr(service, "_get_search_config", lambda: {
        "max_concurrency": 1,
        "source_batch_size": 1,
        "overall_search_timeout_seconds": 30,
    })
    monkeypatch.setattr(service, "_record_attempt", lambda *args, **kwargs: None)
    monkeypatch.setattr(service._repo, "record_success", lambda *args, **kwargs: None)
    job = service.create_job("持久化样例", page=1, limit=1)
    job.events.append({"type": "queued", "keyword": job.keyword, "page": job.page})
    service.persist_job(job)

    await service.run_job(job.job_id)

    restored_service = SearchJobService()
    restored_job = restored_service.get_job(job.job_id)

    assert restored_job is not None
    assert restored_job.status == "completed"
    assert restored_job.result["items"][0]["name"] == "持久化样例"
    assert [event["type"] for event in restored_job.events][0] == "queued"
    assert "done" in [event["type"] for event in restored_job.events]
    assert restored_service.get_events(job.job_id)
    assert restored_service.list_jobs(limit=5)[0]["jobId"] == job.job_id


def test_verify_search_job_candidate_returns_reviews(monkeypatch):
    import asyncio
    from app.api.console import _live_acceptance_service

    async def mock_verify(candidate, keyword="", chapter_index=0):
        return {
            "pluginId": candidate.get("sourceId", ""),
            "keyword": keyword,
            "status": "passed",
            "passed": True,
            "search": {"count": 0, "firstName": "", "groups": []},
            "selectedCandidate": {
                "candidateId": "abc123",
                "sourceId": candidate.get("sourceId", ""),
                "sourceName": "起点中文网",
                "name": "凡人修仙传",
                "author": "忘语",
                "bookUrl": candidate.get("bookUrl", ""),
                "lastChapter": "",
            },
            "detail": {"name": "凡人修仙传", "author": "忘语", "coverUrl": "", "intro": "", "kind": "", "lastChapter": "", "wordCount": "", "wordCountText": "", "bookUrl": "", "tocUrl": "", "passed": True},
            "toc": {"chapterCount": 1, "count": 1, "firstTitle": "第一章", "items": [{"title": "第一章", "chapterUrl": "https://m.qidian.com/chapter/1/1/"}], "passed": True},
            "chapter": {"title": "第一章", "chapterUrl": "https://m.qidian.com/chapter/1/1/", "contentLength": 900, "preview": "正文" * 300, "content": "正文" * 300, "passed": True},
            "reviews": {
                "paragraphs": {"0": [{"id": "r1", "content": "段评样例", "userName": "读者甲", "likeNum": 3, "replyCount": 0, "reviewTime": "2026-06-11", "paragraphId": 0}]},
                "chapterEnd": [{"id": "r2", "content": "章末评论样例", "userName": "读者乙", "likeNum": 5, "replyCount": 1, "reviewTime": "2026-06-11"}],
                "summary": {"totalReviews": 2, "totalParagraphs": 1, "chapterEndCount": 1, "authMode": "public"},
                "debug": {"mock": True},
                "passed": True,
            },
            "diagnostics": [],
            "timings": {"elapsedMs": 123},
            "explore": {"groupCount": 0, "itemCount": 0, "groups": [], "selected": {"sourceId": "", "sourceName": "", "name": "", "author": "", "bookUrl": "", "groupId": "", "groupTitle": ""}, "detailPassed": False, "tocCount": 0, "chapterTitle": "", "contentLength": 0, "passed": None},
        }

    monkeypatch.setattr(_live_acceptance_service, "verify_candidate", mock_verify)

    # Create a minimal job with one candidate so verify can resolve it
    service = SearchJobService()
    job = service.create_job("凡人修仙传", page=1, limit=1)
    job.status = "completed"
    job.candidate_groups = [{
        "candidateId": "abc123",
        "name": "凡人修仙传",
        "author": "忘语",
        "items": [{
            "candidateId": "abc123",
            "sourceId": "qidian_com",
            "sourceName": "起点中文网",
            "name": "凡人修仙传",
            "author": "忘语",
            "bookUrl": "https://m.qidian.com/book/1/",
            "score": 1200,
        }],
    }]
    service.persist_job(job)

    response = client.post(f"/api/console/search-jobs/{job.job_id}/candidates/abc123/verify", json={"chapterIndex": 0})
    assert response.status_code == 200
    data = response.json()
    assert data["jobId"] == job.job_id
    assert data["candidateId"] == "abc123"
    result = data["result"]
    assert result["reviews"]["paragraphs"]["0"][0]["content"] == "段评样例"
    assert result["reviews"]["chapterEnd"][0]["content"] == "章末评论样例"
    assert result["reviews"]["summary"]["totalReviews"] == 2
    assert result["reviews"]["passed"] is True
