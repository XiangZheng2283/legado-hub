"""Tests for smoke runner."""

import pytest
from pathlib import Path

from app.source_plugins.smoke import run_smoke
from app.source_plugins.context import PluginContext
from app.source_plugins.fetcher import Fetcher
from app.source_plugins.loader import PluginLoader


def _make_fake_plugin(tmp_path: Path, plugin_id: str, fail_stage: str | None = None):
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

    if fail_stage == "search":
        search_body = 'return []'
    elif fail_stage == "chapter":
        search_body = 'return [{"sourceId": "%s", "name": "Test", "author": "A", "bookUrl": "https://example.com/book/1"}]' % plugin_id
    else:
        search_body = 'return [{"sourceId": "%s", "name": "Test", "author": "A", "bookUrl": "https://example.com/book/1"}]' % plugin_id

    if fail_stage == "chapter":
        chapter_body = 'return {"sourceId": "%s", "title": "C1", "content": "short"}' % plugin_id
    else:
        chapter_body = 'return {"sourceId": "%s", "title": "C1", "content": "This is chapter content. " * 50}' % plugin_id

    source_py = f'''
class Source:
    id = "{plugin_id}"
    name = "Fake {plugin_id}"
    contract_version = "1.0"

    async def search(self, ctx, keyword: str, page: int):
        {search_body}

    async def detail(self, ctx, book_url: str):
        return {{"sourceId": "{plugin_id}", "name": "Test", "author": "A", "bookUrl": book_url, "tocUrl": book_url}}

    async def toc(self, ctx, toc_url: str):
        return [{{"sourceId": "{plugin_id}", "index": 1, "title": "C1", "chapterUrl": "https://example.com/chapter/1"}}]

    async def chapter(self, ctx, chapter_url: str):
        {chapter_body}
'''
    (d / "source.py").write_text(source_py, encoding="utf-8")
    return d


@pytest.fixture
def passing_plugin(tmp_path):
    _make_fake_plugin(tmp_path, "passing")
    loader = PluginLoader(plugins_dir=tmp_path)
    plugins = loader.load_all()
    return plugins["passing"]


@pytest.fixture
def failing_search_plugin(tmp_path):
    _make_fake_plugin(tmp_path, "fail_search", fail_stage="search")
    loader = PluginLoader(plugins_dir=tmp_path)
    plugins = loader.load_all()
    return plugins["fail_search"]


@pytest.fixture
def failing_chapter_plugin(tmp_path):
    _make_fake_plugin(tmp_path, "fail_chapter", fail_stage="chapter")
    loader = PluginLoader(plugins_dir=tmp_path)
    plugins = loader.load_all()
    return plugins["fail_chapter"]


@pytest.mark.asyncio
async def test_smoke_pass(passing_plugin):
    ctx = PluginContext(fetcher=Fetcher(), plugin_id=passing_plugin.metadata.id)
    result = await run_smoke(passing_plugin, ctx, keyword="test")
    assert result["pass"] is True
    assert result["stages"]["search"]["status"] == "ok"
    assert result["stages"]["detail"]["status"] == "ok"
    assert result["stages"]["toc"]["status"] == "ok"
    assert result["stages"]["chapter"]["status"] == "ok"


@pytest.mark.asyncio
async def test_smoke_fail_search(failing_search_plugin):
    ctx = PluginContext(fetcher=Fetcher(), plugin_id=failing_search_plugin.metadata.id)
    result = await run_smoke(failing_search_plugin, ctx, keyword="test")
    assert result["pass"] is False
    assert result["stages"]["search"]["status"] in ("error", "ok")
    if result["stages"]["search"]["status"] == "ok":
        assert result["stages"]["search"]["count"] == 0


@pytest.mark.asyncio
async def test_smoke_fail_chapter_too_short(failing_chapter_plugin):
    ctx = PluginContext(fetcher=Fetcher(), plugin_id=failing_chapter_plugin.metadata.id)
    result = await run_smoke(failing_chapter_plugin, ctx, keyword="test")
    assert result["pass"] is False
    assert any("short" in (e.get("message", "")).lower() for e in result["errors"])
