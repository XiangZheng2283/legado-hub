"""Tests for Phase 3 features: multi-object JSON, batch search, auto-disable, single-source test, admin routes."""

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rules.legado_loader import load_source_file, make_source_id
from app.services.source_repository import SourceRepository
from app.core.aggregate_config import load_aggregate_config
from app.core.source_generator import write_aggregate_source
from app.storage.db import initialize_database

client = TestClient(app)


# ---- Multi-object JSON expansion ----

def test_load_multi_object_file() -> None:
    """A file with multiple objects must return all objects."""
    path = Path("data/sources/raw/by-site/legado/bbiquge8.net.json")
    if not path.exists():
        pytest.skip("bbiquge8.net.json not found")
    objects = load_source_file(path)
    assert len(objects) > 1, "bbiquge8.net.json should contain multiple source objects"
    for obj in objects:
        assert isinstance(obj, dict)
        assert "bookSourceName" in obj or "bookSourceUrl" in obj


def test_make_source_id_collision_safe() -> None:
    assert make_source_id("example", 0, "Foo") == "example"
    assert make_source_id("example", 1, "Foo") == "example#Foo"
    assert make_source_id("example", 2, "") == "example#2"


# ---- Source repository ----

def test_source_repository_scan(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    # Create a fake repo dir with one single-object and one multi-object file
    repo_dir = tmp_path / "legado"
    repo_dir.mkdir()
    (repo_dir / "site1.json").write_text(
        json.dumps({"bookSourceName": "A", "bookSourceUrl": "https://a.com", "searchUrl": "/s?k={{key}}", "ruleSearch": {}, "ruleBookInfo": {}, "ruleToc": {}, "ruleContent": {}}),
        encoding="utf-8",
    )
    (repo_dir / "site2.json").write_text(
        json.dumps([
            {"bookSourceName": "B1", "bookSourceUrl": "https://b1.com", "searchUrl": "/s?k={{key}}", "ruleSearch": {}, "ruleBookInfo": {}, "ruleToc": {}, "ruleContent": {}},
            {"bookSourceName": "B2", "bookSourceUrl": "https://b2.com", "searchUrl": "/s?k={{key}}", "ruleSearch": {}, "ruleBookInfo": {}, "ruleToc": {}, "ruleContent": {}},
        ]),
        encoding="utf-8",
    )

    repo = SourceRepository(repo_dir=repo_dir, db_path=db_path)
    summary = repo.scan_and_index()
    assert summary["total_files"] == 2
    assert summary["total_objects"] == 3
    assert summary["indexed"] == 3

    stats = repo.get_stats()
    assert stats["total"] == 3
    assert stats["enabled"] == 3

    # Check multi-object IDs
    src_b1 = repo.get_source("site2#B1")
    assert src_b1 is not None
    assert src_b1["bookSourceName"] == "B1"
    assert src_b1["sourceIndex"] == 0

    src_b2 = repo.get_source("site2#B2")
    assert src_b2 is not None
    assert src_b2["sourceIndex"] == 1


# ---- Auto-disable on hard failure ----

def test_record_failure_disables_source(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    repo = SourceRepository(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO source_health (source_id, book_source_name, enabled, health_status) VALUES (?, ?, ?, ?)",
            ("test-src", "Test", 1, "healthy"),
        )
        conn.commit()

    repo.record_failure("test-src", "search", "unsupported syntax: <js>", is_hard_failure=True)
    src = repo.get_source("test-src")
    assert src["enabled"] is False
    assert src["healthStatus"] == "disabled"
    assert "unsupported syntax" in src["failureReason"]


def test_record_success_keeps_enabled(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    repo = SourceRepository(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO source_health (source_id, book_source_name, enabled, health_status) VALUES (?, ?, ?, ?)",
            ("test-src", "Test", 1, "unknown"),
        )
        conn.commit()

    repo.record_success("test-src", 123)
    src = repo.get_source("test-src")
    assert src["enabled"] is True
    assert src["healthStatus"] == "healthy"
    assert src["successCount"] == 1


def test_enable_all_valid_sources_preserves_hard_disabled_and_missing_fields(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    repo = SourceRepository(db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO source_health (source_id, book_source_name, enabled, health_status, failure_reason) VALUES (?, ?, ?, ?, ?)",
            [
                ("valid-unknown", "Valid Unknown", 0, "unknown", ""),
                ("valid-healthy", "Valid Healthy", 1, "healthy", ""),
                ("missing", "Missing", 0, "missing_fields", "缺少必要字段"),
                ("hard-disabled", "Hard Disabled", 0, "disabled", "[search] unsupported syntax"),
            ],
        )
        conn.commit()

    changed = repo.enable_all_valid_sources()
    assert changed >= 2
    assert repo.get_source("valid-unknown")["enabled"] is True
    assert repo.get_source("valid-healthy")["enabled"] is True
    assert repo.get_source("missing")["enabled"] is False
    assert repo.get_source("hard-disabled")["enabled"] is False


# ---- Aggregate config ----

def test_load_aggregate_config() -> None:
    config = load_aggregate_config()
    assert "name" in config
    assert "version" in config
    assert "parser_progress" in config


def test_aggregate_progress_updates_on_generation() -> None:
    write_aggregate_source()
    config = load_aggregate_config()
    progress = config["parser_progress"]
    assert "configured_sources" in progress
    assert "enabled_sources" in progress


# ---- Admin API routes ----

def test_admin_sources_route() -> None:
    response = client.get("/api/admin/sources")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "stats" in data


def test_admin_aggregate_source_route() -> None:
    response = client.get("/api/admin/aggregate-source")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "version" in data


def test_admin_progress_route() -> None:
    response = client.get("/api/admin/progress")
    assert response.status_code == 200
    data = response.json()
    assert "aggregate" in data
    assert "sources" in data


def test_admin_settings_route() -> None:
    response = client.get("/api/admin/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["sourcePool"]["source_batch_size"] == 20


def test_admin_rule_engines_route() -> None:
    response = client.get("/api/admin/rule-engines")
    assert response.status_code == 200
    data = response.json()
    engines = data.get("engines", [])
    legado = next((engine for engine in engines if engine.get("id") == "legado"), None)
    assert legado is not None
    assert legado["enabled"] is True
    assert legado["type"] == "legado"


# ---- Web admin pages ----

def test_admin_dashboard_page() -> None:
    response = client.get("/admin")
    assert response.status_code == 200
    assert "LegadoHub 管理后台" in response.text


def test_admin_sources_page() -> None:
    response = client.get("/admin/sources")
    assert response.status_code == 200
    assert "书源管理" in response.text


def test_admin_search_page() -> None:
    response = client.get("/admin/search")
    assert response.status_code == 200
    assert "搜索工作台" in response.text


def test_admin_settings_page() -> None:
    response = client.get("/admin/settings")
    assert response.status_code == 200
    assert "设置" in response.text
    assert "每批书源数量" in response.text


def test_admin_rule_engines_page() -> None:
    response = client.get("/admin/rule-engines")
    assert response.status_code == 200
    assert "规则引擎" in response.text
    assert "阅读/Legado 规则引擎" in response.text


def test_admin_no_emoji() -> None:
    """Verify system-owned admin copy does not contain emoji characters.

    Source names are user/source-provided data and may contain symbols. Those
    names should pass through unchanged, so source listing pages are excluded
    from this whole-page assertion.
    """
    for path in ["/admin", "/admin/settings", "/admin/rule-engines"]:
        response = client.get(path)
        text = response.text
        # Check for common emoji ranges
        assert not any(0x1F300 <= ord(c) <= 0x1FAFF for c in text), f"Emoji found in {path}"
        assert not any(0x2600 <= ord(c) <= 0x27BF for c in text), f"Symbol emoji found in {path}"


# ---- Default proxy config ----

def test_default_proxy_url_in_config() -> None:
    pool_path = Path("config/source_pool.json")
    assert pool_path.exists()
    data = json.loads(pool_path.read_text(encoding="utf-8"))
    proxy = data.get("proxy", {})
    assert proxy.get("enabled") is True
    assert proxy.get("url") == "http://192.168.31.233:7890"
    assert data.get("source_batch_size") == 20
