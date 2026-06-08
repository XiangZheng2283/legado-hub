"""Tests for Browser Bridge search-engine capability."""

import pytest

from app.services.browser_bridge.search_engine import (
    build_provider_urls,
    normalize_search_engine_url,
    parse_search_engine_results,
    search_site,
)


def test_build_provider_urls_uses_site_query():
    urls = build_provider_urls(
        "剑宗外门",
        target_domain="www.69shuba.com",
        provider_order=["duckduckgo_html", "bing_html"],
        query_site_path="/book",
    )

    assert urls == [
        (
            "duckduckgo_html",
            "https://html.duckduckgo.com/html/?q=site%3Awww.69shuba.com%2Fbook+%E5%89%91%E5%AE%97%E5%A4%96%E9%97%A8",
        ),
        (
            "bing_html",
            "https://www.bing.com/search?q=site%3Awww.69shuba.com%2Fbook+%E5%89%91%E5%AE%97%E5%A4%96%E9%97%A8",
        ),
    ]


def test_normalize_search_engine_url_accepts_direct_and_redirects():
    patterns = [r"/book/\d+\.htm"]

    direct = normalize_search_engine_url(
        "https://www.69shuba.com/book/12345.htm",
        target_domain="www.69shuba.com",
        url_patterns=patterns,
    )
    duckduckgo = normalize_search_engine_url(
        "/l/?uddg=https%3A%2F%2Fwww.69shuba.com%2Fbook%2F12345.htm",
        target_domain="www.69shuba.com",
        url_patterns=patterns,
    )
    bing = normalize_search_engine_url(
        "/ck/a?u=a1aHR0cHM6Ly93d3cuNjlzaHViYS5jb20vYm9vay8xMjM0NS5odG0",
        target_domain="www.69shuba.com",
        url_patterns=patterns,
    )

    assert direct == "https://www.69shuba.com/book/12345.htm"
    assert duckduckgo == "https://www.69shuba.com/book/12345.htm"
    assert bing == "https://www.69shuba.com/book/12345.htm"


def test_parse_search_engine_results_extracts_links_and_text_urls():
    html = """
    <html><body>
      <a href="/l/?uddg=https%3A%2F%2Fwww.69shuba.com%2Fbook%2F12345.htm">剑宗外门 最新章节</a>
      <a href="https://example.com/ignore">ignore</a>
      <script>var u = "https://www.69shuba.com/book/67890.htm"</script>
    </body></html>
    """

    hits = parse_search_engine_results(
        html,
        provider="duckduckgo_html",
        target_domain="www.69shuba.com",
        url_patterns=[r"/book/\d+\.htm"],
    )

    assert [hit.url for hit in hits] == [
        "https://www.69shuba.com/book/12345.htm",
        "https://www.69shuba.com/book/67890.htm",
    ]
    assert hits[0].title == "剑宗外门 最新章节"
    assert hits[0].matched_pattern == r"/book/\d+\.htm"


@pytest.mark.asyncio
async def test_search_site_returns_first_provider_hits():
    calls = []

    async def fetch_text(url: str):
        calls.append(url)
        if "duckduckgo" in url:
            return """
            <a href="/l/?uddg=https%3A%2F%2Fwww.69shuba.com%2Fbook%2F12345.htm">剑宗外门</a>
            """
        return ""

    hits = await search_site(
        "剑宗外门",
        target_domain="www.69shuba.com",
        url_patterns=[r"/book/\d+\.htm"],
        provider_order=["duckduckgo_html", "bing_html"],
        fetch_text=fetch_text,
        query_site_path="/book",
    )

    assert len(hits) == 1
    assert hits[0].url == "https://www.69shuba.com/book/12345.htm"
    assert len(calls) == 1
