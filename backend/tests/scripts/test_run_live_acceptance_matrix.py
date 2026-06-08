"""Tests for run_live_acceptance_matrix.py helpers."""

from types import SimpleNamespace

import pytest

from app.services.plugin_auth_repository import PluginAuthRepository
from scripts.run_live_acceptance_matrix import (
    apply_cookie_header,
    apply_browser_cookie_json,
    clear_plugin_cookies,
    cookie_domains_for_plugin,
    normalize_playwright_cookie_file,
    open_browser_challenges,
    parse_cookie_header,
    resolve_cookie_header,
)


def _scheduler_with_plugin() -> SimpleNamespace:
    metadata = SimpleNamespace(
        id="69shuba_com",
        name="69书吧",
        auth={"cookieDomains": ["69shuba.com", "www.69shuba.com"]},
        domains=["69shuba.cx"],
        base_urls=["https://www.69shuba.com"],
        browser={"verificationUrl": "https://www.69shuba.com/newhot_0_1_1.htm"},
        domain_profiles=[
            {"domains": ["www.69shuba.cx"]},
        ],
    )
    return SimpleNamespace(_plugins={"69shuba_com": SimpleNamespace(metadata=metadata)})


def test_parse_cookie_header_ignores_invalid_parts():
    assert parse_cookie_header("cf_clearance=ok; sid=1; invalid; theme = dark ") == {
        "cf_clearance": "ok",
        "sid": "1",
        "theme": "dark",
    }


def test_resolve_cookie_header_from_env(monkeypatch):
    monkeypatch.setenv("LEGADO_TEST_COOKIE", "cf_clearance=from-env")

    assert resolve_cookie_header(cookie_header_env="LEGADO_TEST_COOKIE") == "cf_clearance=from-env"


def test_resolve_cookie_header_from_file(tmp_path):
    cookie_file = tmp_path / "cookie.txt"
    cookie_file.write_text("cf_clearance=from-file\n", encoding="utf-8")

    assert resolve_cookie_header(cookie_header_file=str(cookie_file)) == "cf_clearance=from-file"


def test_resolve_cookie_header_rejects_multiple_sources():
    with pytest.raises(ValueError, match="use only one"):
        resolve_cookie_header(cookie_header="a=b", cookie_header_env="LEGADO_TEST_COOKIE")


def test_cookie_domains_for_plugin_uses_metadata_domains():
    domains = cookie_domains_for_plugin(_scheduler_with_plugin(), "69shuba_com")

    assert domains == [
        "69shuba.com",
        "69shuba.cx",
        "www.69shuba.com",
        "www.69shuba.cx",
    ]


def test_apply_cookie_header_saves_to_explicit_domains(tmp_path):
    repo = PluginAuthRepository(tmp_path / "auth.db")

    result = apply_cookie_header(
        scheduler=_scheduler_with_plugin(),
        plugin_ids=["69shuba_com"],
        cookie_header="cf_clearance=ok; sid=1",
        cookie_domains=[".69shuba.com"],
        repository=repo,
    )

    assert result == {
        "cookieNames": ["cf_clearance", "sid"],
        "appliedDomains": {"69shuba_com": ["69shuba.com"]},
    }
    assert repo.get_cookies("69shuba_com") == {
        "69shuba.com": {"cf_clearance": "ok", "sid": "1"}
    }


def test_normalize_playwright_cookie_file_accepts_helper_payload(tmp_path):
    cookie_file = tmp_path / "session.cookies.json"
    cookie_file.write_text(
        '{"cookies":[{"domain":".69shuba.com","name":"cf_clearance","value":"ok"}]}',
        encoding="utf-8",
    )

    assert normalize_playwright_cookie_file(str(cookie_file)) == {
        "69shuba.com": {"cf_clearance": "ok"}
    }


def test_apply_browser_cookie_json_saves_domains_from_file(tmp_path):
    repo = PluginAuthRepository(tmp_path / "auth.db")
    cookie_file = tmp_path / "session.cookies.json"
    cookie_file.write_text(
        '[{"domain":"www.69shuba.com","name":"cf_clearance","value":"ok"}]',
        encoding="utf-8",
    )

    result = apply_browser_cookie_json(
        plugin_ids=["69shuba_com"],
        cookie_json_path=str(cookie_file),
        repository=repo,
    )

    assert result["cookieNames"] == ["cf_clearance"]
    assert result["appliedDomains"] == {"69shuba_com": ["www.69shuba.com"]}
    assert repo.get_cookies("69shuba_com") == {
        "www.69shuba.com": {"cf_clearance": "ok"}
    }


def test_open_browser_challenges_starts_helper():
    class FakeChallengeService:
        def create_for_plugin(self, plugin, **kwargs):
            return {
                "sessionId": "s1",
                "openUrl": "https://www.69shuba.com/newhot_0_1_1.htm",
                "cookieDomains": ["69shuba.com"],
            }

        def record_browser_helper(self, session_id, helper):
            self.recorded = (session_id, helper)

    class FakeHelperService:
        def start(self, session):
            return {"started": True, "cookieFile": "cookies.json", "openUrl": session["openUrl"]}

    result = open_browser_challenges(
        scheduler=_scheduler_with_plugin(),
        plugin_ids=["69shuba_com"],
        challenge_service=FakeChallengeService(),
        helper_service=FakeHelperService(),
    )

    assert result[0]["sessionId"] == "s1"
    assert result[0]["helper"]["started"] is True


def test_clear_plugin_cookies_requires_selected_plugins(tmp_path):
    repo = PluginAuthRepository(tmp_path / "auth.db")

    with pytest.raises(ValueError, match="requires at least one --plugin"):
        clear_plugin_cookies([], repository=repo)


def test_clear_plugin_cookies_removes_existing_state(tmp_path):
    repo = PluginAuthRepository(tmp_path / "auth.db")
    repo.set_cookies("69shuba_com", {"69shuba.com": {"cf_clearance": "old"}})

    result = clear_plugin_cookies(["69shuba_com"], repository=repo)

    assert result == {"clearedPlugins": ["69shuba_com"]}
    assert repo.get_cookies("69shuba_com") == {}


def test_apply_cookie_header_requires_selected_plugins(tmp_path):
    repo = PluginAuthRepository(tmp_path / "auth.db")

    with pytest.raises(ValueError, match="requires at least one --plugin"):
        apply_cookie_header(
            scheduler=_scheduler_with_plugin(),
            plugin_ids=[],
            cookie_header="cf_clearance=ok",
            repository=repo,
        )
