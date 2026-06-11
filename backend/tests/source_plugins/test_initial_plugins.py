"""Fixture-backed tests for initial So Novel based plugins."""

import pytest
from app.source_plugins.loader import PluginLoader
from app.source_plugins.context import PluginContext
from app.source_plugins.fetcher import Fetcher
from app.source_plugins.smoke import run_fixture_smoke, run_smoke
from app.services.access_bridge.models import SearchProviderHit
from app.source_plugins.errors import CloudflareRequired
from app.config import PLUGINS_DIR


def _plugin_dir(plugin_id: str):
    for candidate in (
        PLUGINS_DIR / "official" / plugin_id,
        PLUGINS_DIR / "thirdparty" / plugin_id,
        PLUGINS_DIR / plugin_id,
    ):
        if candidate.exists():
            return candidate
    return PLUGINS_DIR / plugin_id


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
async def test_shuhaige_net_search_does_not_return_generic_recommendations_when_keyword_missing(loader):
    plugin = loader.load_all().get("shuhaige_net")
    assert plugin is not None
    responses = {
        "https://m.shuhaige.tw/search.html": """
        <html><body>
        <div class="search-tip">未找到相关结果</div>
        <div class="recommend">
          <a href="/320243/">外门</a>
          <a href="/62244/">外门大师兄</a>
        </div>
        </body></html>
        """,
        "https://m.shuhaige.net/search.html": """
        <html><body><div class="search-tip">未找到相关结果</div></body></html>
        """,
        "https://www.shuhaige.net/search.html": """
        <html><body><div class="search-tip">未找到相关结果</div></body></html>
        """,
        "https://m.shuhaige.net/allvisit/1.html": "<html><body></body></html>",
        "https://m.shuhaige.net/monthvisit/1.html": "<html><body></body></html>",
        "https://m.shuhaige.net/weekvisit/1.html": "<html><body></body></html>",
    }
    ctx = _mock_ctx("shuhaige_net", responses)

    items = await plugin.source.search(ctx, "剑宗外门", 1)

    assert items == []


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
async def test_22biqu_com_search_enriches_missing_latest_from_detail(loader):
    plugin = loader.load_all().get("22biqu_com")
    assert plugin is not None
    responses = {
        "https://www.22biqu.com/ss/": """
        <html><body>
        <div class="container"><div><div><ul>
        <li><span class="s2"><a href="/book/1/">凡人修仙传</a></span><span class="s4"></span><span class="s3"></span></li>
        </ul></div></div></div>
        </body></html>
        """,
        "https://www.22biqu.com/book/1/": """
        <html><body>
        <div class="info">
          <h1>凡人修仙传</h1>
          <p>作者：忘语</p>
          <p>更新时间：2026-06-10</p>
          <p></p>
          <p><a href="/book/1/99.html">第99章 详情补齐</a></p>
          <div class="desc">一个普通山村小子。</div>
        </div>
        </body></html>
        """,
    }
    ctx = _mock_ctx("22biqu_com", responses)

    items = await plugin.source.search(ctx, "凡人修仙传", 1)

    assert len(items) >= 1
    assert items[0]["author"] == "忘语"
    assert items[0]["lastChapter"] == "第99章 详情补齐"
    assert items[0]["updateTime"] == "2026-06-10"
    assert items[0]["extra"]["detailEnriched"] is True


@pytest.mark.asyncio
async def test_kks101_com_search_accepts_direct_detail_page(loader):
    plugin = loader.load_all().get("kks101_com")
    assert plugin is not None
    html = (PLUGINS_DIR / "kks101_com" / "tests" / "fixtures" / "detail.html").read_text(encoding="utf-8")
    ctx = _mock_ctx("kks101_com", {"https://101kks.com/search": html})

    items = await plugin.source.search(ctx, "星武纪元：从凡人到大帝", 1)

    assert len(items) == 1
    assert items[0]["name"] == "星武纪元：从凡人到大帝"
    assert items[0]["bookUrl"] == "https://101kks.com/book/40419.html"
    assert items[0]["lastChapter"] == "第一百四十章 奔赴边城（下）"


