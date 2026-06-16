"""69shuba.tw output conversion behavior."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from app.source_plugins.context import PluginContext
from app.source_plugins.smoke import FixtureFetcher
from app.services.access_bridge.client import AccessBridgeClient
from app.services.access_bridge.config import AccessBridgeConfig
from app.services.access_bridge.models import AccessFetchRequest, AccessFetchResult


class FakeAccessBridgeAdapter:
    def __init__(self, browser_fetcher):
        self.browser_fetcher = browser_fetcher

    async def fetch(self, request: AccessFetchRequest) -> AccessFetchResult:
        html = await self.browser_fetcher.fetch_text(
            request.plugin_id,
            request.url,
            method=request.method,
            data=request.data,
            timeout=request.timeout_ms / 1000,
            wait_ms=request.wait_ms,
        )
        return AccessFetchResult(
            ok=True,
            final_url=request.url,
            html=html,
            cookies=[],
            profile_id=request.profile_id,
        )


class BrowserFixtureFetcher:
    def __init__(self, fetcher: FixtureFetcher):
        self.fetcher = fetcher
        self.calls = []

    async def fetch_text(self, plugin_id: str, url: str, **kwargs) -> str:
        self.calls.append({"pluginId": plugin_id, "url": url, **kwargs})
        return await self.fetcher.fetch_text(url, **kwargs)


def _load_source():
    root = Path(__file__).resolve().parents[2]
    source_path = root / "plugins" / "sources" / "69shuba_tw" / "source.py"
    spec = spec_from_file_location("test_69shuba_tw_source", source_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Source()


@pytest.mark.asyncio
async def test_69shuba_tw_search_outputs_simplified_text():
    source = _load_source()
    html = """
    <html><body>
      <table class="list-item">
        <tr>
          <td><img src="/cover.jpg" /></td>
          <td class="article">
            <a href="/book/777/">鬥破蒼穹</a>
            <span class="fs12">這是一段繁體簡介</span>
            <span class="mr15">作者: 天蠶土豆</span>
          </td>
        </tr>
      </table>
    </body></html>
    """
    fetcher = FixtureFetcher({
        "https://69shuba.tw/search/?searchkey=%E9%AC%A5%E7%A0%B4": html,
        "https://69shuba.tw/search/?searchkey=%E6%96%97%E7%A0%B4": html,
    })
    browser_fetcher = BrowserFixtureFetcher(fetcher)
    access_bridge = AccessBridgeClient(
        config=AccessBridgeConfig(provider="chromium"),
        adapter=FakeAccessBridgeAdapter(browser_fetcher),
    )
    ctx = PluginContext(
        fetcher=fetcher,
        plugin_id="69shuba_tw",
        access_bridge=access_bridge,
    )

    items = await source.search(ctx, "斗破", 1)

    # _fetch uses browser directly because 69shuba.tw enforces Cloudflare
    # browser verification that stealth cannot bypass.
    assert browser_fetcher.calls[0]["wait_ms"] >= 5000
    assert items[0]["name"] == "斗破苍穹"
    assert items[0]["author"] == "天蚕土豆"
    assert items[0]["intro"] == "这是一段繁体简介"


@pytest.mark.asyncio
async def test_69shuba_tw_toc_follows_paginated_index_pages():
    source = _load_source()
    responses = {
        "https://69shuba.tw/indexlist/347237/": """
        <html><body>
          <div id="alllist">
            <a href="/read/347237/1">第1章 石珠</a>
            <a href="/read/347237/100">第100章 回返宗门</a>
          </div>
          <a href="/indexlist/347237/2/">下一页</a>
        </body></html>
        """,
        "https://69shuba.tw/indexlist/347237/2/": """
        <html><body>
          <div id="alllist">
            <a href="/read/347237/101">第101章 再见林轻</a>
            <a href="/read/347237/102">第102章 魔门重现</a>
          </div>
        </body></html>
        """,
    }
    fetcher = FixtureFetcher(responses)
    browser_fetcher = BrowserFixtureFetcher(fetcher)
    access_bridge = AccessBridgeClient(
        config=AccessBridgeConfig(provider="chromium"),
        adapter=FakeAccessBridgeAdapter(browser_fetcher),
    )
    ctx = PluginContext(fetcher=fetcher, plugin_id="69shuba_tw", access_bridge=access_bridge)

    chapters = await source.toc(ctx, "https://69shuba.tw/indexlist/347237/")

    assert [chapter["title"] for chapter in chapters] == [
        "第1章 石珠",
        "第100章 回返宗门",
        "第101章 再见林轻",
        "第102章 魔门重现",
    ]


def test_69shuba_tw_conversion_cleans_common_taiwan_residue():
    from app.services.text_convert import to_simplified

    assert to_simplified("她捏著瓷瓶看著臺灣舊書，妳也在旁邊。") == "她捏着瓷瓶看着台湾旧书，你也在旁边。"
    assert to_simplified("著名作者的著作") == "著名作者的著作"






