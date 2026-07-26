from __future__ import annotations

import pytest

from app.services.access_bridge.models import AccessFetchResult
from app.source_plugins.context import PluginContext
from app.source_plugins.errors import CloudflareRequired, FetchNetworkError
from app.source_plugins.fetcher import Fetcher


class _MemoryCookieStore:
    def __init__(self) -> None:
        self.payload: dict = {}

    def load(self, _plugin_id: str) -> dict:
        return self.payload

    def save(self, _plugin_id: str, payload: dict) -> None:
        self.payload = payload

    def clear(self, _plugin_id: str) -> None:
        self.payload = {}


class _ChallengeFetcher:
    def __init__(self) -> None:
        self._cookies: dict[str, dict[str, str]] = {}
        self.calls = 0

    async def fetch_text(self, url: str, **_kwargs) -> str:
        self.calls += 1
        if self.cookies_for_domain("example.test").get("cf_clearance") != "clear":
            raise CloudflareRequired("challenge", url=url)
        return "ok"

    def cookies_for_domain(self, domain: str) -> dict[str, str]:
        return dict(self._cookies.get(self._normalize_cookie_domain(domain), {}))

    def cookie_snapshot(self) -> dict[str, dict[str, str]]:
        return {domain: dict(cookies) for domain, cookies in self._cookies.items()}

    def set_cookie(self, domain: str, name: str, value: str) -> None:
        self._cookies.setdefault(self._normalize_cookie_domain(domain), {})[name] = value

    def clear_cookies(self, domain: str | None = None) -> None:
        if domain is None:
            self._cookies.clear()
        else:
            self._cookies.pop(self._normalize_cookie_domain(domain), None)

    def _normalize_cookie_domain(self, domain: str) -> str:
        return str(domain or "").lstrip(".").lower()

    def get_traces(self) -> list[dict]:
        return []


class _BrowserBridge:
    def __init__(self) -> None:
        self.request = None

    async def fetch(self, request):
        self.request = request
        return AccessFetchResult(
            # Cloudflare may answer the initial navigation with 403 even when
            # the browser subsequently clears the challenge and sets a token.
            ok=False,
            final_url=request.url,
            html="ready",
            cookies=[{"domain": "example.test", "name": "cf_clearance", "value": "clear"}],
            challenge={"detected": False},
            profile_id=request.profile_id,
        )


@pytest.mark.asyncio
async def test_http_cf_challenge_uses_browser_cookie_then_retries_once() -> None:
    fetcher = _ChallengeFetcher()
    browser = _BrowserBridge()
    cookie_store = _MemoryCookieStore()
    ctx = PluginContext(
        fetcher=fetcher,
        plugin_id="cf_source",
        cookie_store=cookie_store,
        access_bridge=browser,
        proxy_mode="always",
        proxy_url="http://proxy.test:7890",
        cookie_allowed=False,
    )

    result = await ctx.access.http.fetch_text("https://example.test/chapter")

    assert result == "ok"
    assert fetcher.calls == 3
    assert browser.request.use_proxy is True
    assert browser.request.profile_id.startswith("cf_source-example_test-")
    assert fetcher.cookies_for_domain("example.test")["cf_clearance"] == "clear"
    assert cookie_store.payload == {}


@pytest.mark.asyncio
async def test_fetch_bytes_retries_with_proxy_after_direct_failure() -> None:
    fetcher = Fetcher(
        proxy_url="http://proxy.test:7890",
        proxy_mode="auto",
        proxy_config={
            "enabled": True,
            "url": "http://proxy.test:7890",
            "retry_on_failure": True,
        },
    )
    calls: list[bool] = []

    async def fake_fetch_raw(*_args, proxy: bool = True, **_kwargs):
        calls.append(proxy)
        if not proxy:
            raise FetchNetworkError("connection timeout")
        response = type("Response", (), {"content": b"ok"})()
        return "", response

    fetcher._fetch_raw = fake_fetch_raw

    assert await fetcher.fetch_bytes("https://example.test/chapter.bin") == b"ok"
    assert calls == [False, True]