@pytest.mark.asyncio
async def test_kks101_com_toc_prefers_complete_ajax_chapter_list(loader):
    plugin = loader.load_all().get("kks101_com")
    assert plugin is not None
    responses = {
        "https://101kks.com/book/9783/index.html": """
        <html><body>
        <div id="allchapter"><ul>
          <li><a href="/txt/9783/1.html">第1章 石珠</a></li>
          <li><a href="/txt/9783/575.html">第575章 虚实逆</a></li>
        </ul></div>
        </body></html>
        """,
        "https://101kks.com/ajax_novels/chapterlist/9783.html": """
        <ul>
          <li><a href="/txt/9783/1.html">第1章 石珠</a></li>
          <li><a href="/txt/9783/2.html">第2章 两仪</a></li>
          <li><a href="/txt/9783/3.html">第3章 丹院</a></li>
          <li><a href="/txt/9783/575.html">第575章 虚实逆</a></li>
        </ul>
        """,
    }
    ctx = _mock_ctx("kks101_com", responses)

    chapters = await plugin.source.toc(ctx, "https://101kks.com/book/9783/index.html")

    assert [chapter["title"] for chapter in chapters] == ["第1章 石珠", "第2章 两仪", "第3章 丹院", "第575章 虚实逆"]


@pytest.mark.asyncio
async def test_kks101_com_toc_uses_ajax_when_static_catalog_unavailable(loader):
    plugin = loader.load_all().get("kks101_com")
    assert plugin is not None
    responses = {
        "https://101kks.com/ajax_novels/chapterlist/9783.html": """
        <ul>
          <li><a href="/txt/9783/1.html">第1章 石珠</a></li>
          <li><a href="/txt/9783/2.html">第2章 两仪</a></li>
        </ul>
        """,
    }
    ctx = _mock_ctx("kks101_com", responses)

    chapters = await plugin.source.toc(ctx, "https://101kks.com/book/9783/index.html")

    assert [chapter["title"] for chapter in chapters] == ["第1章 石珠", "第2章 两仪"]


@pytest.mark.asyncio
async def test_kks101_com_chapter_preserves_paragraphs(loader):
    plugin = loader.load_all().get("kks101_com")
    assert plugin is not None
    responses = {
        "https://101kks.com/txt/9783/1.html": """
        <html><body>
          <h1>第1章 石珠</h1>
          <div class="txtnav">
            <p>第一段。</p>
            <p>第二段。</p>
          </div>
        </body></html>
        """,
    }
    ctx = _mock_ctx("kks101_com", responses)

    result = await plugin.source.chapter(ctx, "https://101kks.com/txt/9783/1.html")

    assert result["content"] == "第一段。\n\n第二段。"


@pytest.mark.asyncio
async def test_twkan_com_search_accepts_direct_detail_page(loader):
    plugin = loader.load_all().get("twkan_com")
    assert plugin is not None
    responses = {
        "https://twkan.com/search": """
        <html><head>
        <meta property="og:type" content="novel">
        <meta property="og:url" content="https://twkan.com/book/79272.html">
        <meta property="og:novel:book_name" content="劍宗外門">
        <meta property="og:novel:author" content="其聲喵喵然">
        <meta property="og:novel:category" content="武俠仙俠">
        <meta property="og:novel:status" content="連載">
        <meta property="og:novel:latest_chapter_name" content="第575章 虛實逆，鏡花影">
        <meta property="og:novel:update_time" content="2026-06-06 12:46:27">
        <meta property="og:image" content="https://twkan.com/files/article/image/79/79272/79272s.jpg">
        <meta property="og:description" content="（凡人流，無系統）匣中風霆肅，劍起日月舒。">
        </head><body></body></html>
        """
    }
    ctx = _mock_ctx("twkan_com", responses)

    items = await plugin.source.search(ctx, "剑宗外门", 1)

    assert len(items) == 1
    assert items[0]["name"] == "剑宗外门"
    assert items[0]["author"] == "其声喵喵然"
    assert items[0]["bookUrl"] == "https://twkan.com/book/79272.html"
    assert items[0]["lastChapter"] == "第575章 虚实逆，镜花影"


