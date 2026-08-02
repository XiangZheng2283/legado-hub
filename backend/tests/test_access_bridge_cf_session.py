from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.services.access_bridge.client import AccessBridgeClient, LocalChromiumPlaywrightAdapter
from app.services.access_bridge.config import DEFAULT_BROWSER_IMPERSONATE
from app.services.access_bridge.models import AccessFetchRequest, AccessFetchResult
from app.source_plugins.context import PluginContext
from app.source_plugins.challenges import looks_like_cloudflare_challenge
from app.source_plugins.errors import CloudflareRequired, FetchHttp4xx, FetchNetworkError, RateLimited
from app.source_plugins.loader import PluginLoader


def test_cloudflare_detection_is_case_insensitive() -> None:
    assert looks_like_cloudflare_challenge('<script src="/cloudflare/challenge-platform/scripts/jsd/main.js"></script>')


def test_cloudflare_insights_script_is_not_a_challenge() -> None:
    assert not looks_like_cloudflare_challenge(
        '<script src="https://static.cloudflareinsights.com/beacon.min.js"></script>'
    )


def test_browser_post_dict_uses_form_encoding(tmp_path) -> None:
    adapter = _ReusableBrowserAdapter(tmp_path)

    assert adapter._request_payload({"searchkey": "天命之上"}) == {
        "form": {"searchkey": "天命之上"}
    }


def test_browser_profile_ignores_state_from_another_user_agent(tmp_path) -> None:
    adapter = _ReusableBrowserAdapter(tmp_path)
    request = AccessFetchRequest(
        plugin_id="example",
        url="https://example.test/",
        profile_id="example-profile",
    )
    adapter.profile_store.write_storage_state_by_id(request.profile_id, {"cookies": []})

    assert adapter._read_storage_state(request, "new-agent") is None

    adapter.profile_store.write_user_agent_by_id(request.profile_id, "new-agent")
    assert adapter._read_storage_state(request, "new-agent") == {"cookies": []}


@pytest.mark.asyncio
async def test_browser_challenge_resets_profile_and_retries_once() -> None:
    class ChallengeThenOkAdapter:
        def __init__(self) -> None:
            self.calls = 0
            self.reset_ids: list[str] = []

        async def fetch(self, request) -> AccessFetchResult:
            self.calls += 1
            challenged = self.calls == 1
            return AccessFetchResult(
                ok=not challenged,
                final_url=request.url,
                html="challenge" if challenged else "ok",
                challenge={"detected": challenged},
                profile_id=request.profile_id,
            )

        def reset_profile(self, profile_id: str) -> None:
            self.reset_ids.append(profile_id)

    adapter = ChallengeThenOkAdapter()
    client = AccessBridgeClient(adapter=adapter)
    request = AccessFetchRequest(
        plugin_id="example",
        url="https://example.test/",
        profile_id="example-profile",
    )

    result = await client.fetch(request)

    assert result.html == "ok"
    assert adapter.calls == 2
    assert adapter.reset_ids == ["example-profile"]


@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_id", ["96dushu_com", "kks101_com", "twkan_com"])
async def test_rate_limit_never_falls_back_to_browser(plugin_id: str) -> None:
    class RateLimitedAccess:
        async def fetch_text(self, *_args, **_kwargs) -> str:
            raise RateLimited("HTTP 429")

    class UnexpectedBrowser:
        calls = 0

        async def fetch_text(self, *_args, **_kwargs) -> str:
            self.calls += 1
            return "unexpected"

    plugin_root = Path(__file__).parents[2] / "plugins" / "sources" / "thirdparty" / plugin_id
    source = PluginLoader(plugin_root).load_all()[plugin_id].source
    browser = UnexpectedBrowser()
    ctx = SimpleNamespace(
        access=SimpleNamespace(
            http=RateLimitedAccess(),
            stealth=RateLimitedAccess(),
            browser=browser,
        )
    )

    with pytest.raises(RateLimited):
        await source._fetch(ctx, "https://example.test/chapter")

    assert browser.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plugin_id",
    ["69shuba_com", "96dushu_com", "kks101_com", "twkan_com"],
)
async def test_plugin_does_not_duplicate_host_cloudflare_browser_refresh(plugin_id: str) -> None:
    class CloudflareAccess:
        async def fetch_text(self, url: str, *_args, **_kwargs) -> str:
            raise CloudflareRequired("challenge remains after host refresh", url=url)

    class UnexpectedBrowser:
        calls = 0

        async def fetch_text(self, *_args, **_kwargs) -> str:
            self.calls += 1
            return "unexpected"

    plugin_root = Path(__file__).parents[2] / "plugins" / "sources" / "thirdparty" / plugin_id
    source = PluginLoader(plugin_root).load_all()[plugin_id].source
    browser = UnexpectedBrowser()
    ctx = SimpleNamespace(
        access=SimpleNamespace(
            http=CloudflareAccess(),
            stealth=CloudflareAccess(),
            browser=browser,
        )
    )

    with pytest.raises(CloudflareRequired):
        await source._fetch(ctx, "https://example.test/chapter")

    assert browser.calls == 0


