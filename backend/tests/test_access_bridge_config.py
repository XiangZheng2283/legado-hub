"""Tests for Source Access Bridge configuration."""

from pathlib import Path

from app.services.access_bridge.config import AccessBridgeConfig


def test_access_bridge_config_defaults(monkeypatch):
    monkeypatch.delenv("LEGADOHUB_BROWSERLESS_WS", raising=False)
    monkeypatch.delenv("LEGADOHUB_BROWSERLESS_TOKEN", raising=False)
    monkeypatch.delenv("LEGADOHUB_BROWSER_PROVIDER", raising=False)
    monkeypatch.delenv("LEGADOHUB_BROWSER_ENABLED", raising=False)
    monkeypatch.delenv("LEGADOHUB_BROWSER_PUBLIC_BASE_URL", raising=False)
    monkeypatch.delenv("LEGADOHUB_BROWSER_PROFILE_ROOT", raising=False)
    monkeypatch.delenv("LEGADOHUB_BROWSER_CONNECT_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("LEGADOHUB_BROWSER_ACTION_TIMEOUT_MS", raising=False)

    config = AccessBridgeConfig.from_env()

    assert config.provider == "chromium"
    assert config.browserless_ws == ""
    assert config.browserless_token == ""
    assert config.public_base_url == ""
    assert config.connect_timeout_ms > 0
    assert config.action_timeout_ms > 0
    assert config.profile_root.name == "browser_profiles"


def test_access_bridge_config_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LEGADOHUB_BROWSER_PROVIDER", "browserless")
    monkeypatch.setenv("LEGADOHUB_BROWSERLESS_WS", "ws://browserless:3000")
    monkeypatch.setenv("LEGADOHUB_BROWSERLESS_TOKEN", "secret")
    monkeypatch.setenv("LEGADOHUB_BROWSER_PUBLIC_BASE_URL", "http://192.168.1.2:8765")
    monkeypatch.setenv("LEGADOHUB_BROWSER_PROFILE_ROOT", str(tmp_path / "profiles"))
    monkeypatch.setenv("LEGADOHUB_BROWSER_CONNECT_TIMEOUT_MS", "1234")
    monkeypatch.setenv("LEGADOHUB_BROWSER_ACTION_TIMEOUT_MS", "5678")

    config = AccessBridgeConfig.from_env()

    assert config.browserless_ws == "ws://browserless:3000"
    assert config.browserless_token == "secret"
    assert config.public_base_url == "http://192.168.1.2:8765"
    assert config.profile_root == Path(tmp_path / "profiles")
    assert config.connect_timeout_ms == 1234
    assert config.action_timeout_ms == 5678


def test_access_bridge_config_invalid_int_falls_back(monkeypatch):
    monkeypatch.setenv("LEGADOHUB_BROWSER_CONNECT_TIMEOUT_MS", "oops")
    monkeypatch.setenv("LEGADOHUB_BROWSER_ACTION_TIMEOUT_MS", "-10")

    config = AccessBridgeConfig.from_env()

    assert config.connect_timeout_ms == AccessBridgeConfig.default_connect_timeout_ms
    assert config.action_timeout_ms == AccessBridgeConfig.default_action_timeout_ms


def test_access_bridge_config_enabled_requires_endpoint(monkeypatch):
    monkeypatch.setenv("LEGADOHUB_BROWSER_PROVIDER", "browserless")
    monkeypatch.delenv("LEGADOHUB_BROWSERLESS_WS", raising=False)
    assert AccessBridgeConfig.from_env().enabled is False

    monkeypatch.setenv("LEGADOHUB_BROWSERLESS_WS", "ws://browserless:3000")
    assert AccessBridgeConfig.from_env().enabled is True


def test_access_bridge_config_enables_embedded_chromium_by_default(monkeypatch):
    monkeypatch.delenv("LEGADOHUB_BROWSER_PROVIDER", raising=False)
    monkeypatch.delenv("LEGADOHUB_BROWSERLESS_WS", raising=False)
    monkeypatch.delenv("LEGADOHUB_BROWSER_ENABLED", raising=False)

    config = AccessBridgeConfig.from_env()

    assert config.provider == "chromium"
    assert config.enabled is True


def test_access_bridge_config_can_disable_access_bridge(monkeypatch):
    monkeypatch.setenv("LEGADOHUB_BROWSER_PROVIDER", "chromium")
    monkeypatch.setenv("LEGADOHUB_BROWSER_ENABLED", "false")

    config = AccessBridgeConfig.from_env()

    assert config.enabled is False






