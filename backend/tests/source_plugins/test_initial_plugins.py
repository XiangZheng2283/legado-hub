"""Fixture-backed tests for initial So Novel based plugins."""

import pytest
from app.source_plugins.loader import PluginLoader
from app.source_plugins.context import PluginContext
from app.source_plugins.fetcher import Fetcher
from app.source_plugins.smoke import run_fixture_smoke, run_smoke
from app.config import PLUGINS_DIR


def _mock_fetcher_for_plugin(plugin_id: str, responses: dict):
    """Create a fetcher that returns canned responses for given URLs."""
    class MockFetcher:
        def __init__(self):
            self.responses = responses
            self._cookies = {}

        async def fetch_text(self, url, **kwargs):
            if url in self.responses:
                return self.responses[url]
            raise Exception(f"No mock for {url}")

        async def fetch_json(self, url, **kwargs):
            import json as _json
            return _json.loads(self.responses[url])

        async def fetch_bytes(self, url, **kwargs):
            return self.responses[url].encode("utf-8")

        async def fetch_many(self, urls, **kwargs):
            return [self.responses.get(u, "") for u in urls]

        async def close(self):
            pass

        def cookies_for_domain(self, domain):
            return {}

        def set_cookie(self, domain, name, value):
            pass

        def clear_cookies(self, domain=None):
            pass

        def get_traces(self):
            return []

    return MockFetcher()


def _mock_ctx(plugin_id: str, responses: dict):
    fetcher = _mock_fetcher_for_plugin(plugin_id, responses)
    ctx = PluginContext(fetcher=Fetcher(), plugin_id=plugin_id)
    # Replace the underlying fetcher with our mock
    ctx._fetcher = fetcher
    return ctx


@pytest.fixture
def loader():
    return PluginLoader()


@pytest.mark.asyncio
async def test_xbiqugu_la_search(loader):
    plugin = loader.load_all().get("xbiqugu_la")
    assert plugin is not None
    responses = {
        "http://www.xbiqugu.la/modules/article/waps.php": """
        <html><body>
        <form id="checkform">
        <table><tbody>
        <tr><td class="even"><a href="/book/1/">凡人修仙传</a></td><td>仙侠</td><td>忘语</td><td class="odd"><a href="/book/1/1.html">第一章</a></td><td>2024-01-01</td></tr>
        </tbody></table>
        </form>
        </body></html>
        """
    }
    ctx = _mock_ctx("xbiqugu_la", responses)
    items = await plugin.source.search(ctx, "凡人修仙传", 1)
    assert len(items) >= 1
    assert items[0]["name"] == "凡人修仙传"
    assert items[0]["author"] == "忘语"


@pytest.mark.asyncio
async def test_xbiqugu_la_detail(loader):
    plugin = loader.load_all().get("xbiqugu_la")
    responses = {
        "http://www.xbiqugu.la/book/1/": """
        <html><body>
        <div id="info"><h1>凡人修仙传</h1><p>作者：忘语</p><p>类别：仙侠</p><p>状态：完结</p><p>最新：<a href="/book/1/1.html">第一章</a></p></div>
        <div id="intro">一个普通山村小子...</div>
        <div id="fmimg"><img src="/files/1.jpg"/></div>
        </body></html>
        """
    }
    ctx = _mock_ctx("xbiqugu_la", responses)
    detail = await plugin.source.detail(ctx, "http://www.xbiqugu.la/book/1/")
    assert detail["name"] == "凡人修仙传"
    assert detail["author"] == "忘语"


@pytest.mark.asyncio
async def test_xbiqugu_la_toc(loader):
    plugin = loader.load_all().get("xbiqugu_la")
    responses = {
        "http://www.xbiqugu.la/book/1/": """
        <html><body>
        <div id="list"><dl>
        <dt>正文</dt>
        <dd><a href="/book/1/1.html">第一章</a></dd>
        <dd><a href="/book/1/2.html">第二章</a></dd>
        </dl></div>
        </body></html>
        """
    }
    ctx = _mock_ctx("xbiqugu_la", responses)
    chapters = await plugin.source.toc(ctx, "http://www.xbiqugu.la/book/1/")
    assert len(chapters) >= 2
    assert chapters[0]["title"] == "第一章"


@pytest.mark.asyncio
async def test_xbiqugu_la_chapter(loader):
    plugin = loader.load_all().get("xbiqugu_la")
    responses = {
        "http://www.xbiqugu.la/book/1/1.html": """
        <html><body>
        <div class="bookname"><h1>第一章</h1></div>
        <div id="content"><p>这是正文内容。</p><p>这是第二段。</p></div>
        </body></html>
        """
    }
    ctx = _mock_ctx("xbiqugu_la", responses)
    content = await plugin.source.chapter(ctx, "http://www.xbiqugu.la/book/1/1.html")
    assert "第一章" in content["title"]
    assert "正文" in content["content"]


