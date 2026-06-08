"""Tests for realtime search job API."""

import pytest
import asyncio
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
async def test_search_job_emits_verification_required_event(monkeypatch):
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
    assert "source_verification_required" in event_types
    assert "source_timeout" not in event_types
    assert job.browser_challenges[0]["openUrl"] == "https://example.com/search"


@pytest.mark.asyncio
async def test_search_job_preflights_cloudflare_browser_source(monkeypatch):
    service = SearchJobService()

    class FakeSource:
        async def search(self, ctx, keyword, page):
            raise AssertionError("preflight should skip plugin search")

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
                    "verificationUrl": "https://example.com/rank",
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

        def search_timeout_for_plugin(self, plugin):
            return 30

    service.scheduler = FakeScheduler()
    monkeypatch.setattr(service._cache, "set_search", lambda *args, **kwargs: None)
    job = service.create_job("剑宗外门", page=1, limit=1)

    await service.run_job(job.job_id)

    event_types = [event["type"] for event in job.events]
    assert "source_verification_required" in event_types
    assert job.completed_count == 1
    assert job.browser_challenges[0]["openUrl"] == "https://example.com/rank"


@pytest.mark.asyncio
async def test_search_job_skips_cloudflare_preflight_when_search_engine_fallback_declared(monkeypatch):
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
                    "verificationUrl": "https://www.69shuba.com/newhot_0_1_1.htm",
                    "searchFallback": "search_engine",
                },
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