@pytest.mark.asyncio
async def test_twkan_com_toc_prefers_complete_ajax_chapter_list(loader):
    plugin = loader.load_all().get("twkan_com")
    assert plugin is not None
    responses = {
        "https://twkan.com/book/79272/index.html": """
        <html><body>
        <div class="catalog"><ul>
          <li><a href="/txt/79272/1">第1章 石珠</a></li>
          <li><a href="/txt/79272/575">第575章 虚实逆</a></li>
        </ul></div>
        </body></html>
        """,
        "https://twkan.com/ajax_novels/chapterlist/79272.html": """
        <ul>
          <li><a href="/txt/79272/1">第1章 石珠</a></li>
          <li><a href="/txt/79272/2">第2章 两仪</a></li>
          <li><a href="/txt/79272/3">第3章 丹院</a></li>
          <li><a href="/txt/79272/575">第575章 虚实逆</a></li>
        </ul>
        """,
    }
    ctx = _mock_ctx("twkan_com", responses)

    chapters = await plugin.source.toc(ctx, "https://twkan.com/book/79272/index.html")

    assert [chapter["title"] for chapter in chapters] == ["第1章 石珠", "第2章 两仪", "第3章 丹院", "第575章 虚实逆"]


@pytest.mark.asyncio
async def test_twkan_com_toc_uses_ajax_when_static_catalog_unavailable(loader):
    plugin = loader.load_all().get("twkan_com")
    assert plugin is not None
    responses = {
        "https://twkan.com/ajax_novels/chapterlist/98218.html": """
        <ul>
          <li><a href="/txt/98218/1">第1章 外门</a></li>
          <li><a href="/txt/98218/2">第2章 剑光</a></li>
        </ul>
        """,
    }
    ctx = _mock_ctx("twkan_com", responses)

    chapters = await plugin.source.toc(ctx, "https://twkan.com/book/98218/index.html")

    assert [chapter["title"] for chapter in chapters] == ["第1章 外门", "第2章 剑光"]


@pytest.mark.asyncio
async def test_twkan_com_toc_uses_real_ajax_id_from_static_page(loader):
    plugin = loader.load_all().get("twkan_com")
    assert plugin is not None
    responses = {
        "https://twkan.com/book/4591/index.html": """
        <html><body>
          <script>
            var chapterUrl = '/ajax_novels/chapterlist/98218.html';
          </script>
          <div class="catalog"><ul>
            <li><a href="/txt/4591/1">第1章 预览</a></li>
          </ul></div>
        </body></html>
        """,
        "https://twkan.com/ajax_novels/chapterlist/98218.html": """
        <ul>
          <li><a href="/txt/4591/1">第1章 今日宜出行</a></li>
          <li><a href="/txt/4591/2">第2章 单灵根</a></li>
        </ul>
        """,
    }
    ctx = _mock_ctx("twkan_com", responses)

    chapters = await plugin.source.toc(ctx, "https://twkan.com/book/4591/index.html")

    assert [chapter["title"] for chapter in chapters] == ["第1章 今日宜出行", "第2章 单灵根"]


@pytest.mark.asyncio
async def test_twkan_com_chapter_preserves_paragraphs(loader):
    plugin = loader.load_all().get("twkan_com")
    assert plugin is not None
    responses = {
        "https://twkan.com/txt/79272/1": """
        <html><body>
          <h1>第1章 石珠</h1>
          <div class="txtnav">
            <p>第一段。abc123.com</p>
            <p>第二段。</p>
          </div>
        </body></html>
        """,
    }
    ctx = _mock_ctx("twkan_com", responses)

    result = await plugin.source.chapter(ctx, "https://twkan.com/txt/79272/1")

    assert result["content"] == "第一段。\n\n第二段。"


@pytest.mark.asyncio
async def test_biquge365_net_toc_follows_paginated_catalog(loader):
    plugin = loader.load_all().get("biquge365_net")
    assert plugin is not None
    responses = {
        "https://m.biquge365.net/shu/679551_1/": """
        <html><body>
          <ul><li>作者：最白的乌鸦</li></ul>
          <ul>
            <li><a href="/chapter/679551/latest.html">番外三</a></li>
          </ul>
          <ul>
            <li><a href="/chapter/679551/1.html">第一章 今日宜出行，不宜作弊</a></li>
            <li><a href="/chapter/679551/2.html">第二章 单灵根</a></li>
          </ul>
          <a href="/shu/679551_2/">下一页</a>
        </body></html>
        """,
        "https://m.biquge365.net/shu/679551_2/": """
        <html><body>
          <ul><li>作者：最白的乌鸦</li></ul>
          <ul>
            <li><a href="/chapter/679551/latest.html">番外三</a></li>
          </ul>
          <ul>
            <li><a href="/chapter/679551/3.html">第三章 一看就是老实人</a></li>
            <li><a href="/chapter/679551/4.html">第四章 拿来吧你</a></li>
          </ul>
        </body></html>
        """,
    }
    ctx = _mock_ctx("biquge365_net", responses)

    chapters = await plugin.source.toc(ctx, "https://m.biquge365.net/shu/679551_1/")

    assert [chapter["title"] for chapter in chapters] == [
        "第一章 今日宜出行，不宜作弊",
        "第二章 单灵根",
        "第三章 一看就是老实人",
        "第四章 拿来吧你",
    ]