@pytest.mark.asyncio
async def test_69shuba_tw_reuses_browser_session_through_stealth_http() -> None:
    class SessionAwareStealth:
        calls = 0

        async def fetch_text(self, url: str, *_args, **_kwargs) -> str:
            self.calls += 1
            if self.calls == 1:
                raise FetchHttp4xx("HTTP 403")
            return "stealth session"

    class SessionBrowser:
        calls = 0

        async def fetch_text(self, *_args, **_kwargs) -> str:
            self.calls += 1
            return "browser session"

    plugin_root = Path(__file__).parents[2] / "plugins" / "sources" / "thirdparty" / "69shuba_tw"
    source = PluginLoader(plugin_root).load_all()["69shuba_tw"].source
    stealth = SessionAwareStealth()
    browser = SessionBrowser()
    ctx = SimpleNamespace(
        access=SimpleNamespace(stealth=stealth, browser=browser),
    )

    assert await source._fetch(ctx, "/first") == "browser session"
    assert await source._fetch(ctx, "/second") == "stealth session"
    assert stealth.calls == 2
    assert browser.calls == 1


class _NavigationInfo:
    def __init__(self) -> None:
        async def response():
            return _BrowserResponse()

        self.value = response()


class _Navigation:
    def __init__(self) -> None:
        self.info = _NavigationInfo()

    async def __aenter__(self):
        return self.info

    async def __aexit__(self, *_args) -> None:
        return None


class _FormPage:
    def __init__(self) -> None:
        self.payload = None

    def expect_navigation(self, **_kwargs):
        return _Navigation()

    async def evaluate(self, _script, payload) -> None:
        self.payload = payload


@pytest.mark.asyncio
async def test_browser_post_dict_submits_real_page_form(tmp_path) -> None:
    adapter = _ReusableBrowserAdapter(tmp_path)
    page = _FormPage()
    request = AccessFetchRequest(
        plugin_id="example",
        url="https://example.test/search",
        method="POST",
        data={"searchkey": "天命之上"},
    )

    response = await adapter._submit_form(page, request)

    assert response.ok is True
    assert page.payload == {
        "url": "https://example.test/search",
        "fields": {"searchkey": "天命之上"},
    }


from app.source_plugins.fetcher import Fetcher


@pytest.mark.asyncio
async def test_fetcher_rejects_http_200_cloudflare_challenge() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                text=(
                    '<title>Just a moment...</title>'
                    '<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script>'
                ),
            )
        )
    )
    fetcher = Fetcher(proxy_mode="never")

    async def client_instance(_proxy_url=None):
        return client

    fetcher._client_instance = client_instance
    try:
        with pytest.raises(CloudflareRequired):
            await fetcher.fetch_text("https://example.test/chapter")
    finally:
        await client.aclose()


class _BrowserResponse:
    ok = True


class _BrowserPage:
    url = "https://example.test/chapter"

    def __init__(self) -> None:
        self.closed = False

    async def content(self) -> str:
        return "<html><body>ok</body></html>"

    async def title(self) -> str:
        return "Example"

    async def close(self) -> None:
        self.closed = True


class _BrowserContext:
    def __init__(self) -> None:
        self.page = _BrowserPage()
        self.closed = False

    async def new_page(self) -> _BrowserPage:
        return self.page

    async def cookies(self) -> list[dict]:
        return []

    async def close(self) -> None:
        self.closed = True


class _Browser:
    version = "130.0.0.0"

    def __init__(self) -> None:
        self.contexts: list[_BrowserContext] = []
        self.context_kwargs: list[dict] = []
        self.closed = False

    def is_connected(self) -> bool:
        return not self.closed

    async def new_context(self, **kwargs) -> _BrowserContext:
        context = _BrowserContext()
        self.contexts.append(context)
        self.context_kwargs.append(kwargs)
        return context

    async def close(self) -> None:
        self.closed = True


