from __future__ import annotations

from pathlib import Path

import pytest

from app.services.library_books import LibraryBooksService
from app.source_plugins.context import PluginContext
from app.source_plugins.loader import PluginLoader
from app.source_plugins.smoke import FixtureFetcher, _fixture_map, load_smoke_spec


PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "sources" / "thirdparty"


@pytest.mark.parametrize(
    ("plugin_id", "expected_chapters"),
    (("ixdzs8_com", 1663), ("czbooks_net", 2475)),
)
async def test_source_fields_survive_subscription_payload(
    plugin_id: str,
    expected_chapters: int,
) -> None:
    plugin = PluginLoader(plugins_dir=PLUGIN_ROOT).load_all()[plugin_id]
    plugin_dir = PLUGIN_ROOT / plugin_id
    spec = load_smoke_spec(plugin_dir)
    fetcher = FixtureFetcher(_fixture_map(plugin_dir, spec, plugin.capabilities))
    ctx = PluginContext(fetcher=fetcher, plugin_id=plugin_id)

    search_items = await plugin.source.search(ctx, spec["keyword"], 1)
    item = dict(search_items[0])
    item.setdefault("sourceName", plugin.metadata.name)
    detail = await plugin.source.detail(ctx, item["bookUrl"])

    for field in ("sourceId", "name", "author", "bookUrl", "tocUrl", "lastChapter", "bookStatus"):
        assert item.get(field), f"search field missing: {field}"
    assert item["chapterCount"] == expected_chapters
    assert detail["chapterCount"] == expected_chapters
    assert detail["bookStatus"]
    assert "<br" not in detail["intro"].lower()

    group = {
        "candidateId": f"test-{plugin_id}",
        "name": item["name"],
        "author": item["author"],
        "items": [item],
    }
    payload = LibraryBooksService()._payload_from_group(group)
    source = payload["sources"][0]
    assert payload["bookStatus"]
    assert payload["totalChaptersAtSubscribe"] == expected_chapters
    for field in ("bookId", "sourceId", "sourceName", "bookUrl", "tocUrl", "lastChapter", "bookStatus"):
        assert source.get(field), f"subscription source field missing: {field}"
