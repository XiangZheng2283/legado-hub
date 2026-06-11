"""Tests for controlled fetch wrapper."""

import pytest
import httpx

from app.source_plugins.fetcher import Fetcher
from app.source_plugins.errors import BrowserRequired, CloudflareRequired, FetchHttp4xx, FetchHttp5xx, RateLimited


@pytest.fixture
def fetcher():
    return Fetcher()


@pytest.mark.asyncio
async def test_fetch_text_with_mock(monkeypatch):
    fetcher = Fetcher()
    called = {}

    async def fake_request(self, method, url, **kwargs):
        called["url"] = url
        called["method"] = method
        request = httpx.Request(method, url)
        response = httpx.Response(200, text="<html>hello</html>", request=request)
        return response

    monkeypatch.setattr(
        "httpx.AsyncClient.request",
        fake_request,
    )
    text = await fetcher.fetch_text("https://example.com")
    assert text == "<html>hello</html>"


@pytest.mark.asyncio
async def test_fetch_json(monkeypatch):
    fetcher = Fetcher()

    async def fake_request(self, method, url, **kwargs):
        request = httpx.Request(method, url)
        return httpx.Response(200, text='{"data": 1}', request=request)

    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)
    data = await fetcher.fetch_json("https://example.com")
    assert data == {"data": 1}


@pytest.mark.asyncio
async def test_http_404_raises(monkeypatch):
    fetcher = Fetcher()

    async def fake_request(self, method, url, **kwargs):
        request = httpx.Request(method, url)
        return httpx.Response(404, text="not found", request=request)

    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)
    with pytest.raises(FetchHttp4xx):
        await fetcher.fetch_text("https://example.com/missing")


@pytest.mark.asyncio
async def test_aegis_challenge_raises_browser_required(monkeypatch):
    fetcher = Fetcher()

    async def fake_request(self, method, url, **kwargs):
        request = httpx.Request(method, url)
        return httpx.Response(403, text="<script>window.axCfg={challenge:'/aegis_challenge_object/x.js',verify:'/aegis_challenge_verify'}</script>", request=request)

    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)
    with pytest.raises(BrowserRequired) as exc_info:
        await fetcher.fetch_text("https://69shuba.tw/")
    assert exc_info.value.url == "https://69shuba.tw/"


@pytest.mark.asyncio
async def test_turnstile_challenge_raises_cloudflare_required(monkeypatch):
    fetcher = Fetcher()

    async def fake_request(self, method, url, **kwargs):
        request = httpx.Request(method, url)
        return httpx.Response(
            403,
            text="<script>window.onloadTurnstileCallback=function(){}</script>",
            request=request,
        )

    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)
    with pytest.raises(CloudflareRequired) as exc_info:
        await fetcher.fetch_text("https://www.69shuba.com/")
    assert exc_info.value.url == "https://www.69shuba.com/"


@pytest.mark.asyncio
async def test_http_500_raises(monkeypatch):
    fetcher = Fetcher()

    async def fake_request(self, method, url, **kwargs):
        request = httpx.Request(method, url)
        return httpx.Response(500, text="error", request=request)

    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)
    with pytest.raises(FetchHttp5xx):
        await fetcher.fetch_text("https://example.com/error")


@pytest.mark.asyncio
async def test_rate_limit_429_raises(monkeypatch):
    fetcher = Fetcher()

    async def fake_request(self, method, url, **kwargs):
        request = httpx.Request(method, url)
        return httpx.Response(429, text="rate limited", request=request)

    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)
    with pytest.raises(RateLimited):
        await fetcher.fetch_text("https://example.com")


def test_cookie_jar():
    fetcher = Fetcher()
    fetcher.set_cookie("example.com", "session", "abc123")
    assert fetcher.cookies_for_domain("example.com") == {"session": "abc123"}
    fetcher.clear_cookies("example.com")
    assert fetcher.cookies_for_domain("example.com") == {}


def test_parent_domain_cookie_applies_to_subdomain():
    fetcher = Fetcher()
    fetcher.set_cookie(".69shuba.com", "cf_clearance", "ok")
    fetcher.set_cookie("www.69shuba.com", "session", "site")

    header = fetcher._get_cookie_header("https://www.69shuba.com/newhot_0_1_1.htm")

    assert "cf_clearance=ok" in header
    assert "session=site" in header


def test_subdomain_cookie_does_not_apply_to_parent_domain():
    fetcher = Fetcher()
    fetcher.set_cookie("www.69shuba.com", "session", "site")

    header = fetcher._get_cookie_header("https://69shuba.com/newhot_0_1_1.htm")

    assert header == ""


def test_set_cookie_domain_attribute_is_persisted_as_parent_domain():
    request = httpx.Request("GET", "https://www.69shuba.com/")
    response = httpx.Response(
        200,
        headers={"set-cookie": "cf_clearance=ok; Domain=.69shuba.com; Path=/"},
        request=request,
    )
    fetcher = Fetcher()

    fetcher._update_cookies(response)

    assert fetcher.cookies_for_domain("69shuba.com") == {"cf_clearance": "ok"}
    assert "cf_clearance=ok" in fetcher._get_cookie_header("https://www.69shuba.com/book/1.htm")


def test_decode_response_text_prefers_html_meta_charset_over_header():
    body = '<html><head><meta charset="gbk"></head><body>剑宗外门</body></html>'.encode("gbk")
    response = type("Response", (), {
        "content": body,
        "text": body.decode("utf-8", errors="replace"),
        "headers": {"content-type": "text/html; charset=utf-8"},
    })()
    fetcher = Fetcher()

    assert "剑宗外门" in fetcher._decode_response_text(response)






