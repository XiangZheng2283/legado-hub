"""Tests for Source Access Bridge client facade."""

import pytest

from app.services.access_bridge.client import AccessBridgeClient, AccessBridgeUnavailable
from app.services.access_bridge.client import BrowserlessPlaywrightAdapter, LocalChromiumPlaywrightAdapter
from app.services.access_bridge.config import AccessBridgeConfig
from app.services.access_bridge.models import AccessFetchRequest, AccessFetchResult


class FakeAdapter:
    def __init__(self):
        self.requests = []

    async def fetch(self, request: AccessFetchRequest) -> AccessFetchResult:
        self.requests.append(request)
        return AccessFetchResult(
            ok=True,
            final_url="https://example.com/book/1.htm",
            title="Example",
            html="<html><body>ok</body></html>",
            cookies=[{"domain": "example.com", "name": "sid", "value": "1"}],
            challenge={"detected": False},
            network=[],
            profile_id=request.profile_id,
        )


@pytest.mark.asyncio
async def test_access_bridge_client_uses_adapter():
    adapter = FakeAdapter()
    client = AccessBridgeClient(
        config=AccessBridgeConfig(browserless_ws="ws://browserless:3000"),
        adapter=adapter,
    )

    result = await client.fetch(AccessFetchRequest(
        plugin_id="example",
        url="https://example.com/book/1.htm",
        stage="detail",
        profile_id="example-default",
    ))

    assert result.ok is True
    assert result.html == "<html><body>ok</body></html>"
    assert adapter.requests[0].stage == "detail"


@pytest.mark.asyncio
async def test_access_bridge_client_requires_configuration_without_adapter():
    client = AccessBridgeClient(config=AccessBridgeConfig(enabled_by_env=False))

    with pytest.raises(AccessBridgeUnavailable):
        await client.fetch(AccessFetchRequest(
            plugin_id="example",
            url="https://example.com",
        ))


def test_access_bridge_client_defaults_to_local_chromium_adapter():
    client = AccessBridgeClient(config=AccessBridgeConfig(provider="chromium"))

    assert isinstance(client.adapter, LocalChromiumPlaywrightAdapter)


def test_access_bridge_client_uses_browserless_adapter_when_configured():
    client = AccessBridgeClient(
        config=AccessBridgeConfig(
            provider="browserless",
            browserless_ws="ws://browserless:3000",
        )
    )

    assert isinstance(client.adapter, BrowserlessPlaywrightAdapter)


def test_browserless_adapter_detects_cloudflare_challenge(tmp_path):
    adapter = BrowserlessPlaywrightAdapter(
        AccessBridgeConfig(
            browserless_ws="ws://browserless:3000",
            profile_root=tmp_path,
        )
    )

    challenge = adapter._detect_challenge(
        "<html><head><title>Just a moment...</title></head>"
        "<body>cf-turnstile</body></html>",
        "https://example.com",
    )

    assert challenge["detected"] is True
    assert challenge["kind"] == "cloudflare"
    assert challenge["url"] == "https://example.com"


def test_browserless_adapter_serializes_non_get_body(tmp_path):
    adapter = BrowserlessPlaywrightAdapter(
        AccessBridgeConfig(
            browserless_ws="ws://browserless:3000",
            profile_root=tmp_path,
        )
    )

    assert adapter._request_body({"keyword": "剑宗外门"}) == '{"keyword": "剑宗外门"}'
    assert adapter._request_body("keyword=test") == "keyword=test"
    assert adapter._request_body(None) is None


def test_browserless_adapter_uses_response_status_for_ok(tmp_path):
    adapter = BrowserlessPlaywrightAdapter(
        AccessBridgeConfig(
            browserless_ws="ws://browserless:3000",
            profile_root=tmp_path,
        )
    )

    assert adapter._response_ok(FakeHttpResponse(200)) is True
    assert adapter._response_ok(FakeHttpResponse(302)) is True
    assert adapter._response_ok(FakeHttpResponse(403)) is False
    assert adapter._response_ok(None) is True


def test_browserless_adapter_captures_network_events(tmp_path):
    adapter = BrowserlessPlaywrightAdapter(
        AccessBridgeConfig(
            browserless_ws="ws://browserless:3000",
            profile_root=tmp_path,
        )
    )
    page = FakePage()
    events = []

    adapter._attach_network_capture(page, events)
    request = FakeNetworkRequest()
    response = FakeNetworkResponse(request)
    page.handlers["request"](request)
    page.handlers["response"](response)

    assert events == [
        {
            "url": "https://example.com/book/1.htm",
            "method": "GET",
            "resourceType": "document",
            "requestHeaders": {"Accept": "text/html"},
            "responseHeaders": {"Content-Type": "text/html"},
            "status": 200,
        }
    ]


class FakePage:
    def __init__(self):
        self.handlers = {}

    def on(self, event: str, handler):
        self.handlers[event] = handler


class FakeNetworkRequest:
    url = "https://example.com/book/1.htm"
    method = "GET"
    resource_type = "document"
    headers = {"Accept": "text/html"}


class FakeNetworkResponse:
    url = "https://example.com/book/1.htm"
    status = 200
    headers = {"Content-Type": "text/html"}

    def __init__(self, request):
        self.request = request


class FakeHttpResponse:
    def __init__(self, status: int):
        self.status = status






