"""Tests for aggregate settings persistence and migration."""

import json
import sqlite3
from pathlib import Path

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
    assert settings["contentWorkflow"]["sensitiveLexiconPath"] == "data/lexicons/Sensitive-lexicon"
    assert settings["runtime"]["windowChapterLimit"] == WINDOW_CHAPTER_LIMIT == 5
    assert settings["runtime"]["processingPlaceholder"] == PROCESSING_PLACEHOLDER
    assert settings["runtime"]["retryDelaysMinutes"] == RETRY_DELAYS_MINUTES
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT value_json FROM aggregate_settings WHERE key = 'contentWorkflow'"
        ).fetchone()
    assert row is not None


def test_aggregate_settings_reports_api_key_presence(tmp_path):
    db_path = tmp_path / "test.db"
    ai_config_path = tmp_path / "ai_provider.json"
    initialize_database(db_path)
    repo = AggregateSettingsRepository(db_path)
    repo._ai_config_path = ai_config_path

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
    # Plaintext storage: key is returned as-is.
    assert settings["aiProviderConfig"]["apiKey"] == "sk-abcdefghijklmnopqrstuvwxyz123456"


def test_api_key_stored_plaintext_in_json_file(tmp_path):
    """API key is stored as plaintext in the data directory JSON file."""
    db_path = tmp_path / "test.db"
    ai_config_path = tmp_path / "ai_provider.json"
    initialize_database(db_path)
    repo = AggregateSettingsRepository(db_path)
    repo._ai_config_path = ai_config_path

    real_key = "sk-supersecret123456789"
    repo.save_settings({"aiProviderConfig": {"apiKey": real_key, "baseUrl": "https://x.example/v1"}})

    # Read raw JSON file value.
    raw = json.loads(ai_config_path.read_text(encoding="utf-8"))
    # The stored key should be plaintext.
    assert raw["apiKey"] == real_key

    # Reading through the repo should return the same plaintext key.
    config = repo.ai_provider_config()
    assert config["apiKey"] == real_key


def test_legacy_encrypted_key_migrated_to_plaintext_json(tmp_path):
    """A key stored encrypted in the legacy DB should be decrypted and migrated to the JSON file."""
    from app.ai.encryption import encrypt_api_key
    import sqlite3

    db_path = tmp_path / "test.db"
    ai_config_path = tmp_path / "ai_provider.json"
    initialize_database(db_path)
    real_key = "sk-migratedkey"
    encrypted = encrypt_api_key(real_key)
    # Write encrypted key directly to legacy DB.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO aggregate_settings (key, value_json) VALUES (?, ?)",
            ("aiProviderConfig", json.dumps({"apiKey": encrypted, "baseUrl": "https://x.example/v1"})),
        )
        conn.commit()

    repo = AggregateSettingsRepository(db_path)
    repo._ai_config_path = ai_config_path
    config = repo.ai_provider_config()
    assert config["apiKey"] == real_key
    # JSON file should have been created with the decrypted key.
    assert ai_config_path.exists()
    raw = json.loads(ai_config_path.read_text(encoding="utf-8"))
    assert raw["apiKey"] == real_key


def test_save_settings_preserves_real_api_key_when_masked_key_posted(tmp_path):
    """POST with a masked apiKey should NOT overwrite the real key."""
    db_path = tmp_path / "test.db"
    ai_config_path = tmp_path / "ai_provider.json"
    initialize_database(db_path)
    repo = AggregateSettingsRepository(db_path)
    repo._ai_config_path = ai_config_path

    real_key = "sk-abcdefghijklmnopqrstuvwxyz123456"
    repo.save_settings({
        "aiProviderConfig": {
            "baseUrl": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "apiKey": real_key,
        }
    })

    # Simulate what the frontend might do: re-post a masked value.
    repo.save_settings({
        "aiProviderConfig": {
            "baseUrl": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "apiKey": "sk-...3456",
        }
    })

    # The JSON file should still hold the real key.
    raw = repo.ai_provider_config()
    assert raw["apiKey"] == real_key
