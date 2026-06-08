"""Tests for HTTP runtime headers and cookie jar behavior."""

import asyncio

import httpx

from app.legado_engine.http_runtime import HttpRuntime
from app.legado_engine.models import RequestSpec


def test_http_runtime_preserves_cookie_between_requests(monkeypatch):
    seen_headers = []

    class FakeClient:
        is_closed = False

        async def get(self, url, headers=None):
            seen_headers.append(headers or {})
            if url.endswith("/login"):
                return httpx.Response(200, text="ok", headers={"Set-Cookie": "sid=abc; Path=/"}, request=httpx.Request("GET", url))
            return httpx.Response(200, text="ok", request=httpx.Request("GET", url))

        async def post(self, url, data=None, headers=None):
            return await self.get(url, headers=headers)

        async def aclose(self):
            self.is_closed = True

    runtime = HttpRuntime(cookie_jar_enabled=True)
    monkeypatch.setattr(runtime, "_make_client", lambda proxy_url=None: FakeClient())

    asyncio.run(runtime.fetch_with_proxy(RequestSpec("https://example.com/login"), source_id="s", stage="login"))
    asyncio.run(runtime.fetch_with_proxy(RequestSpec("https://example.com/book"), source_id="s", stage="detail"))

    assert seen_headers[1]["Cookie"] == "sid=abc"
