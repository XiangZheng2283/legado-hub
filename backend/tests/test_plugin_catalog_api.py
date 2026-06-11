"""Tests for plugin-backed catalog API."""

import pytest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.source_plugins.loader import PluginLoader


def _make_fake_plugin(tmp_path: Path, plugin_id: str):
    d = tmp_path / plugin_id
    d.mkdir(parents=True, exist_ok=True)
    import yaml
    meta = {
        "contractVersion": "1.0",
        "id": plugin_id,
        "name": f"Fake {plugin_id}",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search", "detail", "toc", "chapter"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "tags": ["html"],
    }
    (d / "metadata.yaml").write_text(yaml.dump(meta), encoding="utf-8")
    source_py = f'''
class Source:
    id = "{plugin_id}"
    name = "Fake {plugin_id}"
    contract_version = "1.0"
    base_url = "https://example.com"

    async def search(self, ctx, keyword: str, page: int):
        return [
            {{
                "sourceId": "{plugin_id}",
                "name": "Test Book " + keyword,
                "author": "Test Author",
                "bookUrl": self.base_url + "/book/1",
            }}
        ]

    async def detail(self, ctx, book_url: str):
        return {{
            "sourceId": "{plugin_id}",
            "name": "Test Book",
            "author": "Test Author",
            "bookUrl": book_url,
            "tocUrl": book_url,
        }}

    async def toc(self, ctx, toc_url: str):
        return [
            {{
                "sourceId": "{plugin_id}",
                "index": 1,
                "title": "Chapter 1",
                "chapterUrl": self.base_url + "/chapter/1",
            }}
        ]

    async def chapter(self, ctx, chapter_url: str):
        return {{
            "sourceId": "{plugin_id}",
            "title": "Chapter 1",
            "content": "This is chapter content. " * 50,
            "chapterUrl": chapter_url,
        }}
'''
    (d / "source.py").write_text(source_py, encoding="utf-8")
    return d


@pytest.fixture
def client_with_plugin(monkeypatch, tmp_path):
    _make_fake_plugin(tmp_path, "fake_api")
    from app.source_plugins.scheduler import PluginScheduler
    from app.services.catalog import Catalog
    from app.services.search_jobs import SearchJobService

    # Inject plugin dir into scheduler instances created by services
    orig_scheduler_init = PluginScheduler.__init__
    def patched_scheduler_init(self, loader=None, config=None):
        loader = loader or PluginLoader(plugins_dir=tmp_path)
        orig_scheduler_init(self, loader=loader, config=config)

    monkeypatch.setattr(PluginScheduler, "__init__", patched_scheduler_init)

    # Also patch catalog and search job service to use our plugin dir
    def patched_catalog_init(self, repo=None, cache=None, base_api=None):
        from app.services.plugin_health_repository import PluginHealthRepository
        from app.services.cache import Cache
        self.repo = repo or PluginHealthRepository()
        self.cache = cache or Cache()
        self.scheduler = PluginScheduler(loader=PluginLoader(plugins_dir=tmp_path), config=self._get_search_config())
        self.base_api = base_api or "http://localhost"

    monkeypatch.setattr(Catalog, "__init__", patched_catalog_init)

    def patched_search_init(self):
        self._jobs = {}
        from app.services.plugin_health_repository import PluginHealthRepository
        from app.services.cache import Cache
        self._repo = PluginHealthRepository()
        self._cache = Cache()
        self.scheduler = PluginScheduler(loader=PluginLoader(plugins_dir=tmp_path), config=self._get_search_config())

    monkeypatch.setattr(SearchJobService, "__init__", patched_search_init)

    return TestClient(app)


def test_search_returns_plugin_results(client_with_plugin):
    res = client_with_plugin.get("/api/legado/search?keyword=凡人")
    assert res.status_code == 200
    data = res.json()
    assert data["implemented"] is True
    assert len(data["items"]) >= 1
    assert data["items"][0]["name"] == "Test Book 凡人"


def test_book_detail(client_with_plugin):
    from app.source_plugins.id_codec import encode_book_id
    book_id = encode_book_id("fake_api", "https://example.com/book/1")
    res = client_with_plugin.get(f"/api/legado/book/{book_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["implemented"] is True
    assert data["data"]["name"] == "Test Book"


def test_toc(client_with_plugin):
    from app.source_plugins.id_codec import encode_book_id
    book_id = encode_book_id("fake_api", "https://example.com/book/1")
    res = client_with_plugin.get(f"/api/legado/book/{book_id}/toc")
    assert res.status_code == 200
    data = res.json()
    assert data["implemented"] is True
    assert len(data["chapters"]) >= 1


def test_chapter(client_with_plugin):
    from app.source_plugins.id_codec import encode_chapter_id
    chapter_id = encode_chapter_id("fake_api", "https://example.com/chapter/1")
    res = client_with_plugin.get(f"/api/legado/chapter/{chapter_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["implemented"] is True
    assert len(data["content"]) > 0


def test_chapter_uses_cache_only_when_live_fetch_hits_bypass_error(monkeypatch, client_with_plugin):
    from app.services.catalog import Catalog
    from app.source_plugins.id_codec import encode_chapter_id
    from app.source_plugins.scheduler import PluginScheduler

    chapter_id = encode_chapter_id("fake_api", "https://example.com/chapter/1")

    original_scheduler_init = PluginScheduler.__init__

    def patched_scheduler_init(self, loader=None, config=None):
        original_scheduler_init(self, loader=loader, config=config)
        plugin = self._plugins.get("fake_api")
        if plugin is not None:
            async def failing_plugin_chapter(ctx, chapter_url: str):
                from app.source_plugins.errors import CloudflareRequired
                raise CloudflareRequired("Cloudflare verification required", url=chapter_url)

            plugin.source.chapter = failing_plugin_chapter

    monkeypatch.setattr(PluginScheduler, "__init__", patched_scheduler_init)

    original_catalog_init = Catalog.__init__

    def patched_catalog_init(self, repo=None, cache=None, base_api=None):
        original_catalog_init(self, repo=repo, cache=cache, base_api=base_api)
        self.cache.set_chapter(
            chapter_id,
            "fake_api",
            "https://example.com/chapter/1",
            {
                "implemented": True,
                "chapterId": chapter_id,
                "title": "缓存章节",
                "content": "缓存正文\n\n第二段",
                "debug": {},
            },
        )

    monkeypatch.setattr(Catalog, "__init__", patched_catalog_init)

    res = client_with_plugin.get(f"/api/legado/chapter/{chapter_id}")

    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "缓存章节"
    assert data["debug"]["cacheHit"] is True
    assert data["debug"]["cacheReason"] == "cloudflare_required"


def test_empty_plugin_pool():
    from app.source_plugins.scheduler import PluginScheduler
    sched = PluginScheduler(loader=PluginLoader(plugins_dir=Path("/nonexistent")), config={})
    import asyncio
    result = asyncio.run(sched.search("test"))
    assert result["items"] == []
    assert result["debug"]["sourceCount"] == 0






