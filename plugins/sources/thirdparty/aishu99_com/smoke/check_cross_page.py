"""Verify that a chapter split across reader pages matches the full TXT."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import urldefrag

PLUGIN_DIR = Path(__file__).resolve().parents[1]
BACKEND = Path(__file__).resolve().parents[5] / "backend"
sys.path.insert(0, str(BACKEND))

from app.source_plugins.context import PluginContext  # noqa: E402
from app.source_plugins.loader import PluginLoader  # noqa: E402
from app.source_plugins.smoke import FixtureFetcher, _fixture_map, load_smoke_spec  # noqa: E402


async def main() -> None:
    plugin = PluginLoader(plugins_dir=PLUGIN_DIR.parent).load_all()[PLUGIN_DIR.name]
    spec = load_smoke_spec(PLUGIN_DIR)
    ctx = PluginContext(
        fetcher=FixtureFetcher(_fixture_map(PLUGIN_DIR, spec, plugin.capabilities)),
        plugin_id=plugin.metadata.id,
    )
    chapters = await plugin.source.toc(ctx, spec["fixtures"]["toc"]["url"])
    chapter_url = chapters[3]["chapterUrl"]
    actual = await plugin.source.chapter(ctx, chapter_url)
    page_url, _ = urldefrag(chapter_url)
    expected_title, expected = await plugin.source._download_chapter(ctx, page_url, 4, chapters[3]["title"])
    assert actual["title"] == expected_title
    assert actual["content"] == expected
    print(f"OK: {actual['title']} ({len(expected)} chars) spans reader pages 1-2")


if __name__ == "__main__":
    asyncio.run(main())
