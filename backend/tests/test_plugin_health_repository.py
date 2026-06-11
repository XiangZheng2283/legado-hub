"""Tests for plugin health repository."""

import pytest
from pathlib import Path

from app.services.plugin_health_repository import PluginHealthRepository


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test_plugin_health.db"


@pytest.fixture
def repo(tmp_db):
    return PluginHealthRepository(db_path=tmp_db)


def test_ensure_plugin_creates_record(repo):
    repo.ensure_plugin("fixture_source", name="测试插件", enabled=True, health_status="unknown")
    p = repo.get_plugin("fixture_source")
    assert p is not None
    assert p["pluginId"] == "fixture_source"
    assert p["pluginName"] == "测试插件"
    assert p["enabled"] is True
    assert p["healthStatus"] == "unknown"


def test_ensure_plugin_updates_existing(repo):
    repo.ensure_plugin("fixture_source", name="Old Name", enabled=True)
    repo.ensure_plugin("fixture_source", name="New Name", enabled=False)
    p = repo.get_plugin("fixture_source")
    assert p["pluginName"] == "New Name"
    assert p["enabled"] is False


def test_set_enabled(repo):
    repo.ensure_plugin("fixture_source", name="测试插件", enabled=True)
    repo.set_enabled("fixture_source", False)
    p = repo.get_plugin("fixture_source")
    assert p["enabled"] is False


def test_set_proxy_mode(repo):
    repo.ensure_plugin("fixture_source", name="测试插件")
    repo.set_proxy_mode("fixture_source", "forced")
    p = repo.get_plugin("fixture_source")
    assert p["proxyMode"] == "forced"


def test_record_attempt(repo):
    repo.ensure_plugin("fixture_source")
    repo.record_attempt(
        source_id="fixture_source",
        stage="search",
        url="http://example.com",
        direct_status="success",
        proxy_status="-",
        proxy_used=False,
        latency_ms=123,
        error="",
        result="",
    )
    attempts = repo.get_attempts("fixture_source")
    assert len(attempts) == 1
    assert attempts[0]["stage"] == "search"
    assert attempts[0]["url"] == "http://example.com"
    assert attempts[0]["latencyMs"] == 123


def test_record_failure(repo):
    repo.ensure_plugin("fixture_source")
    repo.record_failure("fixture_source", "search", "connection timeout")
    p = repo.get_plugin("fixture_source")
    assert p["failureCount"] == 1
    assert "connection timeout" in p["lastError"]


def test_record_failure_hard_disables(repo):
    repo.ensure_plugin("fixture_source", enabled=True)
    repo.record_failure("fixture_source", "search", "hard error", is_hard_failure=True)
    p = repo.get_plugin("fixture_source")
    assert p["enabled"] is False
    assert p["healthStatus"] == "disabled"
    assert "hard error" in p["failureReason"]


def test_record_success(repo):
    repo.ensure_plugin("fixture_source")
    repo.record_failure("fixture_source", "search", "error")
    repo.record_success("fixture_source", latency_ms=200)
    p = repo.get_plugin("fixture_source")
    assert p["successCount"] == 1
    assert p["healthStatus"] == "healthy"


def test_get_plugins_with_filter(repo):
    repo.ensure_plugin("a", name="Alpha", enabled=True, health_status="healthy")
    repo.ensure_plugin("b", name="Beta", enabled=False, health_status="disabled")
    all_plugins = repo.get_plugins()
    assert len(all_plugins) == 2
    enabled = repo.get_plugins(enabled_only=True)
    assert len(enabled) == 1
    assert enabled[0]["pluginId"] == "a"
    healthy = repo.get_plugins(health_status="healthy")
    assert len(healthy) == 1


def test_get_stats(repo):
    repo.ensure_plugin("a", name="Alpha", enabled=True, health_status="healthy")
    repo.ensure_plugin("b", name="Beta", enabled=False, health_status="disabled")
    stats = repo.get_stats()
    assert stats["total"] == 2
    assert stats["enabled"] == 1
    assert stats["healthy"] == 1
    assert stats["disabled"] == 1


def test_update_test_result(repo):
    repo.ensure_plugin("fixture_source")
    repo.update_test_result("fixture_source", {"pass": True, "stage": "search"})
    p = repo.get_plugin("fixture_source")
    assert p["lastTestResult"] == {"pass": True, "stage": "search"}


def test_no_old_table_references_in_active_code():
    """Ensure repository module does not reference legacy table names."""
    import inspect
    source = inspect.getsource(PluginHealthRepository)
    assert "source_health" not in source
    assert "source_attempts" not in source
    assert "source_repository" not in source






