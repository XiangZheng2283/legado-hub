"""Tests for Browser Bridge client facade."""

import pytest

from app.services.browser_bridge.client import BrowserBridgeClient, BrowserBridgeUnavailable
from app.services.browser_bridge.config import BrowserBridgeConfig
from app.services.browser_bridge.models import BrowserFetchRequest, BrowserFetchResult


class FakeAdapter:
    def __init__(self):
        self.requests = []

    async def fetch(self, request: BrowserFetchRequest) -> BrowserFetchResult:
        self.requests.append(request)
        return BrowserFetchResult(
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
async def test_browser_bridge_client_uses_adapter():
    adapter = FakeAdapter()
    client = BrowserBridgeClient(
        config=BrowserBridgeConfig(browserless_ws="ws://browserless:3000"),
        adapter=adapter,
    )

    result = await client.fetch(BrowserFetchRequest(
        plugin_id="example",
        url="https://example.com/book/1.htm",
        stage="detail",
        profile_id="example-default",
    ))

    assert result.ok is True
    assert result.html == "<html><body>ok</body></html>"
    assert adapter.requests[0].stage == "detail"


@pytest.mark.asyncio
async def test_browser_bridge_client_requires_configuration_without_adapter():
    client = BrowserBridgeClient(config=BrowserBridgeConfig())

    with pytest.raises(BrowserBridgeUnavailable):
        await client.fetch(BrowserFetchRequest(
            plugin_id="example",
            url="https://example.com",
        ))