@pytest.mark.asyncio
async def test_shuhaige_net_search(loader):
    plugin = loader.load_all().get("shuhaige_net")
    assert plugin is not None
    responses = {
        "https://www.shuhaige.net/search.html": """
        <html><body>
        <div id="sitembox">
        <dl><dd><h3><a href="/book/1/">凡人修仙传</a></h3></dd><dd><span>忘语</span></dd></dl>
        </div>
        </body></html>
        """
    }
    ctx = _mock_ctx("shuhaige_net", responses)
    items = await plugin.source.search(ctx, "凡人修仙传", 1)
    assert len(items) >= 1
    assert items[0]["name"] == "凡人修仙传"


@pytest.mark.asyncio
async def test_biquge365_net_search(loader):
    plugin = loader.load_all().get("biquge365_net")
    assert plugin is not None
    responses = {
        "https://www.biquge365.net/s.php": """
        <html><body>
        <div class="menu"><div><ul>
        <li><span class="name"><a href="/book/1/">凡人修仙传</a></span><span class="zuo"><a href="/author/1/">忘语</a></span></li>
        </ul></div></div>
        </body></html>
        """
    }
    ctx = _mock_ctx("biquge365_net", responses)
    items = await plugin.source.search(ctx, "凡人修仙传", 1)
    assert len(items) >= 1
    assert items[0]["name"] == "凡人修仙传"


@pytest.mark.asyncio
async def test_smoke_xbiqugu_la(loader):
    plugin = loader.load_all().get("xbiqugu_la")
    responses = {
        "http://www.xbiqugu.la/modules/article/waps.php": """
        <html><body>
        <form id="checkform">
        <table><tbody>
        <tr><td class="even"><a href="/book/1/">凡人修仙传</a></td><td>仙侠</td><td>忘语</td><td class="odd"><a href="/book/1/1.html">第一章</a></td><td>2024-01-01</td></tr>
        </tbody></table>
        </form>
        </body></html>
        """,
        "http://www.xbiqugu.la/book/1/": """
        <html><body>
        <div id="info"><h1>凡人修仙传</h1><p>作者：忘语</p><p>类别：仙侠</p><p>状态：完结</p><p>最新：<a href="/book/1/1.html">第一章</a></p></div>
        <div id="intro">一个普通山村小子...</div>
        <div id="fmimg"><img src="/files/1.jpg"/></div>
        <div id="list"><dl>
        <dt>正文</dt>
        <dd><a href="/book/1/1.html">第一章</a></dd>
        </dl></div>
        </body></html>
        """,
        "http://www.xbiqugu.la/book/1/1.html": """
        <html><body>
        <div class="bookname"><h1>第一章</h1></div>
        <div id="content"><p>这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。这是正文内容。</p></div>
        </body></html>
        """,
    }
    ctx = _mock_ctx("xbiqugu_la", responses)
    result = await run_smoke(plugin, ctx, keyword="凡人修仙传")
    assert result["pass"] is True
    assert result["stages"]["search"]["status"] == "ok"
    assert result["stages"]["chapter"]["contentLength"] >= 150


@pytest.mark.asyncio
async def test_xbiquzw_net_search(loader):
    plugin = loader.load_all().get("xbiquzw_net")
    assert plugin is not None
    responses = {
        "http://www.xbiquzw.net/modules/article/search.php": """
        <html><body>
        <div id="wrapper">
        <table><tbody>
        <tr><td><a href="/book/1/">凡人修仙传</a></td><td>第一章</td><td>忘语</td><td>2024-01-01</td></tr>
        </tbody></table>
        </div>
        </body></html>
        """
    }
    ctx = _mock_ctx("xbiquzw_net", responses)
    items = await plugin.source.search(ctx, "凡人修仙传", 1)
    assert len(items) >= 1
    assert items[0]["name"] == "凡人修仙传"


@pytest.mark.asyncio
async def test_22biqu_com_search(loader):
    plugin = loader.load_all().get("22biqu_com")
    assert plugin is not None
    responses = {
        "https://www.22biqu.com/ss/": """
        <html><body>
        <div class="container"><div><div><ul>
        <li><span class="s2"><a href="/book/1/">凡人修仙传</a></span><span class="s1">仙侠</span><span class="s4">忘语</span><span class="s5">2024-01-01</span></li>
        </ul></div></div></div>
        </body></html>
        """
    }
    ctx = _mock_ctx("22biqu_com", responses)
    items = await plugin.source.search(ctx, "凡人修仙传", 1)
    assert len(items) >= 1
    assert items[0]["name"] == "凡人修仙传"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plugin_id",
    ["xbiqugu_la", "shuhaige_net", "biquge365_net", "xbiquzw_net", "22biqu_com"],
)
async def test_initial_plugins_fixture_smoke(loader, plugin_id):
    plugin = loader.load_all().get(plugin_id)
    assert plugin is not None

    result = await run_fixture_smoke(plugin, PLUGINS_DIR / plugin_id)

    assert result["pass"] is True, result
    assert result["mode"] == "fixture"
    assert result["stages"]["search"]["count"] >= 1
    assert result["stages"]["toc"]["count"] >= 1
    assert result["stages"]["chapter"]["contentLength"] >= 150
