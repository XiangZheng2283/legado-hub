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
    BACKLOG_CHAPTER_LIMIT,
    BACKLOG_RECHECK_MINUTES,
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

    assert settings["contentWorkflow"]["useSharedBookStorage"] is True
    assert settings["contentWorkflow"]["sharedBookStorageReadMode"] == "shared"
    assert settings["contentWorkflow"]["sharedBookStorageDualWrite"] is True
    assert settings["contentWorkflow"]["sharedBookCutoverBookIds"] == []
    contract = settings["sharedBookStorageContract"]
    assert contract["useSharedBookStorage"] is True
    assert contract["dualWrite"] is True
    assert contract["readMode"] == "shared"
    assert contract["legacyWriteMode"] == "read_write"
    assert contract["sharedWriteMode"] == "read_write"
    assert contract["sharedReadMode"] == "shared"
    assert contract["apiReadTargets"] == ["shared"]
    assert contract["shouldReadLegacy"] is False
    assert contract["shouldReadShared"] is True
    assert contract["shouldCompareReads"] is False
    assert contract["rollbackToLegacyAvailable"] is True
    assert contract["cutoverBookIds"] == []
    assert settings["runtime"]["windowChapterLimit"] == WINDOW_CHAPTER_LIMIT == 5
    assert settings["runtime"]["aiRuntimeEnabled"] is False
    assert settings["runtime"]["backlogChapterLimit"] == BACKLOG_CHAPTER_LIMIT == 25
    assert settings["runtime"]["backlogRecheckMinutes"] == BACKLOG_RECHECK_MINUTES == 1
    assert settings["runtime"]["processingPlaceholder"] == PROCESSING_PLACEHOLDER
    assert settings["runtime"]["retryDelaysMinutes"] == RETRY_DELAYS_MINUTES
    assert settings["contentWorkflow"]["stage3MaxBacklogPerBook"] == 0
    assert settings["contentWorkflow"]["aiTokenBudgetPerHour"] == 0
    assert settings["contentWorkflow"]["aiFailureRateThreshold"] == 0.0
    assert settings["contentWorkflow"]["aiCircuitBreakerCooldownMinutes"] == 30
    assert settings["contentWorkflow"]["stage3PeakHourSkipEnabled"] is False
    assert settings["contentWorkflow"]["primarySourcePriority"] == []
    assert settings["contentWorkflow"]["candidateSourcePriority"] == []
    assert settings["contentWorkflow"]["aiEnabled"] is False


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
                "primarySourcePriority": ["qidian_com_app", "qidian_com_web"],
                "candidateSourcePriority": ["third_b", "third_a"],
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
    assert workflow["primarySourcePriority"] == ["qidian_com_app", "qidian_com_web"]
    assert workflow["candidateSourcePriority"] == ["third_b", "third_a"]

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
    assert raw["aggregate"]["contentWorkflow"]["primarySourcePriority"] == ["qidian_com_app", "qidian_com_web"]
    assert raw["aggregate"]["contentWorkflow"]["candidateSourcePriority"] == ["third_b", "third_a"]


def test_aggregate_settings_invalid_read_mode_falls_back_to_shared(tmp_path, monkeypatch):
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

    assert settings["contentWorkflow"]["sharedBookStorageReadMode"] == "shared"


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
    assert contract["useSharedBookStorage"] is False
    assert contract["dualWrite"] is False
    assert contract["readMode"] == "legacy"
    assert contract["legacyWriteMode"] == "read_write"
    assert contract["sharedWriteMode"] == "disabled"
    assert contract["sharedReadMode"] == "disabled"
    assert contract["apiReadTargets"] == ["legacy"]
    assert contract["shouldReadLegacy"] is True
    assert contract["shouldReadShared"] is False
    assert contract["shouldCompareReads"] is False
    assert contract["rollbackToLegacyAvailable"] is False


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
    # sharedBookStorage is enabled by default, so the explicit legacy read mode is preserved.
    assert repo.get_settings()["contentWorkflow"]["sharedBookStorageReadMode"] == "legacy"
    assert repo.get_settings()["contentWorkflow"]["sharedBookStorageDualWrite"] is True

    _write_app_config(
        app_config_path,
        {
            "aggregate": {
                "contentWorkflow": {
                    "useSharedBookStorage": False,
                    "sharedBookStorageReadMode": "dual_verify",
                    "sharedBookCutoverBookIds": ["cutover-1"],
                }
            }
        },
    )

    refreshed = repo.get_settings()["contentWorkflow"]
    assert refreshed["useSharedBookStorage"] is False
    assert refreshed["sharedBookStorageReadMode"] == "legacy"
    assert refreshed["sharedBookStorageDualWrite"] is False
    assert refreshed["sharedBookCutoverBookIds"] == ["cutover-1"]


def test_shared_book_storage_contract_encodes_shared_only_semantics():
    disabled = shared_book_storage_contract(
        {
            "useSharedBookStorage": False,
            "sharedBookStorageReadMode": "shared",
            "sharedBookStorageDualWrite": True,
        }
    )
    assert disabled["useSharedBookStorage"] is False
    assert disabled["dualWrite"] is False
    assert disabled["readMode"] == "legacy"
    assert disabled["legacyWriteMode"] == "read_write"
    assert disabled["sharedWriteMode"] == "disabled"
    assert disabled["sharedReadMode"] == "disabled"
    assert disabled["apiReadTargets"] == ["legacy"]
    assert disabled["shouldReadLegacy"] is True
    assert disabled["shouldReadShared"] is False
    assert disabled["shouldCompareReads"] is False
    assert disabled["rollbackToLegacyAvailable"] is False

    dual_verify = shared_book_storage_contract(
        {
            "useSharedBookStorage": True,
            "sharedBookStorageReadMode": "dual_verify",
            "sharedBookStorageDualWrite": True,
        }
    )
    assert dual_verify["useSharedBookStorage"] is True
    assert dual_verify["dualWrite"] is True
    assert dual_verify["readMode"] == "dual_verify"
    assert dual_verify["legacyWriteMode"] == "read_write"
    assert dual_verify["sharedWriteMode"] == "read_write"
    assert dual_verify["sharedReadMode"] == "dual_verify"
    assert dual_verify["apiReadTargets"] == ["legacy", "shared"]
    assert dual_verify["shouldReadLegacy"] is True
    assert dual_verify["shouldReadShared"] is True
    assert dual_verify["shouldCompareReads"] is True
    assert dual_verify["rollbackToLegacyAvailable"] is True

    no_dual_write = shared_book_storage_contract(
        {
            "useSharedBookStorage": True,
            "sharedBookStorageReadMode": "shared",
            "sharedBookStorageDualWrite": False,
        }
    )
    assert no_dual_write["useSharedBookStorage"] is True
    assert no_dual_write["dualWrite"] is False
    assert no_dual_write["readMode"] == "shared"
    assert no_dual_write["legacyWriteMode"] == "read_only"
    assert no_dual_write["sharedWriteMode"] == "read_write"
    assert no_dual_write["sharedReadMode"] == "shared"
    assert no_dual_write["apiReadTargets"] == ["shared"]
    assert no_dual_write["shouldReadLegacy"] is False
    assert no_dual_write["shouldReadShared"] is True
    assert no_dual_write["shouldCompareReads"] is False
    assert no_dual_write["rollbackToLegacyAvailable"] is False


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
