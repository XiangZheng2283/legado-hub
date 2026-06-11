"""69shuba domain fallback behavior."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from app.source_plugins.context import PluginContext
from app.source_plugins.errors import CloudflareRequired
from app.source_plugins.errors import FetchNetworkError
from app.source_plugins.errors import PluginExecutionError
from app.source_plugins.errors import BrowserRequired
from app.source_plugins.smoke import FixtureFetcher
from app.services.access_bridge.search_provider import normalize_search_provider_url
from app.services.access_bridge.models import SearchProviderHit
from app.services.access_bridge.models import AccessFetchRequest, AccessFetchResult


class BrowserRequiredAccessBridge:
    async def fetch(self, request: AccessFetchRequest) -> AccessFetchResult:
        raise BrowserRequired("browser verification required", url=request.url)


class FakeAccessBridge:
    def __init__(self, html: str):
        self.html = html
        self.requests: list[AccessFetchRequest] = []

    async def fetch(self, request: AccessFetchRequest) -> AccessFetchResult:
        self.requests.append(request)
        return AccessFetchResult(
            ok=True,
            final_url=request.url,
            html=self.html,
            cookies=[],
            profile_id=request.profile_id,
        )


class HeaderRecordingFetcher:
    def __init__(self, url_to_text: dict[str, str]):
        self._url_to_text = url_to_text
        self.requests: list[dict] = []

    async def fetch_text(self, url: str, **kwargs) -> str:
        if url not in self._url_to_text:
            raise AssertionError(f"unexpected url: {url}")
        self.requests.append({"url": url, "headers": kwargs.get("headers") or {}})
        return self._url_to_text[url]

    async def fetch_json(self, url: str, **kwargs):
        import json

        return json.loads(await self.fetch_text(url, **kwargs))

    async def fetch_bytes(self, url: str, **kwargs) -> bytes:
        return (await self.fetch_text(url, **kwargs)).encode("utf-8")

    def cookies_for_domain(self, domain: str) -> dict[str, str]:
        return {}


def _load_source():
    root = Path(__file__).resolve().parents[2]
    source_path = root / "plugins" / "sources" / "69shuba_com" / "source.py"
    spec = spec_from_file_location("test_69shuba_source", source_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Source()


@pytest.mark.asyncio
async def test_69shuba_falls_back_to_mirror_and_keeps_mirror_urls():
    source = _load_source()
    html = """
    <html><body>
      <ul id="article_list_content">
        <li>
          <h3><a href="/book/123.htm">镜像书名</a></h3>
          <img src="/cover.jpg" />
          <label>作者甲</label><label>玄幻</label>
          <p class="ellipsis_2">简介</p>
          <p class="zxzj"><a>第一章</a></p>
        </li>
      </ul>
    </body></html>
    """
    fetcher = FixtureFetcher({"https://www.69shuba.cx/newhot_0_1_1.htm": html})
    ctx = PluginContext(fetcher=fetcher, plugin_id="69shuba_com")

    items = await source.explore(ctx, "newhot", 1)

    assert len(items) == 1
    assert items[0]["name"] == "镜像书名"
    assert items[0]["bookUrl"] == "https://www.69shuba.cx/book/123.htm"
    assert items[0]["coverUrl"] == "https://www.69shuba.cx/cover.jpg"
    traces = fetcher.get_traces()
    assert traces[0]["url"] == "https://www.69shuba.cx/newhot_0_1_1.htm"


@pytest.mark.asyncio
async def test_69shuba_search_uses_search_provider_bypass():
    source = _load_source()
    fetcher = FixtureFetcher({})
    ctx = PluginContext(fetcher=fetcher, plugin_id="69shuba_com")

    async def fake_search_provider(keyword, **kwargs):
        return [
            SearchProviderHit(
                title="我有一个修仙世界 - 69书吧",
                url="https://www.69shuba.com/book/12345.htm",
                provider="duckduckgo_ddgs",
                rank=1,
                matched_pattern=r"/book/\d+\.htm",
            )
        ]

    ctx.access.search_provider = fake_search_provider

    items = await source.search(ctx, "我有一个", 1)

    assert len(items) == 1
    assert items[0]["name"] == "我有一个修仙世界"
    assert items[0]["bookUrl"] == "https://www.69shuba.com/book/12345.htm"
    assert items[0]["extra"]["searchProvider"] == "source_access_bridge"
    assert all("modules/article/search.php" not in trace["url"] for trace in fetcher.get_traces())


@pytest.mark.asyncio
async def test_69shuba_search_uses_scheduler_timeout_instead_of_inner_wait_for(monkeypatch):
    source = _load_source()

    async def fake_search_provider(ctx, keyword):
        return [{"sourceId": source.id, "name": keyword, "bookUrl": "https://www.69shuba.com/book/89745.htm"}]

    async def fail_wait_for(*args, **kwargs):
        raise AssertionError("search should not use an inner timeout")

    monkeypatch.setattr(source, "_search_provider_search", fake_search_provider)
    monkeypatch.setitem(source.search.__globals__, "asyncio", type("AsyncioStub", (), {"wait_for": fail_wait_for}))
    ctx = PluginContext(fetcher=FixtureFetcher({}), plugin_id="69shuba_com")

    items = await source.search(ctx, "剑宗外门", 1)

    assert items[0]["name"] == "剑宗外门"


def test_69shuba_search_provider_normalizes_bing_encoded_urls():
    url = normalize_search_provider_url(
        "/ck/a?u=a1aHR0cHM6Ly93d3cuNjlzaHViYS5jb20vYm9vay8xMjM0NS5odG0",
        target_domain="www.69shuba.com",
        url_patterns=[r"/book/\d+\.htm"],
    )

    assert url == "https://www.69shuba.com/book/12345.htm"


def test_69shuba_search_provider_title_removes_latest_chapter_suffix():
    source = _load_source()

    assert source._clean_search_provider_title("剑宗外门最新章节列表,剑宗外门", "剑宗外门") == "剑宗外门"


@pytest.mark.asyncio
async def test_69shuba_search_provider_uses_declared_providers_once():
    source = _load_source()
    ctx = PluginContext(fetcher=FixtureFetcher({}), plugin_id="69shuba_com")
    calls = []

    async def fake_search_provider(keyword, **kwargs):
        calls.append((kwargs["target_domain"], kwargs["query_site_path"], kwargs["provider_order"]))
        return [
            SearchProviderHit(
                title="剑宗外门 - 69书吧",
                url="https://69shuba.com/book/89745",
                provider="google_html",
                rank=1,
                matched_pattern=r"/book/\d+",
            )
        ]

    ctx.access.search_provider = fake_search_provider

    items = await source._search_provider_search(ctx, "剑宗外门")

    assert len(calls) == 1
    assert calls[0] == ("www.69shuba.com", "/book", ["duckduckgo_ddgs", "bing_html", "google_html"])
    assert items[0]["name"] == "剑宗外门"
    assert items[0]["bookUrl"] == "https://www.69shuba.com/book/89745.htm"
    assert items[0]["extra"]["provider"] == "google_html"


@pytest.mark.asyncio
async def test_69shuba_search_reports_bypass_required_when_search_provider_empty():
    source = _load_source()
    ctx = PluginContext(
        fetcher=FixtureFetcher({}),
        plugin_id="69shuba_com",
    )

    async def empty_search_provider(keyword, **kwargs):
        return []

    ctx.access.search_provider = empty_search_provider

    with pytest.raises(PluginExecutionError, match="bypass returned no results"):
        await source.search(ctx, "我有一个", 1)


@pytest.mark.asyncio
async def test_69shuba_search_page_after_first_returns_empty():
    source = _load_source()
    fetcher = FixtureFetcher({})
    ctx = PluginContext(fetcher=fetcher, plugin_id="69shuba_com")

    assert await source.search(ctx, "我有一个", 2) == []
    assert fetcher.get_traces() == []


@pytest.mark.asyncio
async def test_69shuba_http_rejection_promotes_to_browser_required_when_runtime_browser_exists():
    source = _load_source()
    fetcher = FixtureFetcher({})
    ctx = PluginContext(
        fetcher=fetcher,
        plugin_id="69shuba_com",
        access_bridge=BrowserRequiredAccessBridge(),
    )

    with pytest.raises(FetchNetworkError) as exc_info:
        await source.explore(ctx, "newhot", 1)

    assert "no smoke fixture" in str(exc_info.value) or "no reachable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_69shuba_turnstile_html_raises_cloudflare_without_browser_fallback():
    source = _load_source()
    turnstile = """
    <html><body>
      <script>
        window.onloadTurnstileCallback = function () {};
      </script>
    </body></html>
    """
    fetcher = FixtureFetcher({
        "https://www.69shuba.com/newhot_0_1_1.htm": turnstile,
        "https://www.69shuba.cx/newhot_0_1_1.htm": turnstile,
    })
    ctx = PluginContext(
        fetcher=fetcher,
        plugin_id="69shuba_com",
        access_bridge=BrowserRequiredAccessBridge(),
    )

    with pytest.raises(CloudflareRequired) as exc_info:
        await source.explore(ctx, "newhot", 1)

    assert "attempted domains" in str(exc_info.value)
    assert exc_info.value.url == "https://www.69shuba.com/newhot_0_1_1.htm"


def test_69shuba_chapter_cleanup_removes_site_chrome_and_ads():
    source = _load_source()

    class DummyContext:
        def clean_html(self, html: str) -> str:
            from app.source_plugins.context import PluginContext

            return PluginContext(fetcher=FixtureFetcher({}), plugin_id="69shuba_com").clean_html(html)

    html = """
    <div class="txtnav">
      <h1>第一章 标题</h1>
      <div class="txtinfo">更新时间：忽略</div>
      <p>真正的第一段内容。</p>
      <div id="txtright">广告区域</div>
      <p>真正的第二段内容。(本章完)</p>
      <div class="contentadv">新69书吧广告</div>
      <script>loadAdv(10,0);</script>
    </div>
    """

    content = source._clean_chapter_html(DummyContext(), html)

    assert "真正的第一段内容。" in content
    assert "真正的第二段内容。" in content
    assert "第一章 标题" not in content
    assert "更新时间" not in content
    assert "广告" not in content
    assert "(本章完)" not in content


def test_69shuba_source_referer_uses_book_detail_url():
    source = _load_source()

    assert source._book_detail_referer("https://www.69shuba.com/book/90442.htm") == "https://www.69shuba.com/book/90442.htm"
    assert source._book_detail_referer("https://www.69shuba.com/book/90442/") == "https://www.69shuba.com/book/90442.htm"
    assert source._book_detail_referer("https://www.69shuba.com/txt/90442/40755363") == "https://www.69shuba.com/book/90442.htm"


@pytest.mark.asyncio
async def test_69shuba_source_requests_send_book_detail_referer():
    source = _load_source()
    detail_url = "https://www.69shuba.com/book/90442.htm"
    toc_url = "https://www.69shuba.com/book/90442/"
    chapter_url = "https://www.69shuba.com/txt/90442/40755363"
    fetcher = HeaderRecordingFetcher({
        detail_url: """
        <html><head>
          <meta property="og:novel:book_name" content="剑宗外门">
          <meta property="og:novel:author" content="作者">
        </head><body><a class="catalog-more-btn" href="/book/90442/">目录</a></body></html>
        """,
        toc_url: """
        <html><body><ul id="catalog"><li><a href="/txt/90442/40755363">第一章</a></li></ul></body></html>
        """,
        chapter_url: """
        <html><body><h1>第一章</h1><div class="txtnav"><p>正文内容</p></div></body></html>
        """,
    })
    ctx = PluginContext(fetcher=fetcher, plugin_id="69shuba_com")

    await source.detail(ctx, detail_url)
    await source.toc(ctx, toc_url)
    await source.chapter(ctx, chapter_url)

    assert [request["headers"].get("referer") for request in fetcher.requests] == [
        detail_url,
        detail_url,
        detail_url,
    ]


@pytest.mark.asyncio
async def test_69shuba_detail_extracts_complete_book_info():
    source = _load_source()
    detail_url = "https://www.69shuba.com/book/89745.htm"
    fetcher = HeaderRecordingFetcher({
        detail_url: """
        <html>
          <head>
            <meta property="og:novel:book_name" content="剑宗外门">
            <meta property="og:novel:author" content="其声喵喵然">
            <meta property="og:novel:category" content="修真武侠">
            <meta property="og:novel:status" content="连载">
            <meta property="og:novel:update_time" content="2025-11-27">
            <meta property="og:novel:latest_chapter_name" content="第389章 拔剑而已">
            <meta property="og:image" content="https://cdn.cdnshu.com/files/article/image/89/89745/89745s.jpg">
          </head>
          <body>
            <div class="booknav2">
              <h1>剑宗外门</h1>
              <p>作者：<a>其声喵喵然</a></p>
              <p>分类：<a>修真武侠</a></p>
              <p>131.43万字 | 连载</p>
              <p>更新：2025-11-27</p>
            </div>
            <div class="navtxt">
              <p>匣中风霆肃，剑起日月舒。</p>
              <p>小说关键词：剑宗外门无弹窗,剑宗外门txt全集下载</p>
            </div>
            <a class="catalog-more-btn" href="/book/89745/">目录</a>
          </body>
        </html>
        """,
    })
    ctx = PluginContext(fetcher=fetcher, plugin_id="69shuba_com")

    detail = await source.detail(ctx, detail_url)

    assert detail["name"] == "剑宗外门"
    assert detail["author"] == "其声喵喵然"
    assert detail["coverUrl"] == "https://cdn.cdnshu.com/files/article/image/89/89745/89745s.jpg"
    assert detail["kind"] == "修真武侠 / 连载"
    assert detail["lastChapter"] == "第389章 拔剑而已"
    assert detail["wordCount"] == "131.43万字"
    assert detail["tocUrl"] == "https://www.69shuba.com/book/89745/"
    assert detail["updateTime"] == "2025-11-27"
    assert detail["extra"]["status"] == "连载"
    assert "匣中风霆肃" in detail["intro"]
    assert "小说关键词" not in detail["intro"]


@pytest.mark.asyncio
async def test_69shuba_toc_sorts_reverse_catalog_by_chapter_number():
    source = _load_source()
    toc_url = "https://www.69shuba.com/book/89745/"
    fetcher = HeaderRecordingFetcher({
        toc_url: """
        <html><body>
        <ul id="catalog">
          <li><a href="/txt/89745/40274287">第3章 丹院</a></li>
          <li><a href="/txt/89745/40274286">第2章 两仪</a></li>
          <li><a href="/txt/89745/40274285">第1章 石珠</a></li>
        </ul>
        </body></html>
        """,
    })
    ctx = PluginContext(fetcher=fetcher, plugin_id="69shuba_com")

    chapters = await source.toc(ctx, toc_url)

    assert [chapter["title"] for chapter in chapters] == ["第1章 石珠", "第2章 两仪", "第3章 丹院"]
    assert [chapter["index"] for chapter in chapters] == [1, 2, 3]