@pytest.mark.asyncio
async def test_shuhaige_net_toc_keeps_chronological_catalog_order(loader):
    plugin = loader.load_all().get("shuhaige_net")
    assert plugin is not None
    responses = {
        "https://www.shuhaige.net/16074/": """
        <html><body>
          <div id="info"><a href="/16074/132282683.html">番外三</a></div>
          <dl>
            <dt>最新章节</dt>
            <dd><a href="/16074/132282683.html">番外三</a></dd>
            <dt>章节目录</dt>
            <dd><a href="/16074/85183260.html">第一章 今日宜出行，不宜作弊</a></dd>
            <dd><a href="/16074/85183261.html">第二章 单灵根</a></dd>
            <dd><a href="/16074/132282683.html">番外三</a></dd>
          </dl>
        </body></html>
        """,
    }
    ctx = _mock_ctx("shuhaige_net", responses)

    chapters = await plugin.source.toc(ctx, "https://www.shuhaige.net/16074/")

    assert [chapter["title"] for chapter in chapters] == [
        "第一章 今日宜出行，不宜作弊",
        "第二章 单灵根",
        "番外三",
    ]


@pytest.mark.asyncio
async def test_ttkan_co_search_does_not_return_unrelated_results_when_keyword_missing(loader):
    plugin = loader.load_all().get("ttkan_co")
    assert plugin is not None
    responses = {
        "https://www.ttkan.co/novel/search": """
        <html><body>
          <div class="novel_cell">
            <a href="/novel/chapters/jianzongpangmen-chouachou"><amp-img src="cover.jpg"></amp-img></a>
            <ul>
              <li><a href="/novel/chapters/jianzongpangmen-chouachou"><h3>劍宗旁門</h3></a></li>
              <li>作者：愁啊愁</li>
              <li>簡介：這是推薦書，不是搜索命中。</li>
            </ul>
          </div>
        </body></html>
        """,
    }
    ctx = _mock_ctx("ttkan_co", responses)

    items = await plugin.source.search(ctx, "剑宗外门", 1)

    assert items == []


@pytest.mark.asyncio
async def test_twkan_com_search_provider_fallback_when_cloudflare(loader, monkeypatch):
    plugin = loader.load_all().get("twkan_com")
    assert plugin is not None
    ctx = _mock_ctx("twkan_com", {})

    async def blocked_fetch(*args, **kwargs):
        raise CloudflareRequired("Cloudflare verification required", url="https://twkan.com/search")

    async def fake_search_provider(keyword, **kwargs):
        return [
            SearchProviderHit(
                title="劍宗外門在線閱讀 - 台灣小說網",
                url="https://twkan.com/book/79272.html",
                provider="duckduckgo_ddgs",
                rank=1,
                matched_pattern=r"/book/\d+\.html",
            )
        ]

    monkeypatch.setattr(plugin.source, "_fetch", blocked_fetch)
    ctx.access.search_provider = fake_search_provider

    items = await plugin.source.search(ctx, "剑宗外门", 1)

    assert len(items) == 1
    assert items[0]["name"] == "剑宗外门"
    assert items[0]["bookUrl"] == "https://twkan.com/book/79272.html"
    assert items[0]["extra"]["searchProvider"] == "source_access_bridge"


@pytest.mark.asyncio
async def test_kks101_com_search_tries_browser_before_explore(loader, monkeypatch):
    plugin = loader.load_all().get("kks101_com")
    assert plugin is not None
    ctx = _mock_ctx("kks101_com", {})

    async def blocked_fetch(*args, **kwargs):
        raise CloudflareRequired("Cloudflare verification required", url="https://101kks.com/search")

    async def browser_html(ctx_arg, search_keyword):
        return """
        <html><head>
        <meta property="og:url" content="https://101kks.com/book/9783.html">
        <meta property="og:novel:book_name" content="劍宗外門">
        <meta property="og:novel:author" content="佚名">
        </head><body></body></html>
        """

    async def forbidden_explore(*args, **kwargs):
        raise AssertionError("explore fallback should run only after browser fallback fails")

    monkeypatch.setattr(plugin.source, "_fetch", blocked_fetch)
    monkeypatch.setattr(plugin.source, "_browser_search_html", browser_html)
    monkeypatch.setattr(plugin.source, "_search_from_explore", forbidden_explore)

    items = await plugin.source.search(ctx, "剑宗外门", 1)

    assert len(items) == 1
    assert items[0]["name"] == "剑宗外门"
    assert items[0]["bookUrl"] == "https://101kks.com/book/9783.html"