class _Playwright:
    def __init__(self) -> None:
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class _ReusableBrowserAdapter(LocalChromiumPlaywrightAdapter):
    def __init__(self, tmp_path) -> None:
        from app.services.access_bridge.config import AccessBridgeConfig

        super().__init__(AccessBridgeConfig(profile_root=tmp_path, pool_size=2))
        self.playwrights: list[_Playwright] = []
        self.browsers: list[_Browser] = []
        self.active_loads = 0
        self.max_active_loads = 0

    async def _start_playwright(self) -> _Playwright:
        playwright = _Playwright()
        self.playwrights.append(playwright)
        return playwright

    async def _connect(self, _playwright: _Playwright) -> _Browser:
        browser = _Browser()
        self.browsers.append(browser)
        return browser

    async def _load_page(self, page, _context, _request, _network_events):
        self.active_loads += 1
        self.max_active_loads = max(self.max_active_loads, self.active_loads)
        try:
            await asyncio.sleep(0.01)
            return _BrowserResponse(), ""
        finally:
            self.active_loads -= 1

    def _response_ok(self, response) -> bool:
        return response.ok

    def _detect_challenge(self, _html: str, _url: str) -> dict:
        return {"detected": False}


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
        self.last_headers: dict = {}
        self.last_impersonate = None

    async def fetch_text(self, url: str, **kwargs) -> str:
        self.calls += 1
        self.last_headers = dict(kwargs.get("headers") or {})
        self.last_impersonate = kwargs.get("impersonate")
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
    assert "Chrome/146.0.0.0" in browser.request.headers["User-Agent"]
    assert fetcher.last_headers == browser.request.headers
    assert fetcher.last_impersonate == DEFAULT_BROWSER_IMPERSONATE
    assert fetcher.cookies_for_domain("example.test")["cf_clearance"] == "clear"
    assert cookie_store.payload == {}


@pytest.mark.asyncio
async def test_stealth_cf_retry_replaces_stale_fingerprint_with_browser_fingerprint() -> None:
    fetcher = _ChallengeFetcher()
    browser = _BrowserBridge()
    ctx = PluginContext(
        fetcher=fetcher,
        plugin_id="cf_source",
        cookie_store=_MemoryCookieStore(),
        access_bridge=browser,
        proxy_mode="never",
        cookie_allowed=False,
    )

    result = await ctx.access.stealth.fetch_text(
        "https://example.test/chapter",
        impersonate="chrome120",
    )

    assert result == "ok"
    assert "Chrome/146.0.0.0" in browser.request.headers["User-Agent"]
    assert fetcher.last_headers == browser.request.headers
    assert fetcher.last_impersonate == DEFAULT_BROWSER_IMPERSONATE


@pytest.mark.asyncio
async def test_fetch_bytes_retries_with_proxy_after_direct_failure() -> None:
    fetcher = Fetcher(
        proxy_url="http://proxy.test:7890",
        proxy_mode="auto",
        proxy_config={
            "enabled": True,
            "url": "http://proxy.test:7890",
            "allowAutoRetry": True,
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("proxy_mode", "allow_auto_retry", "expected_calls"),
    [
        ("never", True, [False]),
        ("auto", False, [False]),
        ("auto", True, [False, True]),
        ("always", False, [True]),
    ],
)
async def test_fetcher_honors_proxy_mode_contract(
    proxy_mode: str,
    allow_auto_retry: bool,
    expected_calls: list[bool],
) -> None:
    fetcher = Fetcher(
        proxy_url="http://proxy.test:7890",
        proxy_mode=proxy_mode,
        proxy_config={
            "enabled": True,
            "url": "http://proxy.test:7890",
            "allowAutoRetry": allow_auto_retry,
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

    if expected_calls == [False]:
        with pytest.raises(FetchNetworkError):
            await fetcher.fetch_bytes("https://example.test/chapter.bin")
    else:
        assert await fetcher.fetch_bytes("https://example.test/chapter.bin") == b"ok"
    assert calls == expected_calls


@pytest.mark.asyncio
async def test_playwright_adapter_reuses_browser_and_isolates_contexts(tmp_path) -> None:
    adapter = _ReusableBrowserAdapter(tmp_path)
    request = AccessFetchRequest(plugin_id="example", url="https://example.test/chapter")

    first, second, third = await asyncio.gather(
        adapter.fetch(request),
        adapter.fetch(request),
        adapter.fetch(request),
    )

    assert first.ok is True
    assert second.ok is True
    assert third.ok is True
    assert len(adapter.playwrights) == 1
    assert len(adapter.browsers) == 1
    assert len(adapter.browsers[0].contexts) == 3
    assert adapter.max_active_loads == 2
    assert all("Chrome/146.0.0.0" in kwargs["user_agent"] for kwargs in adapter.browsers[0].context_kwargs)
    assert all(context.closed and context.page.closed for context in adapter.browsers[0].contexts)

    await adapter.close()

    assert adapter.browsers[0].closed is True
    assert adapter.playwrights[0].stopped is True
