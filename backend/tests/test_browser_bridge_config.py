"""Tests for Browser Bridge configuration."""

from pathlib import Path

from app.services.browser_bridge.config import BrowserBridgeConfig


def test_browser_bridge_config_defaults(monkeypatch):
    monkeypatch.delenv("LEGADOHUB_BROWSERLESS_WS", raising=False)
    monkeypatch.delenv("LEGADOHUB_BROWSERLESS_TOKEN", raising=False)
    monkeypatch.delenv("LEGADOHUB_BROWSER_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("LEGADOHUB_BROWSER_PROFILE_ROOT", raising=False)
    monkeypatch.delenv("LEGADOHUB_BROWSER_CONNECT_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("LEGADOHUB_BROWSER_ACTION_TIMEOUT_MS", raising=False)

    config = BrowserBridgeConfig.from_env()

    assert config.provider == "browserless"
    assert config.browserless_ws == ""
    assert config.browserless_token == ""
    assert config.public_base_url == ""
    assert config.connect_timeout_ms > 0
    assert config.action_timeout_ms > 0
    assert config.profile_root.name == "browser_profiles"


def test_browser_bridge_config_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LEGADOHUB_BROWSERLESS_WS", "ws://browserless:3000")
    monkeypatch.setenv("LEGADOHUB_BROWSERLESS_TOKEN", "secret")
    monkeypatch.setenv("LEGADOHUB_BROWSER_PUBLIC_BASE_URL", "http://192.168.1.2:8765")
    monkeypatch.setenv("LEGADOHUB_BROWSER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("LEGADOHUB_BROWSER_CONNECT_TIMEOUT_MS", "1234")
    monkeypatch.setenv("LEGADOHUB_BROWSER_ACTION_TIMEOUT_MS", "5678")

    config = BrowserBridgeConfig.from_env()

    assert config.browserless_ws == "ws://browserless:3000"
    assert config.browserless_token == "secret"
    assert config.public_base_url == "http://192.168.1.2:8765"
    assert config.profile_root == Path(tmp_path / "profiles")
    assert config.connect_timeout_ms == 1234
    assert config.action_timeout_ms == 5678


def test_browser_bridge_config_invalid_int_falls_back(monkeypatch):
    monkeypatch.setenv("LEGADOHUB_BROWSER_CONNECT_TIMEOUT_MS", "oops")
    monkeypatch.setenv("LEGADOHUB_BROWSER_ACTION_TIMEOUT_MS", "-10")

    config = BrowserBridgeConfig.from_env()

    assert config.connect_timeout_ms == BrowserBridgeConfig.default_connect_timeout_ms
    assert config.action_timeout_ms == BrowserBridgeConfig.default_action_timeout_ms


def test_browser_bridge_config_enabled_requires_endpoint(monkeypatch):
    monkeypatch.delenv("LEGADOHUB_BROWSERLESS_WS", raising=False)
    assert BrowserBridgeConfig.from_env().enabled is False

    monkeypatch.setenv("LEGADOHUB_BROWSERLESS_WS", "ws://browserless:3000")
    assert BrowserBridgeConfig.from_env().enabled is True
