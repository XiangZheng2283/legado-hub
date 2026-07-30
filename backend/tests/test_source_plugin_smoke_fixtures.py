from pathlib import Path

import pytest

from app.source_plugins.context import PluginContext
from app.source_plugins.loader import PluginLoader
from app.source_plugins.smoke import (
    FixtureFetcher,
    _FixtureBrowserAdapter,
    _toc_contract_errors,
    _fixture_map,
)
from app.services.access_bridge.client import AccessBridgeClient
from app.services.access_bridge.config import AccessBridgeConfig


def test_fixture_map_loads_extra_pages(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "smoke" / "fixtures"
    fixtures_dir.mkdir(parents=True)
    for name in ("search.html", "detail.html", "toc.html", "chapter.html", "chapter-2.html"):
        (fixtures_dir / name).write_text(name, encoding="utf-8")
    spec = {
        "fixtures": {
            "search": {"url": "https://example.test/search", "file": "search.html"},
            "detail": {"url": "https://example.test/book", "file": "detail.html"},
            "toc": {"url": "https://example.test/toc", "file": "toc.html"},
            "chapter": {"url": "https://example.test/chapter", "file": "chapter.html"},
        },
        "extraFixtures": [
            {"url": "https://example.test/chapter_2", "file": "chapter-2.html"},
        ],
    }

    fixture_map = _fixture_map(tmp_path, spec)

    assert fixture_map["https://example.test/chapter_2"] == "chapter-2.html"


def test_complete_toc_contract_rejects_partial_or_duplicated_catalog() -> None:
    chapters = [
        {"index": 1, "title": "第1章", "chapterUrl": "https://example.test/1"},
        {"index": 2, "title": "第2章", "chapterUrl": "https://example.test/1"},
    ]

    errors = _toc_contract_errors(
        "example",
        chapters,
        {
            "expectedCount": 3,
            "lastTitleContains": "第3章",
            "requireUniqueChapterUrls": True,
            "requireSequentialIndexes": True,
        },
    )

    messages = [error["message"] for error in errors]
    assert "expected exactly 3 chapters, got 2" in messages
    assert "last chapter title must contain 第3章" in messages
    assert "chapter URLs must be non-empty and unique" in messages


@pytest.mark.asyncio
async def test_fixture_browser_uses_the_same_saved_page_map() -> None:
    url = "https://example.test/browser"
    fetcher = FixtureFetcher({url: "<html><body>fixture browser</body></html>"})
    bridge = AccessBridgeClient(
        config=AccessBridgeConfig(provider="chromium"),
        adapter=_FixtureBrowserAdapter(fetcher),
    )
    ctx = PluginContext(fetcher=fetcher, plugin_id="example", access_bridge=bridge)

    assert "fixture browser" in await ctx.access.browser.fetch_text(url)


def test_lingdiankanshu_chapter_fixture_preserves_paragraphs() -> None:
    plugin_dir = (
        Path(__file__).resolve().parents[2]
        / "plugins"
        / "sources"
        / "thirdparty"
        / "lingdiankanshu_com"
    )
    plugin = PluginLoader(plugins_dir=plugin_dir).load_all()[plugin_dir.name]
    html = (plugin_dir / "smoke" / "fixtures" / "chapter.html").read_text(encoding="utf-8")
    ctx = PluginContext(fetcher=FixtureFetcher({}), plugin_id=plugin_dir.name)

    content = plugin.source._chapter_content(ctx, html, "第一章")

    assert content.count("\n\n") >= 20
    assert "龙蛇大陆" in content
