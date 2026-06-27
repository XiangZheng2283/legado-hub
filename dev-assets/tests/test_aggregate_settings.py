"""Tests for aggregate settings defaults, serialization, and reload behavior."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.core import app_config as app_config_module
from app.core.app_config import AppConfig
from app.services.aggregate_processor import AggregateProcessor
from app.services.aggregate_settings import (
    PROCESSING_PLACEHOLDER,
    RETRY_DELAYS_MINUTES,
    WINDOW_CHAPTER_LIMIT,
    AggregateSettingsRepository,
    shared_book_storage_contract,
)
from app.services.shared_book_scheduler import SharedBookScheduler


def _write_app_config(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_aggregate_settings_defaults_include_shared_book_flags(tmp_path, monkeypatch):
    app_config_path = tmp_path / "app_config.json"
    _write_app_config(app_config_path, {})
    monkeypatch.setattr(app_config_module, "APP_CONFIG_PATH", app_config_path)
    AppConfig.reset()

    settings = AggregateSettingsRepository().get_settings()

    assert settings["contentWorkflow"]["useSharedBookStorage"] is False
    assert settings["contentWorkflow"]["sharedBookStorageReadMode"] == "legacy"
    assert settings["contentWorkflow"]["sharedBookStorageDualWrite"] is False
    assert settings["contentWorkflow"]["sharedBookCutoverBookIds"] == []
    assert settings["sharedBookStorageContract"]["legacyWriteMode"] == "read_write"
    assert settings["sharedBookStorageContract"]["sharedWriteMode"] == "disabled"
    assert settings["sharedBookStorageContract"]["apiReadTargets"] == ["legacy"]
    assert settings["sharedBookStorageContract"]["rollbackToLegacyAvailable"] is True
    assert settings["runtime"]["windowChapterLimit"] == WINDOW_CHAPTER_LIMIT == 5
    assert settings["runtime"]["processingPlaceholder"] == PROCESSING_PLACEHOLDER
    assert settings["runtime"]["retryDelaysMinutes"] == RETRY_DELAYS_MINUTES
    assert settings["contentWorkflow"]["stage3MaxBacklogPerBook"] == 0
    assert settings["contentWorkflow"]["aiTokenBudgetPerHour"] == 0
    assert settings["contentWorkflow"]["aiFailureRateThreshold"] == 0.0
    assert settings["contentWorkflow"]["aiCircuitBreakerCooldownMinutes"] == 30
    assert settings["contentWorkflow"]["stage3PeakHourSkipEnabled"] is False


def test_aggregate_settings_serializes_shared_book_flags(tmp_path, monkeypatch):
    app_config_path = tmp_path / "app_config.json"
    _write_app_config(app_config_path, {})
    monkeypatch.setattr(app_config_module, "APP_CONFIG_PATH", app_config_path)
    AppConfig.reset()

    repo = AggregateSettingsRepository()
    settings = repo.save_settings(
        {
            "contentWorkflow": {
                "useSharedBookStorage": True,
                "sharedBookStorageReadMode": "shared",
                "sharedBookStorageDualWrite": False,
                "sharedBookCutoverBookIds": ["book-1", "book-2"],
                "stage3MaxBacklogPerBook": 12,
                "aiTokenBudgetPerHour": 24000,
                "aiFailureRateThreshold": 0.6,
                "aiCircuitBreakerCooldownMinutes": 45,
                "stage3PeakHourSkipEnabled": True,
            }
        }
    )

    workflow = settings["contentWorkflow"]
    assert workflow["useSharedBookStorage"] is True
    assert workflow["sharedBookStorageReadMode"] == "shared"
    assert workflow["sharedBookStorageDualWrite"] is False
    assert workflow["sharedBookCutoverBookIds"] == ["book-1", "book-2"]
    assert workflow["stage3MaxBacklogPerBook"] == 12
    assert workflow["aiTokenBudgetPerHour"] == 24000
    assert workflow["aiFailureRateThreshold"] == 0.6
    assert workflow["aiCircuitBreakerCooldownMinutes"] == 45
    assert workflow["stage3PeakHourSkipEnabled"] is True

    raw = json.loads(app_config_path.read_text(encoding="utf-8"))
    assert raw["aggregate"]["contentWorkflow"]["useSharedBookStorage"] is True
    assert raw["aggregate"]["contentWorkflow"]["sharedBookStorageReadMode"] == "shared"
    assert raw["aggregate"]["contentWorkflow"]["sharedBookStorageDualWrite"] is False
    assert raw["aggregate"]["contentWorkflow"]["sharedBookCutoverBookIds"] == ["book-1", "book-2"]
    assert raw["aggregate"]["contentWorkflow"]["stage3MaxBacklogPerBook"] == 12
    assert raw["aggregate"]["contentWorkflow"]["aiTokenBudgetPerHour"] == 24000
    assert raw["aggregate"]["contentWorkflow"]["aiFailureRateThreshold"] == 0.6
    assert raw["aggregate"]["contentWorkflow"]["aiCircuitBreakerCooldownMinutes"] == 45
    assert raw["aggregate"]["contentWorkflow"]["stage3PeakHourSkipEnabled"] is True


def test_aggregate_settings_defaults_dual_write_when_shared_storage_enabled(tmp_path, monkeypatch):
    app_config_path = tmp_path / "app_config.json"
    _write_app_config(
        app_config_path,
        {
            "aggregate": {
                "contentWorkflow": {
                    "useSharedBookStorage": True,
                }
            }
        },
    )
    monkeypatch.setattr(app_config_module, "APP_CONFIG_PATH", app_config_path)
    AppConfig.reset()

    settings = AggregateSettingsRepository().get_settings()

    assert settings["contentWorkflow"]["useSharedBookStorage"] is True
    assert settings["contentWorkflow"]["sharedBookStorageDualWrite"] is True
    assert settings["contentWorkflow"]["sharedBookStorageReadMode"] == "legacy"


def test_aggregate_settings_save_defaults_dual_write_when_enabled_without_explicit_flag(tmp_path, monkeypatch):
    app_config_path = tmp_path / "app_config.json"
    _write_app_config(
        app_config_path,
        {
            "aggregate": {
                "contentWorkflow": {
                    "useSharedBookStorage": False,
                    "sharedBookStorageDualWrite": False,
                }
            }
        },
    )
    monkeypatch.setattr(app_config_module, "APP_CONFIG_PATH", app_config_path)
    AppConfig.reset()

    repo = AggregateSettingsRepository()
    settings = repo.save_settings(
        {
            "contentWorkflow": {
                "useSharedBookStorage": True,
            }
        }
    )

    assert settings["contentWorkflow"]["useSharedBookStorage"] is True
    assert settings["contentWorkflow"]["sharedBookStorageDualWrite"] is True

    raw = json.loads(app_config_path.read_text(encoding="utf-8"))
    assert raw["aggregate"]["contentWorkflow"]["sharedBookStorageDualWrite"] is True


def test_aggregate_settings_invalid_read_mode_falls_back_to_legacy(tmp_path, monkeypatch):
    app_config_path = tmp_path / "app_config.json"
    _write_app_config(
        app_config_path,
        {
            "aggregate": {
                "contentWorkflow": {
                    "sharedBookStorageReadMode": "future_mode",
                }
            }
        },
    )
    monkeypatch.setattr(app_config_module, "APP_CONFIG_PATH", app_config_path)
    AppConfig.reset()

    settings = AggregateSettingsRepository().get_settings()

    assert settings["contentWorkflow"]["sharedBookStorageReadMode"] == "legacy"


def test_aggregate_settings_repository_normalizes_disabled_shared_storage_flags(tmp_path, monkeypatch):
    app_config_path = tmp_path / "app_config.json"
    _write_app_config(
        app_config_path,
        {
            "aggregate": {
                "contentWorkflow": {
                    "useSharedBookStorage": False,
                    "sharedBookStorageReadMode": "shared",
                    "sharedBookStorageDualWrite": True,
                }
            }
        },
    )
    monkeypatch.setattr(app_config_module, "APP_CONFIG_PATH", app_config_path)
    AppConfig.reset()

    settings = AggregateSettingsRepository().get_settings()

    workflow = settings["contentWorkflow"]
    contract = settings["sharedBookStorageContract"]
    assert workflow["useSharedBookStorage"] is False
    assert workflow["sharedBookStorageReadMode"] == "legacy"
    assert workflow["sharedBookStorageDualWrite"] is False
    assert contract["readMode"] == "legacy"
    assert contract["dualWrite"] is False
    assert contract["apiReadTargets"] == ["legacy"]


def test_aggregate_settings_reload_reads_latest_app_config(tmp_path, monkeypatch):
    app_config_path = tmp_path / "app_config.json"
    _write_app_config(
        app_config_path,
        {
            "aggregate": {
                "contentWorkflow": {
                    "sharedBookStorageReadMode": "legacy",
                }
            }
        },
    )
    monkeypatch.setattr(app_config_module, "APP_CONFIG_PATH", app_config_path)
    AppConfig.reset()

    repo = AggregateSettingsRepository()
    assert repo.get_settings()["contentWorkflow"]["sharedBookStorageReadMode"] == "legacy"

    _write_app_config(
        app_config_path,
        {
            "aggregate": {
                "contentWorkflow": {
                    "useSharedBookStorage": True,
                    "sharedBookStorageReadMode": "dual_verify",
                    "sharedBookCutoverBookIds": ["cutover-1"],
                }
            }
        },
    )

    refreshed = repo.get_settings()["contentWorkflow"]
    assert refreshed["useSharedBookStorage"] is True
    assert refreshed["sharedBookStorageReadMode"] == "dual_verify"
    assert refreshed["sharedBookStorageDualWrite"] is True
    assert refreshed["sharedBookCutoverBookIds"] == ["cutover-1"]


def test_shared_book_storage_contract_encodes_dual_write_cutover_semantics():
    disabled = shared_book_storage_contract(
        {
            "useSharedBookStorage": False,
            "sharedBookStorageReadMode": "shared",
            "sharedBookStorageDualWrite": True,
        }
    )
    assert disabled["sharedWriteMode"] == "disabled"
    assert disabled["sharedReadMode"] == "disabled"
    assert disabled["dualWrite"] is False
    assert disabled["readMode"] == "legacy"
    assert disabled["apiReadTargets"] == ["legacy"]
    assert disabled["shouldReadLegacy"] is True
    assert disabled["shouldReadShared"] is False
    assert disabled["shouldCompareReads"] is False
    assert disabled["rollbackToLegacyAvailable"] is True

    disabled_dual_verify = shared_book_storage_contract(
        {
            "useSharedBookStorage": False,
            "sharedBookStorageReadMode": "dual_verify",
            "sharedBookStorageDualWrite": True,
        }
    )
    assert disabled_dual_verify["sharedReadMode"] == "disabled"
    assert disabled_dual_verify["dualWrite"] is False
    assert disabled_dual_verify["readMode"] == "legacy"
    assert disabled_dual_verify["apiReadTargets"] == ["legacy"]
    assert disabled_dual_verify["shouldReadLegacy"] is True
    assert disabled_dual_verify["shouldReadShared"] is False
    assert disabled_dual_verify["shouldCompareReads"] is False

    dual_write = shared_book_storage_contract(
        {
            "useSharedBookStorage": True,
            "sharedBookStorageReadMode": "dual_verify",
            "sharedBookStorageDualWrite": True,
        }
    )
    assert dual_write["legacyWriteMode"] == "read_write"
    assert dual_write["sharedWriteMode"] == "read_write"
    assert dual_write["apiReadTargets"] == ["legacy", "shared"]
    assert dual_write["shouldCompareReads"] is True
    assert dual_write["rollbackToLegacyAvailable"] is True

    shared_only = shared_book_storage_contract(
        {
            "useSharedBookStorage": True,
            "sharedBookStorageReadMode": "shared",
            "sharedBookStorageDualWrite": False,
        }
    )
    assert shared_only["legacyWriteMode"] == "read_only"
    assert shared_only["sharedWriteMode"] == "read_write"
    assert shared_only["apiReadTargets"] == ["shared"]
    assert shared_only["shouldReadLegacy"] is False
    assert shared_only["rollbackToLegacyAvailable"] is False


@pytest.mark.asyncio
async def test_stage3_backlog_limit_refuses_manual_queue():
    class FakeProcessor:
        def stage3_backlog_state(self, aggregate_book_id: str) -> dict[str, object]:
            return {
                "bookId": aggregate_book_id,
                "backlog": 9,
                "limit": 5,
                "enabled": True,
                "exceeded": True,
            }

        def list_due_books(self, limit: int = 10):
            return []

    scheduler = SharedBookScheduler(
        processor=FakeProcessor(),
        recovery_scanner=lambda: [],
    )
    scheduler._recovery_complete.set()

    result = scheduler.enqueue_manual_update("book-overflow", book_name="积压书", author="作者")

    assert result["queued"] is False
    assert result["reason"] == "stage3_backlog_limit_exceeded"
    assert result["stage3Backlog"] == 9
    assert result["stage3BacklogLimit"] == 5


def test_ai_circuit_breaker_opens_for_failure_rate(monkeypatch):
    processor = AggregateProcessor(db_path=":memory:")
    monkeypatch.setattr(
        processor,
        "_book_workflow_settings",
        lambda aggregate_book_id="": {
            "aiFailureRateThreshold": 0.5,
            "aiTokenBudgetPerHour": 0,
            "aiCircuitBreakerCooldownMinutes": 20,
            "stage3PeakHourSkipEnabled": False,
        },
    )

    for _ in range(3):
        processor._record_ai_window_event("book-a", success=False, tokens=0)

    state = processor.ai_circuit_breaker_state("book-a")

    assert state["isOpen"] is True
    assert state["reason"] == "failure_rate_threshold_exceeded"
    assert state["failedCallsLastHour"] == 3
    assert state["totalCallsLastHour"] == 3


def test_ai_circuit_breaker_opens_for_token_budget(monkeypatch):
    processor = AggregateProcessor(db_path=":memory:")
    monkeypatch.setattr(
        processor,
        "_book_workflow_settings",
        lambda aggregate_book_id="": {
            "aiFailureRateThreshold": 0.0,
            "aiTokenBudgetPerHour": 300,
            "aiCircuitBreakerCooldownMinutes": 15,
            "stage3PeakHourSkipEnabled": False,
        },
    )

    processor._record_ai_window_event("book-budget", success=True, tokens=120)
    processor._record_ai_window_event("book-budget", success=True, tokens=200)

    state = processor.ai_circuit_breaker_state("book-budget")

    assert state["isOpen"] is True
    assert state["reason"] == "token_budget_exceeded"
    assert state["tokensLastHour"] == 320
