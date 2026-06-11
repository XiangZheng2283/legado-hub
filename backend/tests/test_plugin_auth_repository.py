"""Tests for plugin auth and cookie repository."""

import pytest
import httpx

from app.services.access_bridge.models import AccessFetchResult
from app.services.plugin_auth_repository import PluginAuthRepository
from app.source_plugins.context import PluginContext
from app.source_plugins.fetcher import Fetcher


def test_plugin_auth_repository_cookie_roundtrip(tmp_path):
    repo = PluginAuthRepository(tmp_path / "auth.db")

    repo.set_cookies("qidian_com", {"qidian.com": {"session": "abc"}})

    assert repo.get_cookies("qidian_com") == {"qidian.com": {"session": "abc"}}
    status = repo.get_status("qidian_com")
    assert status["hasCookies"] is True
    assert status["cookieDomains"] == ["qidian.com"]

    repo.clear_cookies("qidian_com")

    assert repo.get_cookies("qidian_com") == {}
    assert repo.get_status("qidian_com")["hasCookies"] is False


def test_plugin_auth_repository_status_roundtrip(tmp_path):
    repo = PluginAuthRepository(tmp_path / "auth.db")

    repo.update_status(
        "qidian_com",
        {
            "authenticated": True,
            "accountName": "reader",
            "expiresAt": "2026-12-31T00:00:00Z",
            "message": "ok",
        },
    )

    status = repo.get_status("qidian_com")
    assert status["authenticated"] is True
    assert status["authStatus"] == "authenticated"
    assert status["accountName"] == "reader"
    assert status["expiresAt"] == "2026-12-31T00:00:00Z"


def test_context_cookie_set_persists_to_repository(tmp_path):
    repo = PluginAuthRepository(tmp_path / "auth.db")
    ctx = PluginContext(fetcher=Fetcher(), plugin_id="qidian_com", auth_repository=repo)

    ctx.cookies.set("qidian.com", {"session": "abc"})

    assert repo.get_cookies("qidian_com") == {"qidian.com": {"session": "abc"}}


@pytest.mark.asyncio
async def test_context_browser_fetch_cookies_are_persisted(tmp_path):
    repo = PluginAuthRepository(tmp_path / "auth.db")

    class FakeAccessBridge:
        async def fetch(self, request):
            return AccessFetchResult(
                ok=True,
                final_url=request.url,
                html="<html>ok</html>",
                cookies=[{"domain": ".69shuba.com", "name": "cf_clearance", "value": "ok"}],
            )

    ctx = PluginContext(
        fetcher=Fetcher(),
        plugin_id="69shuba_com",
        auth_repository=repo,
        access_bridge=FakeAccessBridge(),
    )

    text = await ctx.access.browser.fetch_text("https://www.69shuba.com/")

    assert text == "<html>ok</html>"
    assert repo.get_cookies("69shuba_com") == {"69shuba.com": {"cf_clearance": "ok"}}


@pytest.mark.asyncio
async def test_context_http_set_cookie_domain_is_persisted(tmp_path, monkeypatch):
    repo = PluginAuthRepository(tmp_path / "auth.db")

    async def fake_request(self, method, url, **kwargs):
        request = httpx.Request(method, url)
        return httpx.Response(
            200,
            text="<html>ok</html>",
            headers={"set-cookie": "cf_clearance=ok; Domain=.69shuba.com; Path=/"},
            request=request,
        )

    monkeypatch.setattr("httpx.AsyncClient.request", fake_request)
    ctx = PluginContext(fetcher=Fetcher(), plugin_id="69shuba_com", auth_repository=repo)

    text = await ctx.access.http.fetch_text("https://www.69shuba.com/newhot_0_1_1.htm")

    assert text == "<html>ok</html>"
    assert repo.get_cookies("69shuba_com") == {"69shuba.com": {"cf_clearance": "ok"}}






