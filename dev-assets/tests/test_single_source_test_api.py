"""Tests for source inventory and developer-only source checks."""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.storage.db import initialize_database

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr("app.config.DB_PATH", db)
    monkeypatch.setattr("app.services.cache.DB_PATH", db)
    initialize_database(db)
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert login.status_code == 200
    yield


def test_source_stage_test_is_not_exposed():
    response = client.post("/api/console/sources/fake-source/test", json={"keyword": "test", "stage": "search"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Not Found"


def test_source_list():
    response = client.get("/api/console/sources?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "stats" in data


@pytest.mark.asyncio
async def test_source_test_uses_configured_stage_timeouts(monkeypatch):
    import app.services.catalog as catalog_module
    from app.services.catalog import Catalog

    captured_timeouts: list[float] = []

    async def capture_wait_for(awaitable, timeout=None):
        captured_timeouts.append(timeout)
        return await awaitable

    monkeypatch.setattr(catalog_module.asyncio, "wait_for", capture_wait_for)

    class FakeFetcher:
        async def close(self):
            return None

    class FakeContext:
        _fetcher = FakeFetcher()

    class FakeSource:
        async def detail(self, ctx, book_url):
            return {"tocUrl": "https://example.com/toc"}

        async def toc(self, ctx, toc_url):
            return [{"chapterUrl": "https://example.com/chapter/1"}]

        async def chapter(self, ctx, chapter_url):
            return {"content": "正文" * 100}

    class FakeMetadata:
        id = "fake"
        base_urls = ["https://example.com/book/1"]

    class FakePlugin:
        metadata = FakeMetadata()
        capabilities = ["detail", "toc", "chapter"]
        source = FakeSource()

    class FakeScheduler:
        _plugins = {"fake": FakePlugin()}

        def _make_ctx(self, source_id):
            return FakeContext()

        def search_timeout_for_plugin(self, plugin):
            return 45.0

        def timeout_for_plugin(self, plugin):
            return 120.0

    class FakeRepo:
        def update_test_result(self, source_id, result):
            return None

    catalog = Catalog.__new__(Catalog)
    catalog.scheduler = FakeScheduler()
    catalog.repo = FakeRepo()

    result = await catalog.test_source("fake", stage="content")

    assert result["pass"] is True
    assert captured_timeouts == [120.0, 120.0, 120.0]
