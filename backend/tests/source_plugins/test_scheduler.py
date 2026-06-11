"""Tests for plugin scheduler."""

import pytest
from pathlib import Path

from app.source_plugins.scheduler import PluginScheduler
from app.source_plugins.loader import PluginLoader


def _make_fake_plugin(tmp_path: Path, plugin_id: str, official: bool = False):
    d = tmp_path / plugin_id
    d.mkdir(parents=True, exist_ok=True)
    import yaml
    capabilities = ["search", "detail", "toc", "chapter"]
    if official:
        capabilities.append("explore")
    meta = {
        "contractVersion": "1.0",
        "id": plugin_id,
        "name": f"Fake {plugin_id}",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": capabilities,
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "tags": ["html", "official"] if official else ["html"],
    }
    (d / "metadata.yaml").write_text(yaml.dump(meta), encoding="utf-8")
    source_py = f'''
class Source:
    id = "{plugin_id}"
    name = "Fake {plugin_id}"
    contract_version = "1.0"

    async def search(self, ctx, keyword: str, page: int):
        return [
            {{
                "sourceId": "{plugin_id}",
                "name": "Test Book",
                "author": "Test Author",
                "bookUrl": "https://example.com/book/1",
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
                "chapterUrl": "https://example.com/chapter/1",
            }}
        ]

    async def chapter(self, ctx, chapter_url: str):
        return {{
            "sourceId": "{plugin_id}",
            "title": "Chapter 1",
            "content": "This is chapter content. " * 50,
            "chapterUrl": chapter_url,
        }}

    async def explore_groups(self, ctx):
        return [
            {{
                "sourceId": "{plugin_id}",
                "groupId": "rank_all",
                "title": "总排行榜",
                "url": "https://example.com/rank",
                "kind": "rank",
            }}
        ]

    async def explore(self, ctx, group_id=None, page: int = 1):
        return [
            {{
                "sourceId": "{plugin_id}",
                "groupId": group_id or "rank_all",
                "name": "Ranked Book",
                "author": "Rank Author",
                "bookUrl": "https://example.com/book/ranked",
            }}
        ]
'''
    (d / "source.py").write_text(source_py, encoding="utf-8")
    return d


@pytest.fixture
def scheduler(tmp_path):
    _make_fake_plugin(tmp_path, "fake_a", official=True)
    _make_fake_plugin(tmp_path, "fake_b")
    loader = PluginLoader(plugins_dir=tmp_path)
    return PluginScheduler(loader=loader, config={
        "max_concurrency": 3,
        "source_timeout_seconds": 8.0,
        "overall_search_timeout_seconds": 30.0,
        "source_batch_size": 20,
    })


@pytest.mark.asyncio
async def test_search_concurrent_success(scheduler):
    result = await scheduler.search("test", page=1)
    assert result["implemented"] is True
    source_ids = [item["sourceId"] for item in result["items"]]
    assert source_ids == ["fake_a", "fake_b"]
    assert all("[来源:" not in item.get("intro", "") for item in result["items"])
    assert result["debug"]["successCount"] >= 1


def test_search_priority_plugins_places_official_sources_first(scheduler):
    ordered = scheduler._search_priority_plugins(scheduler._enabled_plugins())

    assert [plugin.metadata.id for plugin in ordered] == ["fake_a", "fake_b"]


@pytest.mark.asyncio
async def test_search_returns_official_items_before_ordinary_items(scheduler):
    result = await scheduler.search("test", page=1)
    assert result["implemented"] is True
    source_ids = [item["sourceId"] for item in result["items"]]
    assert source_ids.index("fake_a") < source_ids.index("fake_b")


@pytest.mark.asyncio
async def test_search_empty_plugin_pool():
    sched = PluginScheduler(loader=PluginLoader(plugins_dir=Path("/nonexistent")), config={})
    result = await sched.search("test")
    assert result["items"] == []
    assert result["debug"]["sourceCount"] == 0


@pytest.mark.asyncio
async def test_detail_success(scheduler):
    result = await scheduler.detail("fake_a", "https://example.com/book/1")
    assert result["implemented"] is True
    assert result["data"]["name"] == "Test Book"


@pytest.mark.asyncio
async def test_toc_success(scheduler):
    result = await scheduler.toc("fake_a", "https://example.com/book/1")
    assert result["implemented"] is True
    assert len(result["chapters"]) >= 1


@pytest.mark.asyncio
async def test_chapter_success(scheduler):
    result = await scheduler.chapter("fake_a", "https://example.com/chapter/1")
    assert result["implemented"] is True
    assert len(result["content"]) > 0


@pytest.mark.asyncio
async def test_explore_groups_success(scheduler):
    result = await scheduler.explore_groups("fake_a")
    assert result["implemented"] is True
    assert result["groups"][0]["groupId"] == "rank_all"
    assert result["groups"][0]["sourceName"] == "Fake fake_a"


@pytest.mark.asyncio
async def test_explore_items_success(scheduler):
    result = await scheduler.explore("fake_a", "rank_all", 1)
    assert result["implemented"] is True
    assert result["items"][0]["name"] == "Ranked Book"
    assert result["items"][0]["rank"] == 1


@pytest.mark.asyncio
async def test_ordinary_source_explore_is_disabled(scheduler):
    result = await scheduler.explore("fake_b", "rank_all", 1)
    assert result["items"] == []
    assert "no explore capability" in result["debug"]["error"]


@pytest.mark.asyncio
async def test_detail_missing_plugin():
    sched = PluginScheduler(loader=PluginLoader(plugins_dir=Path("/nonexistent")), config={})
    result = await sched.detail("missing", "https://example.com")
    assert result["data"] is None
    assert "not found" in str(result["debug"].get("error", "")).lower()


def test_scheduler_injects_access_bridge_client(scheduler, monkeypatch):
    class FakeAccessBridgeClient:
        pass

    monkeypatch.setattr(
        "app.services.access_bridge.client.AccessBridgeClient",
        FakeAccessBridgeClient,
    )

    ctx = scheduler._make_ctx("fake_a")

    assert isinstance(ctx._access_bridge, FakeAccessBridgeClient)


def test_scheduler_enables_search_provider_from_access_strategy(tmp_path):
    plugin_dir = _make_fake_plugin(tmp_path, "fake_search_provider")
    metadata_path = plugin_dir / "metadata.yaml"
    text = metadata_path.read_text(encoding="utf-8")
    text += "\naccessStrategy:\n  search: search_provider\n"
    metadata_path.write_text(text, encoding="utf-8")
    sched = PluginScheduler(
        loader=PluginLoader(plugins_dir=tmp_path),
        config={"source_timeout_seconds": 8.0},
    )

    ctx = sched._make_ctx("fake_search_provider")

    assert ctx.allow_search_provider is True