@pytest.mark.asyncio
async def test_kks101_com_search_tries_browser_when_200_challenge_page(loader, monkeypatch):
    plugin = loader.load_all().get("kks101_com")
    assert plugin is not None
    ctx = _mock_ctx("kks101_com", {"https://101kks.com/search": "<html><title>Just a moment...</title>Cloudflare</html>"})

    async def browser_html(ctx_arg, search_keyword):
        return """
        <html><head>
        <meta property="og:url" content="https://101kks.com/book/9783.html">
        <meta property="og:novel:book_name" content="劍宗外門">
        <meta property="og:novel:author" content="佚名">
        </head><body></body></html>
        """

    async def forbidden_explore(*args, **kwargs):
        raise AssertionError("explore fallback should run only after browser fallback fails")

    monkeypatch.setattr(plugin.source, "_browser_search_html", browser_html)
    monkeypatch.setattr(plugin.source, "_search_from_explore", forbidden_explore)

    items = await plugin.source.search(ctx, "剑宗外门", 1)

    assert len(items) == 1
    assert items[0]["name"] == "剑宗外门"
    assert items[0]["bookUrl"] == "https://101kks.com/book/9783.html"


@pytest.mark.asyncio
async def test_kks101_com_search_tries_explore_after_browser_fails(loader, monkeypatch):
    plugin = loader.load_all().get("kks101_com")
    assert plugin is not None
    ctx = _mock_ctx("kks101_com", {})

    async def blocked_fetch(*args, **kwargs):
        raise CloudflareRequired("Cloudflare verification required", url="https://101kks.com/search")

    async def empty_browser(ctx_arg, search_keyword):
        return ""

    async def explore_hit(ctx_arg, keyword):
        return [{
            "sourceId": "kks101_com",
            "name": "剑宗外门",
            "author": "佚名",
            "bookUrl": "https://101kks.com/book/9783.html",
        }]

    monkeypatch.setattr(plugin.source, "_fetch", blocked_fetch)
    monkeypatch.setattr(plugin.source, "_browser_search_html", empty_browser)
    monkeypatch.setattr(plugin.source, "_search_from_explore", explore_hit)

    items = await plugin.source.search(ctx, "剑宗外门", 1)

    assert len(items) == 1
    assert items[0]["name"] == "剑宗外门"
    assert items[0]["bookUrl"] == "https://101kks.com/book/9783.html"


@pytest.mark.asyncio
async def test_twkan_com_search_tries_browser_before_provider(loader, monkeypatch):
    plugin = loader.load_all().get("twkan_com")
    assert plugin is not None
    ctx = _mock_ctx("twkan_com", {})

    async def blocked_fetch(*args, **kwargs):
        raise CloudflareRequired("Cloudflare verification required", url="https://twkan.com/search")

    async def browser_html(ctx_arg, search_keyword):
        return """
        <html><head>
        <meta property="og:url" content="https://twkan.com/book/79272.html">
        <meta property="og:novel:book_name" content="劍宗外門">
        <meta property="og:novel:author" content="其聲喵喵然">
        </head><body></body></html>
        """

    async def forbidden_search_provider(*args, **kwargs):
        raise AssertionError("search provider should be used only after browser and explore fallback fail")

    monkeypatch.setattr(plugin.source, "_fetch", blocked_fetch)
    monkeypatch.setattr(plugin.source, "_browser_search_html", browser_html)
    ctx.access.search_provider = forbidden_search_provider

    items = await plugin.source.search(ctx, "剑宗外门", 1)

    assert len(items) == 1
    assert items[0]["name"] == "剑宗外门"
    assert items[0]["bookUrl"] == "https://twkan.com/book/79272.html"


