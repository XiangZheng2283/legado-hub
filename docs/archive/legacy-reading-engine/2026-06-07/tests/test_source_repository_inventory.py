"""Tests for source repository inventory and health."""

import pytest
import sqlite3
from pathlib import Path
from app.services.source_repository import SourceRepository
from app.storage.db import initialize_database
from app import config


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr("app.services.source_repository.DB_PATH", db)
    monkeypatch.setattr("app.config.DB_PATH", db)
    initialize_database(db)
    yield


def test_scan_and_index_empty():
    repo = SourceRepository(repo_dir=Path("/nonexistent"))
    result = repo.scan_and_index()
    assert result["total_files"] == 0


def test_get_stats_empty():
    repo = SourceRepository()
    stats = repo.get_stats()
    assert stats["total"] == 0


def test_record_attempt_and_failure():
    repo = SourceRepository()
    db_path = config.DB_PATH
    # Insert a dummy source
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO source_health (source_id, book_source_name, enabled) VALUES (?, ?, ?)",
            ("test-source", "Test Source", 1),
        )
        conn.commit()

    repo.record_attempt("test-source", "search", "http://test", "failed", "-", False, 100, "timeout")
    attempts = repo.get_attempts("test-source")
    assert len(attempts) == 1
    assert attempts[0]["stage"] == "search"

    repo.record_failure("test-source", "search", "unsupported syntax", is_hard_failure=True)
    src = repo.get_source("test-source")
    assert src is not None
    assert src["enabled"] is False
    assert src["healthStatus"] == "disabled"


def test_scan_records_subscription_origin(tmp_path):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    source_dir = tmp_path / "legado"
    source_dir.mkdir()
    source_file = source_dir / "sub-demo.json"
    source_file.write_text(
        """
        [{
          "bookSourceName": "Demo Source",
          "bookSourceUrl": "https://demo.example",
          "searchUrl": "/search?key={{key}}",
          "ruleSearch": {"bookList": "div.book"},
          "ruleBookInfo": {"name": "h1@text"},
          "ruleToc": {"chapterList": "ul li"},
          "ruleContent": {"content": "div.content@text"}
        }]
        """,
        encoding="utf-8",
    )
    subscription_config = tmp_path / "source_subscriptions.json"
    subscription_config.write_text(
        """
        {
          "version": 1,
          "subscriptions": [{
            "id": "demo",
            "name": "Demo",
            "engine": "legado",
            "kind": "direct_json",
            "url": "https://example.com/demo.json",
            "last_output_path": "legado/sub-demo.json"
          }]
        }
        """,
        encoding="utf-8",
    )

    repo = SourceRepository(repo_dir=source_dir, db_path=db_path, subscription_config_path=subscription_config)
    result = repo.scan_and_index()
    src = repo.get_source("sub-demo")

    assert result["indexed"] == 1
    assert src is not None
    assert src["subscriptionId"] == "demo"
    assert src["upstreamUrl"] == "https://example.com/demo.json"
    assert src["engineType"] == "legado"


def test_detect_capabilities_treats_supported_rule_syntax_as_supported():
    repo = SourceRepository()
    caps = repo._detect_capabilities(
        {
            "searchUrl": "/search?key={{key}}",
            "ruleSearch": {
                "bookList": "class.book||id.fallback",
                "name": "class.name@text@js:result.trim()",
            },
        }
    )

    assert "@js:" not in caps["unsupported_syntax"]
    assert "|| fallback" not in caps["unsupported_syntax"]
    assert caps["has_limited_js"] is True
    assert caps["has_fallback"] is True


def test_load_raw_source_missing():
    repo = SourceRepository()
    assert repo.load_raw_source("nonexistent") is None
