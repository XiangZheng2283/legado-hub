"""69shuba domain fallback behavior."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from app.source_plugins.context import PluginContext
from app.source_plugins.errors import CloudflareRequired
from app.source_plugins.errors import BrowserRequired
from app.source_plugins.smoke import FixtureFetcher


class BrowserChallengeFetcher:
    async def fetch_text(self, plugin_id: str, url: str, **kwargs) -> str:
        raise BrowserRequired("browser verification required", url=url)


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
async def test_69shuba_search_engine_fallback_extracts_book_urls():
    source = _load_source()
    challenge = "<!DOCTYPE html><html lang=\"en-US\"><head><title>Just a moment...</title></head></html>"
    duckduckgo = """
    <html><body>
      <a href="/l/?uddg=https%3A%2F%2Fwww.69shuba.com%2Fbook%2F12345.htm">
        我有一个修仙世界 - 69书吧
      </a>
      <a href="https://example.com/ignore">ignore</a>
    </body></html>
    """
    fetcher = FixtureFetcher({
        "https://www.69shuba.com/modules/article/search.php": challenge,
        "https://www.69shuba.cx/modules/article/search.php": challenge,
        "https://html.duckduckgo.com/html/?q=site%3Awww.69shuba.com%2Fbook+%E6%88%91%E6%9C%89%E4%B8%80%E4%B8%AA": duckduckgo,
    })
    ctx = PluginContext(fetcher=fetcher, plugin_id="69shuba_com")
    ctx.allow_search_engine_fallback = True

    items = await source.search(ctx, "我有一个", 1)

    assert len(items) == 1
    assert items[0]["name"] == "我有一个修仙世界"
    assert items[0]["bookUrl"] == "https://www.69shuba.com/book/12345.htm"
    assert items[0]["extra"]["fallback"] == "search_engine"


def test_69shuba_search_engine_normalizes_bing_encoded_urls():
    source = _load_source()

    url = source._normalize_search_engine_url(
        "/ck/a?u=a1aHR0cHM6Ly93d3cuNjlzaHViYS5jb20vYm9vay8xMjM0NS5odG0"
    )

    assert url == "https://www.69shuba.com/book/12345.htm"


@pytest.mark.asyncio
async def test_69shuba_search_still_reports_cloudflare_when_fallback_empty():
    source = _load_source()
    challenge = "<!DOCTYPE html><html lang=\"en-US\"><head><title>Just a moment...</title></head></html>"
    empty = "<html><body><a href=\"https://example.com/nope\">empty</a></body></html>"
    fetcher = FixtureFetcher({
        "https://www.69shuba.com/modules/article/search.php": challenge,
        "https://www.69shuba.cx/modules/article/search.php": challenge,
        "https://html.duckduckgo.com/html/?q=site%3Awww.69shuba.com%2Fbook+%E6%88%91%E6%9C%89%E4%B8%80%E4%B8%AA": empty,
        "https://lite.duckduckgo.com/lite/?q=site%3Awww.69shuba.com%2Fbook+%E6%88%91%E6%9C%89%E4%B8%80%E4%B8%AA": empty,
        "https://www.bing.com/search?q=site%3Awww.69shuba.com%2Fbook+%E6%88%91%E6%9C%89%E4%B8%80%E4%B8%AA": empty,
        "https://cn.bing.com/search?q=site%3Awww.69shuba.com%2Fbook+%E6%88%91%E6%9C%89%E4%B8%80%E4%B8%AA": empty,
    })
    ctx = PluginContext(fetcher=fetcher, plugin_id="69shuba_com")
    ctx.allow_search_engine_fallback = True

    with pytest.raises(BrowserRequired):
        await source.search(ctx, "我有一个", 1)


@pytest.mark.asyncio
async def test_69shuba_http_rejection_promotes_to_browser_required_when_runtime_browser_exists():
    source = _load_source()
    fetcher = FixtureFetcher({})
    ctx = PluginContext(
        fetcher=fetcher,
        plugin_id="69shuba_com",
        browser_fetcher=BrowserChallengeFetcher(),
    )

    with pytest.raises(BrowserRequired) as exc_info:
        await source.explore(ctx, "newhot", 1)

    assert "attempted domains" in str(exc_info.value)
    assert exc_info.value.url == "https://www.69shuba.com/newhot_0_1_1.htm"


@pytest.mark.asyncio
async def test_69shuba_turnstile_html_promotes_to_browser_required_when_runtime_browser_exists():
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
        browser_fetcher=BrowserChallengeFetcher(),
    )

    with pytest.raises(BrowserRequired) as exc_info:
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


def test_69shuba_chapter_referer_uses_book_catalog_url():
    source = _load_source()

    assert source._chapter_referer("https://www.69shuba.com/txt/90442/40755363") == "https://www.69shuba.com/book/90442/"
