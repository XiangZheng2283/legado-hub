"""Tests for plugin auth and cookie repository."""

import pytest
import httpx

from app.services.access_bridge.models import AccessFetchResult
from app.services.plugin_auth_repository import PluginAuthRepository
from app.source_plugins.context import PluginContext
from app.source_plugins.fetcher import Fetcher


def test_plugin_auth_repository_cookie_roundtrip(tmp_path):
    repo = PluginAuthRepository(tmp_path / "auth.db")

    repo.set_cookies("example_plugin", {"example.com": {"session": "abc"}})

    assert repo.get_cookies("example_plugin") == {"example.com": {"session": "abc"}}
    status = repo.get_status("example_plugin")
    assert status["hasCookies"] is True
    assert status["cookieDomains"] == ["example.com"]

    repo.clear_cookies("example_plugin")

    assert repo.get_cookies("example_plugin") == {}
    status = repo.get_status("example_plugin")
    assert status["hasCookies"] is False
    assert status["authStatus"] == "unknown"
    assert status["accountName"] == ""


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
    ctx = PluginContext(fetcher=Fetcher(), plugin_id="example_plugin", auth_repository=repo)

    ctx.cookies.set("qidian.com", {"session": "abc"})

    assert repo.get_cookies("example_plugin") == {"qidian.com": {"session": "abc"}}


def test_qidian_context_cookie_set_persists_to_cookie_json_not_db(tmp_path):
    from app.services import plugin_cookie_file_store

    repo = PluginAuthRepository(tmp_path / "auth.db")
    plugin_cookie_file_store.clear("qidian_com")
    ctx = PluginContext(fetcher=Fetcher(), plugin_id="qidian_com", auth_repository=repo)

    ctx.cookies.set("qidian.com", {"ywguid": "g", "ywkey": "k"})

    assert plugin_cookie_file_store.load("qidian_com")["qidian.com"]["ywguid"] == "g"
    assert repo.get_cookies("qidian_com") == {}


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


def test_qidian_login_cookies_persist_across_multiple_domains(tmp_path):
    """After login, all relevant Qidian/Yuewen domains and _csrfToken are stored."""
    from app.services import plugin_cookie_file_store

    repo = PluginAuthRepository(tmp_path / "auth.db")
    jar = {
        "qidian.com": {"ywguid": "123", "ywkey": "abc", "_csrfToken": "tok"},
        "m.qidian.com": {"ywguid": "123", "ywkey": "abc"},
        "yuewen.com": {"ywguid": "123", "ywkey": "abc"},
    }

    plugin_cookie_file_store.save("qidian_com", jar)

    status = repo.get_status("qidian_com")
    assert status["hasCookies"] is True
    assert "qidian.com" in status["cookieDomains"]
    assert "yuewen.com" in status["cookieDomains"]


def test_scheduler_reloads_qidian_cookie_json_into_fetcher_after_restart(tmp_path):
    """For qidian_com, Cookie.json is the only cookie source for scheduler fetcher cookies."""
    from app.source_plugins.scheduler import PluginScheduler
    from app.services import plugin_cookie_file_store

    plugin_cookie_file_store.clear("qidian_com")
    repo = PluginAuthRepository(tmp_path / "auth.db")

    plugin_cookie_file_store.save(
        "qidian_com",
        {"qidian.com": {"ywguid": "123", "ywkey": "abc", "_csrfToken": "tok"}},
    )

    scheduler = PluginScheduler()
    fetcher = scheduler._make_fetcher_with_cookies("qidian_com", repo)

    jar = fetcher.cookies_for_domain("qidian.com")
    assert jar.get("ywguid") == "123"
    assert jar.get("ywkey") == "abc"
    assert jar.get("_csrfToken") == "tok"


def test_scheduler_non_qidian_plugin_uses_db_cookies_and_does_not_touch_cookie_json(tmp_path):
    """Non-qidian plugins continue to use the DB cookie cache and never write Cookie.json."""
    from app.source_plugins.scheduler import PluginScheduler
    from app.services import plugin_cookie_file_store

    plugin_cookie_file_store.clear("qidian_com")
    repo = PluginAuthRepository(tmp_path / "auth.db")
    repo.set_cookies(
        "some_other_source",
        {"example.com": {"session": "db_only"}},
    )

    scheduler = PluginScheduler()
    fetcher = scheduler._make_fetcher_with_cookies("some_other_source", repo)

    assert not plugin_cookie_file_store.exists("qidian_com")
    jar = fetcher.cookies_for_domain("example.com")
    assert jar.get("session") == "db_only"


def test_status_roundtrip_for_pending_state(tmp_path):
    from app.services import plugin_cookie_file_store

    repo = PluginAuthRepository(tmp_path / "auth.db")
    plugin_cookie_file_store.save("qidian_com", {"qidian.com": {"ywguid": "1", "ywkey": "2"}})
    repo.update_status(
        "qidian_com",
        {
            "authenticated": False,
            "authStatus": "pending",
            "accountName": "",
            "message": "Cookie 已保存，等待进一步校验",
            "requiredActions": ["check_auth_status"],
        },
    )

    status = repo.get_status("qidian_com")
    assert status["authenticated"] is False
    assert status["authStatus"] == "pending"
    assert status["hasCookies"] is True
