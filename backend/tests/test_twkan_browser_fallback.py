"""twkan browser fallback behavior."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from app.source_plugins.context import PluginContext
from app.source_plugins.errors import BrowserRequired, FetchNetworkError


class NetworkFailFetcher:
    async def fetch_text(self, *args, **kwargs):
        raise FetchNetworkError("TLS connect error")

    def cookies_for_domain(self, domain: str):
        return {}

    def get_traces(self):
        return []


class BrowserChallengeFetcher:
    async def fetch_text(self, plugin_id: str, url: str, **kwargs) -> str:
        raise BrowserRequired("browser verification required", url=url)


def _load_source():
    root = Path(__file__).resolve().parents[2]
    source_path = root / "plugins" / "sources" / "twkan_com" / "source.py"
    spec = spec_from_file_location("test_twkan_source", source_path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Source()


@pytest.mark.asyncio
async def test_twkan_network_error_uses_browser_fallback_and_reports_challenge():
    source = _load_source()
    ctx = PluginContext(
        fetcher=NetworkFailFetcher(),
        plugin_id="twkan_com",
        browser_fetcher=BrowserChallengeFetcher(),
    )

    with pytest.raises(BrowserRequired) as exc_info:
        await source.explore(ctx, "hot", 1)

    assert exc_info.value.url == "https://twkan.com/novels/hot"
