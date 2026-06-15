"""Tests for aggregate settings persistence and migration."""

import json
import sqlite3

from app.services.aggregate_settings import (
    PROCESSING_PLACEHOLDER,
    RETRY_DELAYS_MINUTES,
    WINDOW_CHAPTER_LIMIT,
    AggregateSettingsRepository,
)
from app.storage.db import initialize_database


def test_aggregate_settings_migrates_legacy_content_workflow(tmp_path):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    legacy = {
        "aiEnabled": True,
        "autoAggregate": True,
        "processAggregateOnRead": True,
        "aggregateCheckIntervalMinutes": 15,
        "purifyMode": "aggressive",
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO admin_settings (key, value_json) VALUES (?, ?)",
            ("contentWorkflow", json.dumps(legacy, ensure_ascii=False)),
        )
        conn.commit()

    settings = AggregateSettingsRepository(db_path).get_settings()

    assert settings["contentWorkflow"]["aiEnabled"] is True
    assert settings["contentWorkflow"]["aggregateCheckIntervalMinutes"] == 15
    assert settings["contentWorkflow"]["sensitiveLexiconEnabled"] is True
    assert settings["contentWorkflow"]["sensitiveLexiconPath"] == "backend/data/lexicons/Sensitive-lexicon"
    assert settings["runtime"]["windowChapterLimit"] == WINDOW_CHAPTER_LIMIT == 5
    assert settings["runtime"]["processingPlaceholder"] == PROCESSING_PLACEHOLDER
    assert settings["runtime"]["retryDelaysMinutes"] == RETRY_DELAYS_MINUTES
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT value_json FROM aggregate_settings WHERE key = 'contentWorkflow'"
        ).fetchone()
    assert row is not None


def test_aggregate_settings_masks_api_key_and_reports_presence(tmp_path):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    repo = AggregateSettingsRepository(db_path)

    repo.save_settings(
        {
            "aiProviderConfig": {
                "provider": "openai_compatible",
                "baseUrl": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "apiKey": "sk-abcdefghijklmnopqrstuvwxyz123456",
            }
        }
    )

    settings = repo.get_settings()

    assert settings["aiProviderConfig"]["hasApiKey"] is True
    assert settings["aiProviderConfig"]["apiKey"].startswith("sk-")
    assert settings["aiProviderConfig"]["apiKey"].endswith("3456")
    assert "abcdefghijklmnopqrstuvwxyz" not in settings["aiProviderConfig"]["apiKey"]


def test_api_key_encrypted_at_rest(tmp_path):
    """API key should be encrypted in DB, not stored as plaintext."""
    from app.ai.encryption import is_encrypted
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    repo = AggregateSettingsRepository(db_path)

    real_key = "sk-supersecret123456789"
    repo.save_settings({"aiProviderConfig": {"apiKey": real_key, "baseUrl": "https://x.example/v1"}})

    # Read raw DB value.
    import sqlite3, json
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT value_json FROM aggregate_settings WHERE key='aiProviderConfig'"
        ).fetchone()
    raw = json.loads(row[0])
    # The stored key should be encrypted, not plaintext.
    assert raw["apiKey"] != real_key
    assert is_encrypted(raw["apiKey"])

    # But reading through the repo should return the decrypted key.
    config = repo.ai_provider_config(masked=False)
    assert config["apiKey"] == real_key


def test_legacy_plaintext_key_still_readable(tmp_path):
    """A key stored as plaintext before encryption was added should still be readable."""
    import sqlite3, json
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    # Write plaintext directly to DB.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO aggregate_settings (key, value_json) VALUES (?, ?)",
            ("aiProviderConfig", json.dumps({"apiKey": "sk-plaintextkey", "baseUrl": "https://x.example/v1"})),
        )
        conn.commit()
    repo = AggregateSettingsRepository(db_path)
    config = repo.ai_provider_config(masked=False)
    assert config["apiKey"] == "sk-plaintextkey"


def test_save_settings_preserves_real_api_key_when_masked_key_posted(tmp_path):
    """POST with a masked/apiKey should NOT overwrite the real key in DB."""
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    repo = AggregateSettingsRepository(db_path)

    real_key = "sk-abcdefghijklmnopqrstuvwxyz123456"
    repo.save_settings({
        "aiProviderConfig": {
            "baseUrl": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "apiKey": real_key,
        }
    })

    # Simulate what the frontend does: GET (gets masked), then POST it back.
    masked = repo.get_settings()["aiProviderConfig"]["apiKey"]
    assert masked != real_key  # confirm it's masked

    repo.save_settings({
        "aiProviderConfig": {
            "baseUrl": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "apiKey": masked,  # frontend re-posts the masked value
        }
    })

    # The raw DB should still hold the real key.
    raw = repo.ai_provider_config(masked=False)
    assert raw["apiKey"] == real_key
