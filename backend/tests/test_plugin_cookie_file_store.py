"""Tests for plugin_cookie_file_store — scoped to qidian_com only."""

import json

import pytest

from app.services import plugin_cookie_file_store


@pytest.fixture(autouse=True)
def _clear_qidian_cookies():
    """Make sure qidian_com Cookie.json does not leak between tests."""
    plugin_cookie_file_store.clear("qidian_com")
    yield
    plugin_cookie_file_store.clear("qidian_com")


def test_save_writes_normalized_cookie_json():
    jar = {
        "qidian.com": {"ywguid": "g1", "ywkey": "k1", "_csrfToken": "tok"},
        "yuewen.com": {"ywguid": "g1"},
    }

    plugin_cookie_file_store.save("qidian_com", jar)

    path = plugin_cookie_file_store.path_for("qidian_com")
    assert path.exists()

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["pluginId"] == "qidian_com"
    assert "updatedAt" in raw
    assert raw["cookies"]["qidian.com"]["ywguid"] == "g1"
    assert raw["cookies"]["yuewen.com"]["ywguid"] == "g1"


def test_load_returns_cookie_jar():
    jar = {"qidian.com": {"ywguid": "g1", "ywkey": "k1"}}
    plugin_cookie_file_store.save("qidian_com", jar)

    loaded = plugin_cookie_file_store.load("qidian_com")

    assert loaded == jar


def test_load_missing_returns_empty_dict():
    plugin_cookie_file_store.clear("qidian_com")
    assert plugin_cookie_file_store.load("qidian_com") == {}


def test_load_malformed_returns_empty_dict(tmp_path, monkeypatch):
    path = plugin_cookie_file_store.path_for("qidian_com")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")

    assert plugin_cookie_file_store.load("qidian_com") == {}


def test_load_legacy_flat_jar_format():
    """A legacy file that stores the jar directly (without 'cookies' wrapper) should still load."""
    path = plugin_cookie_file_store.path_for("qidian_com")
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy = {"qidian.com": {"ywguid": "legacy"}}
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    loaded = plugin_cookie_file_store.load("qidian_com")
    assert loaded["qidian.com"]["ywguid"] == "legacy"


def test_clear_deletes_cookie_json():
    plugin_cookie_file_store.save("qidian_com", {"qidian.com": {"session": "abc"}})
    assert plugin_cookie_file_store.exists("qidian_com")

    plugin_cookie_file_store.clear("qidian_com")

    assert not plugin_cookie_file_store.exists("qidian_com")
    assert plugin_cookie_file_store.load("qidian_com") == {}


def test_save_drops_none_values_and_empty_domains():
    jar = {
        "qidian.com": {"ywguid": "g1", "bad": None},
        "empty.com": {},
    }
    plugin_cookie_file_store.save("qidian_com", jar)

    loaded = plugin_cookie_file_store.load("qidian_com")
    assert "bad" not in loaded.get("qidian.com", {})
    assert "empty.com" not in loaded


def test_store_is_no_op_for_non_qidian_plugins(tmp_path):
    """Cookie.json support is scoped to qidian_com; other plugins never touch the file."""
    plugin_cookie_file_store.clear("qidian_com")
    jar = {"example.com": {"session": "abc"}}

    plugin_cookie_file_store.save("other_plugin", jar)
    assert not plugin_cookie_file_store.exists("other_plugin")
    assert plugin_cookie_file_store.load("other_plugin") == {}

    # qidian_com file should remain untouched.
    assert not plugin_cookie_file_store.exists("qidian_com")
