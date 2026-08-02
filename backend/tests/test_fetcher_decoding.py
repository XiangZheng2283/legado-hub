from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.source_plugins.fetcher import Fetcher
from app.source_plugins.scheduler import PluginScheduler


def test_legacy_iso_header_falls_back_to_gbk() -> None:
    response = httpx.Response(
        200,
        content="天启预报".encode("gbk"),
        headers={"content-type": "text/html; charset=ISO-8859-1"},
    )

    assert Fetcher()._decode_response_text(response) == "天启预报"


def test_toc_timeout_uses_existing_hard_source_limit() -> None:
    scheduler = object.__new__(PluginScheduler)
    scheduler.config = {
        "source_timeout_seconds": 8.0,
        "source_hard_timeout_seconds": 25.0,
    }
    plugin = SimpleNamespace(metadata=SimpleNamespace(browser={}))

    assert scheduler.toc_timeout_for_plugin(plugin) == 25.0


@pytest.mark.asyncio
async def test_impersonated_fetch_persists_response_cookies(monkeypatch) -> None:
    response = SimpleNamespace(
        status_code=200,
        url="https://www.0xs.net/txt_1/30.html",
        text="<html></html>",
        content=b"<html></html>",
        headers=httpx.Headers({"set-cookie": "uid=test-user; Path=/"}),
    )

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, *args, **kwargs):
            return response

    import curl_cffi.requests

    monkeypatch.setattr(curl_cffi.requests, "AsyncSession", lambda **kwargs: FakeSession())
    fetcher = Fetcher()

    await fetcher._fetch_raw_impersonate(
        response.url,
        "GET",
        None,
        None,
        None,
        {},
        10,
        "chrome131",
        proxy=False,
    )

    assert fetcher.cookies_for_domain("www.0xs.net") == {"uid": "test-user"}