@pytest.mark.asyncio
async def test_twkan_com_search_tries_browser_when_200_challenge_page(loader, monkeypatch):
    plugin = loader.load_all().get("twkan_com")
    assert plugin is not None
    ctx = _mock_ctx("twkan_com", {"https://twkan.com/search": "<html><title>Just a moment...</title>Cloudflare</html>"})

    async def browser_html(ctx_arg, search_keyword):
        return """
        <html><head>
        <meta property="og:url" content="https://twkan.com/book/79272.html">
        <meta property="og:novel:book_name" content="劍宗外門">
        <meta property="og:novel:author" content="其聲喵喵然">
        </head><body></body></html>
        """

    async def forbidden_search_provider(*args, **kwargs):
        raise AssertionError("search provider should be used only after browser and explore fallback fail")

    monkeypatch.setattr(plugin.source, "_browser_search_html", browser_html)
    ctx.access.search_provider = forbidden_search_provider

    items = await plugin.source.search(ctx, "剑宗外门", 1)

    assert len(items) == 1
    assert items[0]["name"] == "剑宗外门"
    assert items[0]["bookUrl"] == "https://twkan.com/book/79272.html"


@pytest.mark.asyncio
async def test_twkan_com_search_tries_explore_before_provider(loader, monkeypatch):
    plugin = loader.load_all().get("twkan_com")
    assert plugin is not None
    ctx = _mock_ctx("twkan_com", {})

    async def blocked_fetch(*args, **kwargs):
        raise CloudflareRequired("Cloudflare verification required", url="https://twkan.com/search")

    async def empty_browser(ctx_arg, search_keyword):
        return ""

    async def explore_hit(ctx_arg, keyword):
        return [{
            "sourceId": "twkan_com",
            "name": "剑宗外门",
            "author": "其声喵喵然",
            "bookUrl": "https://twkan.com/book/79272.html",
        }]

    async def forbidden_search_provider(*args, **kwargs):
        raise AssertionError("search provider should be used only after explore fallback fails")

    monkeypatch.setattr(plugin.source, "_fetch", blocked_fetch)
    monkeypatch.setattr(plugin.source, "_browser_search_html", empty_browser)
    monkeypatch.setattr(plugin.source, "_search_from_explore", explore_hit)
    ctx.access.search_provider = forbidden_search_provider

    items = await plugin.source.search(ctx, "剑宗外门", 1)

    assert len(items) == 1
    assert items[0]["name"] == "剑宗外门"
    assert items[0]["bookUrl"] == "https://twkan.com/book/79272.html"


@pytest.mark.asyncio
async def test_qidian_com_auth_status_requires_login_when_no_cookies(loader):
    plugin = loader.load_all().get("qidian_com")
    assert plugin is not None
    ctx = PluginContext(fetcher=Fetcher(), plugin_id="qidian_com")

    result = await plugin.source.auth_status(ctx)

    assert result["authenticated"] is False
    assert result["requiredActions"] == ["manual_login"]


@pytest.mark.asyncio
async def test_qidian_com_chapter_preview_from_mobile_fixture(loader):
    plugin = loader.load_all().get("qidian_com")
    assert plugin is not None
    responses = {
        "https://m.qidian.com/chapter/1036370336/745302300/": (_plugin_dir("qidian_com") / "tests" / "fixtures" / "chapter.html").read_text(encoding="utf-8"),
    }
    ctx = _mock_ctx("qidian_com", responses)

    result = await plugin.source.chapter(ctx, "https://m.qidian.com/chapter/1036370336/745302300/")

    assert result["title"] == "欢迎收藏"
    assert "作者大大正努力存稿中" in result["content"]
    assert result["extra"]["previewOnly"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plugin_id",
    [
        "xbiqugu_la",
        "shuhaige_net",
        "biquge365_net",
        "xbiquzw_net",
        "22biqu_com",
        "0xs_net",
        "96dushu_com",
        "dongtanxs_com",
        "kks101_com",
        "quanben5_com",
        "ranwen8_cc",
        "sudugu_org",
        "tianxibook_com",
        "ttkan_co",
        "xhytd_com",
        "xiaoshuohu_com",
        "qidian_com",
    ],
)
async def test_initial_plugins_fixture_smoke(loader, plugin_id):
    plugin = loader.load_all().get(plugin_id)
    assert plugin is not None

    result = await run_fixture_smoke(plugin, _plugin_dir(plugin_id))

    assert result["pass"] is True, result
    assert result["mode"] == "fixture"
