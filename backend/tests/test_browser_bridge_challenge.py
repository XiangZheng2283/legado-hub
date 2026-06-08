"""Tests for unified Browser Bridge challenge sessions."""

from fastapi.testclient import TestClient

from app.main import app
from app.services.browser_challenge import BrowserChallengeService
from app.source_plugins.scheduler import PluginScheduler


def test_browser_challenge_actions_include_unified_open_and_callback():
    plugin = PluginScheduler()._plugins["69shuba_com"]
    session = BrowserChallengeService().create_for_plugin(
        plugin,
        stage="search",
        url="https://www.69shuba.com/newhot_0_1_1.htm",
    )

    session_id = session["sessionId"]

    assert session["actions"]["open"] == f"/api/browser/challenges/{session_id}/open"
    assert session["actions"]["callback"] == f"/api/browser/challenges/{session_id}/callback"
    assert session["actions"]["consoleOpen"] == session["actions"]["open"]
    assert session["actions"]["legadoOpen"] == session["actions"]["open"]


def test_unified_browser_challenge_open_and_callback():
    client = TestClient(app)
    created = client.post(
        "/api/console/plugins/69shuba_com/browser-challenge",
        json={"stage": "search", "url": "https://www.69shuba.com/newhot_0_1_1.htm"},
    )
    session_id = created.json()["sessionId"]

    opened = client.get(f"/api/browser/challenges/{session_id}/open")
    assert opened.status_code == 200
    assert "Browser Challenge" in opened.text

    callback = client.post(
        f"/api/browser/challenges/{session_id}/callback",
        json={"status": "verified", "cookies": [{"domain": ".69shuba.com", "name": "cf_clearance", "value": "ok"}]},
    )

    data = callback.json()
    assert data["saved"] is True
    assert data["status"] == "verified"
    assert data["clearanceDomains"] == ["69shuba.com"]


def test_unified_browser_challenge_status_alias():
    client = TestClient(app)
    created = client.post(
        "/api/console/plugins/69shuba_com/browser-challenge",
        json={"stage": "search", "url": "https://www.69shuba.com/newhot_0_1_1.htm"},
    )
    session_id = created.json()["sessionId"]

    status = client.get(f"/api/browser/challenges/{session_id}")

    assert status.status_code == 200
    assert status.json()["sessionId"] == session_id
