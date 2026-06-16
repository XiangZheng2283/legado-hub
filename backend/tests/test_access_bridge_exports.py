"""Tests for Source Access Bridge public exports."""

from app.services.access_bridge import AccessBridgeConfig, AccessFetchRequest, SearchProviderHit
from app.services.access_bridge.client import AccessBridgeClient, AccessBridgeUnavailable
from app.services.access_bridge.search_provider import DUCKDUCKGO_LIBRARY_PROVIDER


def test_access_bridge_exports_runtime_types():
    config = AccessBridgeConfig(provider="chromium")
    client = AccessBridgeClient(config=config)
    request = AccessFetchRequest(plugin_id="example", url="https://example.com")
    hit = SearchProviderHit(title="Example", url="https://example.com/book/1.htm", provider="test")

    assert config.provider == "chromium"
    assert client.config is config
    assert request.plugin_id == "example"
    assert hit.provider == "test"
    assert issubclass(AccessBridgeUnavailable, RuntimeError)


def test_access_bridge_exports_search_provider_names():
    assert DUCKDUCKGO_LIBRARY_PROVIDER == "duckduckgo_ddgs"






