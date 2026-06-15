"""Tests for SourceAccessBridge facade behaviour."""

import pytest

from app.services.access_bridge.facade import SourceAccessBridge


class _FakeFetcher:
    def __init__(self):
        self.calls: list[dict] = []

    async def fetch_text(self, url, *, proxy=True, **kwargs):
        self.calls.append({"url": url, "proxy": proxy})
        return ""


class _FakeCookieJar:
    def _persist(self):
        pass


class _FakeCtx:
    def __init__(self, proxy_mode="auto", proxy_url=""):
        self.plugin_id = "test"
        self.proxy_mode = proxy_mode
        self.proxy_url = proxy_url
        self._fetcher = _FakeFetcher()
        self._access_bridge = None
        self._traces = []
        self.cookies = _FakeCookieJar()
        self.access = SourceAccessBridge(self)

    def trace(self, stage, url="", message="", data=None):
        self._traces.append({"stage": stage, "url": url, "message": message, "data": data})


@pytest.mark.asyncio
async def test_search_provider_uses_proxy_when_plugin_mode_always():
    ctx = _FakeCtx(proxy_mode="always", proxy_url="http://proxy.example:7890")
    access = SourceAccessBridge(ctx)

    await access.search_provider(
        "keyword",
        target_domain="example.com",
        url_patterns=[r"/book/\d+"],
        provider_order=["bing_html"],
    )

    assert ctx._fetcher.calls
    assert all(call["proxy"] is True for call in ctx._fetcher.calls)


@pytest.mark.asyncio
async def test_search_provider_does_not_use_proxy_when_plugin_mode_never():
    ctx = _FakeCtx(proxy_mode="never", proxy_url="http://proxy.example:7890")
    access = SourceAccessBridge(ctx)

    await access.search_provider(
        "keyword",
        target_domain="example.com",
        url_patterns=[r"/book/\d+"],
        provider_order=["bing_html"],
    )

    assert ctx._fetcher.calls
    assert all(call["proxy"] is False for call in ctx._fetcher.calls)


@pytest.mark.asyncio
async def test_search_provider_allows_caller_override():
    ctx = _FakeCtx(proxy_mode="never", proxy_url="http://proxy.example:7890")
    access = SourceAccessBridge(ctx)

    await access.search_provider(
        "keyword",
        target_domain="example.com",
        url_patterns=[r"/book/\d+"],
        provider_order=["bing_html"],
        proxy=True,
    )

    assert ctx._fetcher.calls
    assert all(call["proxy"] is True for call in ctx._fetcher.calls)
