"""69shuba.tw output conversion behavior."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from app.source_plugins.context import PluginContext
from app.source_plugins.smoke import FixtureFetcher


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
    fetcher = FixtureFetcher({"https://69shuba.tw/search/?searchkey=%E9%AC%A5%E7%A0%B4": html})
    browser_fetcher = BrowserFixtureFetcher(fetcher)
    ctx = PluginContext(
        fetcher=fetcher,
        plugin_id="69shuba_tw",
        browser_fetcher=browser_fetcher,
    )

    items = await source.search(ctx, "斗破", 1)

    assert browser_fetcher.calls[0]["url"] == "https://69shuba.tw/search/?searchkey=%E9%AC%A5%E7%A0%B4"
    assert items[0]["name"] == "斗破苍穹"
    assert items[0]["author"] == "天蚕土豆"
    assert items[0]["intro"] == "这是一段繁体简介"


def test_69shuba_tw_conversion_cleans_common_taiwan_residue():
    from app.services.text_convert import to_simplified

    assert to_simplified("她捏著瓷瓶看著臺灣舊書，妳也在旁邊。") == "她捏着瓷瓶看着台湾旧书，你也在旁边。"
    assert to_simplified("著名作者的著作") == "著名作者的著作"
