"""Tests for plugin console API endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_list_plugins():
    res = client.get("/api/console/plugins")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    if data["items"]:
        item = data["items"][0]
        assert item["accessType"] in {"HTTP", "Browser"}
        assert item["sourceType"] == item["accessType"]
        assert "proxyRequired" in item


def test_get_plugin():
    # First list to find a plugin id
    list_res = client.get("/api/console/plugins")
    items = list_res.json().get("items", [])
    if not items:
        pytest.skip("No plugins installed")
    plugin_id = items[0]["pluginId"]
    res = client.get(f"/api/console/plugins/{plugin_id}")
    assert res.status_code == 200
    assert res.json()["pluginId"] == plugin_id
    assert res.json()["accessType"] in {"HTTP", "Browser"}


def test_reload_plugins():
    res = client.post("/api/console/plugins/reload")
    assert res.status_code == 200
    assert res.json()["reloaded"] is True


def test_enable_plugin():
    list_res = client.get("/api/console/plugins")
    items = list_res.json().get("items", [])
    if not items:
        pytest.skip("No plugins installed")
    plugin_id = items[0]["pluginId"]
    res = client.post(f"/api/console/plugins/{plugin_id}/enable", json={"enabled": True})
    assert res.status_code == 200
    assert res.json()["enabled"] is True


def test_smoke_plugin():
    list_res = client.get("/api/console/plugins")
    items = list_res.json().get("items", [])
    if not items:
        pytest.skip("No plugins installed")
    plugin_id = items[0]["pluginId"]
    res = client.post(f"/api/console/plugins/{plugin_id}/smoke", json={"keyword": "test"})
    assert res.status_code == 200
    assert "pass" in res.json()


def test_plugin_auth():
    list_res = client.get("/api/console/plugins")
    items = list_res.json().get("items", [])
    if not items:
        pytest.skip("No plugins installed")
    plugin_id = items[0]["pluginId"]
    res = client.get(f"/api/console/plugins/{plugin_id}/auth")
    assert res.status_code == 200
    assert "authenticated" in res.json()
    assert res.json()["mode"] == "none"


def test_browser_required_plugin_auth_returns_verification_challenge(monkeypatch, tmp_path):
    import app.api.console as console_api
    from app.services.browser_challenge import BrowserChallengeService
    from app.services.plugin_auth_repository import PluginAuthRepository

    repo = PluginAuthRepository(tmp_path / "auth.db")
    monkeypatch.setattr(console_api, "_browser_challenge_service", BrowserChallengeService(auth_repository=repo))
    monkeypatch.setattr(console_api, "PluginAuthRepository", lambda: repo)

    res = client.get("/api/console/plugins/69shuba_com/auth")

    assert res.status_code == 200
    data = res.json()
    assert data["sourceId"] == "69shuba_com"
    assert data["mode"] == "browser_verification"
    assert data["verificationStatus"] == "required"
    assert data["requiredActions"] == ["browser_verification"]
    assert data["browserChallenges"][0]["openUrl"] == "https://www.69shuba.com/newhot_0_1_1.htm"
    assert data["browserChallenges"][0]["cookieDomains"] == [
        "69shuba.com",
        "69shuba.cx",
        "www.69shuba.com",
        "www.69shuba.cx",
    ]


def test_browser_required_plugin_auth_reports_saved_cookies(monkeypatch, tmp_path):
    import app.api.console as console_api
    from app.services.browser_challenge import BrowserChallengeService
    from app.services.plugin_auth_repository import PluginAuthRepository

    repo = PluginAuthRepository(tmp_path / "auth.db")
    repo.set_cookies("69shuba_com", {"69shuba.com": {"cf_clearance": "ok"}})
    monkeypatch.setattr(console_api, "_browser_challenge_service", BrowserChallengeService(auth_repository=repo))
    monkeypatch.setattr(console_api, "PluginAuthRepository", lambda: repo)

    res = client.post("/api/console/plugins/69shuba_com/auth/check")

    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "browser_verification"
    assert data["verificationStatus"] == "cookies_saved"
    assert data["hasCookies"] is True
    assert data["requiredActions"] == ["retry_live_check"]
    assert data["browserChallenges"] == []


def test_plugin_login_and_cookie_clear():
    list_res = client.get("/api/console/plugins")
    items = list_res.json().get("items", [])
    if not items:
        pytest.skip("No plugins installed")
    plugin_id = items[0]["pluginId"]

    login_res = client.post(f"/api/console/plugins/{plugin_id}/login")
    assert login_res.status_code == 200
    assert login_res.json()["mode"] == "manual_browser"

    clear_res = client.post(f"/api/console/plugins/{plugin_id}/cookies/clear")
    assert clear_res.status_code == 200
    assert clear_res.json()["cleared"] is True


def test_plugin_live_check_preserves_browser_challenges(monkeypatch):
    import app.api.console as console_api

    class FakeLiveAcceptance:
        async def run_plugin_live_check(self, **kwargs):
            return {
                "pluginId": kwargs["plugin_id"],
                "status": "failed",
                "passed": False,
                "diagnostics": [{"stage": "runtime", "code": "BROWSER_REQUIRED", "message": "browser verification required"}],
                "browserChallenges": [
                    {
                        "stage": "runtime",
                        "reason": "BROWSER_REQUIRED",
                        "openUrl": "https://www.69shuba.com/newhot_0_1_1.htm",
                    }
                ],
            }

    monkeypatch.setattr(console_api, "_live_acceptance_service", FakeLiveAcceptance())

    res = client.post("/api/console/plugins/69shuba_com/live-check", json={"keyword": "剑宗外门"})

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "failed"
    assert data["browserChallenges"][0]["openUrl"] == "https://www.69shuba.com/newhot_0_1_1.htm"


def test_status_endpoint():
    res = client.get("/api/console/status")
    assert res.status_code == 200
    data = res.json()
    assert "pluginStats" in data
    assert "sourceStats" in data  # compatibility alias
    assert "plugins" in data  # compatibility alias


def test_legacy_admin_api_entry_not_exposed():
    res = client.get("/api/admin/status")
    assert res.status_code == 404


def test_cache_endpoint():
    res = client.get("/api/console/cache")
    assert res.status_code == 200
    data = res.json()
    assert "searchCache" in data


def test_settings_endpoint():
    res = client.get("/api/console/settings")
    assert res.status_code == 200


def test_aggregate_source_endpoint():
    res = client.get("/api/console/aggregate-source")
    assert res.status_code == 200
    data = res.json()
    assert "generated_path" in data
