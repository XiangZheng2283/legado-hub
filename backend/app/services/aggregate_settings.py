"""Settings repository and runtime constants for AI aggregate processing.

All persistent settings now live in backend/config/app_config.json.
This module provides the same public API as before but reads/writes the
unified config file instead of split SQLite/JSON files.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core.app_config import AppConfig

logger = logging.getLogger(__name__)

PROCESSING_PLACEHOLDER = "聚合处理中……请先查看其他源或稍后刷新。"
AI_RUNTIME_ENABLED = False
WINDOW_CHAPTER_LIMIT = 5
BACKLOG_CHAPTER_LIMIT = 25
BACKLOG_RECHECK_MINUTES = 1
RETRY_DELAYS_MINUTES = [5, 15, 30, 60, 120]
PREVIEW_RETRY_DELAYS_MINUTES = [30, 60, 120, 240, 480]
CANDIDATE_SOURCE_CACHE_TTL_SECONDS = 300
CHAPTER_PARALLELISM_LIMIT = 8
PER_SOURCE_CONCURRENCY = 6
PER_BOOK_SOURCE_CONCURRENCY = 3
INITIAL_PREFETCH_GRACE_SECONDS = 60
INITIAL_PREFETCH_CHAPTER_LIMIT = 20
WORD_COUNT_TOLERANCE_LOWER = 0.9
WORD_COUNT_TOLERANCE_UPPER = 1.2

# Default lexicon path relative to backend/ (e.g. backend/data/lexicons/Sensitive-lexicon).
# The resolve_sensitive_lexicon_path() function handles CWD differences at runtime.
DEFAULT_LEXICON_PATH = "data/lexicons/Sensitive-lexicon"

# Legacy path that older configs may still carry.
_LEGACY_LEXICON_PATH = "backend/data/lexicons/Sensitive-lexicon"


def resolve_sensitive_lexicon_path(raw_path: str | Path | None) -> Path:
    """Resolve a user-configured lexicon path to an absolute ``Path``.

    Resolution order:
    1. If *raw_path* is already absolute, return it directly.
    2. If the path exists relative to the current working directory, use it.
    3. If the path starts with ``backend/`` and stripping that prefix gives an
       existing path relative to ``BACKEND_ROOT``, use the stripped path.
       (This handles the legacy default ``backend/data/lexicons/Sensitive-lexicon``
       when the runtime CWD is the repo root or ``backend/``.)
    4. Otherwise resolve against ``BACKEND_ROOT``.
    """
    from app.config import BACKEND_ROOT
    if not raw_path:
        return (BACKEND_ROOT / DEFAULT_LEXICON_PATH).resolve()

    p = Path(raw_path)

    # Absolute path — use as-is.
    if p.is_absolute():
        return p

    # Relative to CWD (works from repo root for old default, and from backend/ for new default).
    cwd_resolved = (Path.cwd() / p).resolve()
    if cwd_resolved.exists():
        return cwd_resolved

    # Legacy path: "backend/data/lexicons/..." — strip "backend/" prefix and resolve against BACKEND_ROOT.
    p_str = str(p).replace("\\", "/")
    if p_str.startswith("backend/"):
        stripped = p_str[len("backend/"):]
        stripped_resolved = (BACKEND_ROOT / stripped).resolve()
        if stripped_resolved.exists():
            return stripped_resolved
        # If stripped path doesn't exist yet, still return it (path may be created later).
        return stripped_resolved

    # Default: resolve relative to BACKEND_ROOT (handles "data/lexicons/..." from any CWD).
    return (BACKEND_ROOT / p).resolve()


DEFAULT_CONTENT_WORKFLOW: dict[str, Any] = {
    "aggregationMode": "balanced",
    "autoAggregate": True,
    "processAggregateOnRead": True,
    "aggregateCheckIntervalMinutes": 30,
    "returnOnlyAggregateSource": False,
    "sourceCandidateLimit": 0,  # 0 表示所有启用候选源参与交叉比对。
    "purifyMode": "conservative",
    "primarySourceMode": "official",
    # Empty by default: do not pre-seed qidian_com_app (often absent / gitignored).
    # Operators add installed official plugins via settings when available.
    "primarySourcePriority": [],
    "candidateSourcePriority": [],  # Ordered list of third-party source IDs for VIP completion.
    "minSourceScore": 100,
    "aiEnabled": False,
    "blockedWordRepair": True,
    "sensitiveLexiconEnabled": True,
    "sensitiveLexiconPath": DEFAULT_LEXICON_PATH,
    "includePreviousChapters": 3,
    "deviationThreshold": 0.90,
    "promptTemplate": "",
    "systemPrompt": "",
    "useSharedBookStorage": True,
    "sharedBookStorageReadMode": "shared",
    "sharedBookStorageDualWrite": True,
    "sharedBookCutoverBookIds": [],
    "minReadableChaptersForDiscovery": 50,
    "stage3MaxBacklogPerBook": 0,
    "aiTokenBudgetPerHour": 0,
    "aiFailureRateThreshold": 0.0,
    "aiCircuitBreakerCooldownMinutes": 30,
    "stage3PeakHourSkipEnabled": False,
}


DEFAULT_AI_PROVIDER_CONFIG: dict[str, Any] = {
    "provider": "openai_compatible",
    "name": "",
    "baseUrl": "",
    "apiKey": "",
    "apiKeyField": "api_key",
    "model": "",
    "modelContextLength": 256000,
    "maxContextUseRatio": 0.5,
    "maxOutputTokens": 8192,
    "timeoutMs": 120000,
    "aiMaxConcurrency": 2,
    "bookDefaultConcurrency": 1,
    "temperature": 0.3,
    "topP": 1.0,
    "frequencyPenalty": 0,
    "presencePenalty": 0,
    "seed": 0,
    "endpointCandidates": [],
    "modelsUrl": "",
    "customHeaders": {},
    "customBodyParams": {},
    "thinkingLevel": "medium",
    "compatOverrides": {},
}


def shared_book_storage_contract(content_workflow: dict[str, Any]) -> dict[str, Any]:
    """Return normalized shared-book cutover semantics for callers and docs.

    This mirrors the contract documented in the shared-subscription rewrite plan:
    - ``useSharedBookStorage=false`` keeps the legacy path read/write.
    - ``useSharedBookStorage=true, dualWrite=true`` is the only rollback-safe
      migration state.
    - ``useSharedBookStorage=true, dualWrite=false`` stops legacy writes and
      makes shared files the source of truth.
    """
    workflow = _normalize_content_workflow(content_workflow)
    use_shared_storage = workflow["useSharedBookStorage"]
    configured_read_mode = workflow["sharedBookStorageReadMode"]
    dual_write = workflow["sharedBookStorageDualWrite"]

    if not use_shared_storage:
        read_mode = "legacy"
        legacy_write_mode = "read_write"
        shared_write_mode = "disabled"
        shared_read_mode = "disabled"
        rollback_allowed = False
        rollback_note = (
            "Legacy subscription implementation has been removed; shared-book storage is "
            "the only persistence layer for subscription books."
        )
    elif dual_write:
        read_mode = configured_read_mode
        legacy_write_mode = "read_write"
        shared_write_mode = "read_write"
        shared_read_mode = read_mode
        rollback_allowed = True
        rollback_note = (
            "Rollback remains available: set useSharedBookStorage=false to stop all new "
            "shared-book reads and writes while keeping legacy behavior."
        )
    else:
        read_mode = configured_read_mode
        legacy_write_mode = "read_only"
        shared_write_mode = "read_write"
        shared_read_mode = read_mode
        rollback_allowed = False
        rollback_note = (
            "Rollback to pure legacy mode is no longer guaranteed after legacy writes are "
            "disabled; investigate with shared-book data as the write source of truth."
        )

    if not use_shared_storage:
        api_read_targets = ["legacy"]
        should_read_legacy = True
        should_read_shared = False
        should_compare_reads = False
    else:
        read_targets = {
            "legacy": ["legacy"],
            "shared": ["shared"],
            "dual_verify": ["legacy", "shared"],
        }
        api_read_targets = list(read_targets.get(read_mode, ["shared"]))
        should_read_legacy = read_mode in {"legacy", "dual_verify"}
        should_read_shared = read_mode in {"shared", "dual_verify"}
        should_compare_reads = read_mode == "dual_verify"

    return {
        "useSharedBookStorage": use_shared_storage,
        "dualWrite": dual_write,
        "readMode": read_mode,
        "legacyWriteMode": legacy_write_mode,
        "sharedWriteMode": shared_write_mode,
        "sharedReadMode": shared_read_mode,
        "apiReadTargets": api_read_targets,
        "shouldReadLegacy": should_read_legacy,
        "shouldReadShared": should_read_shared,
        "shouldCompareReads": should_compare_reads,
        "rollbackToLegacyAvailable": rollback_allowed,
        "rollbackToLegacyRule": rollback_note,
        "cutoverBookIds": workflow.get("sharedBookCutoverBookIds", []),
    }


def runtime_contract() -> dict[str, Any]:
    return {
        "aiRuntimeEnabled": AI_RUNTIME_ENABLED,
        "windowChapterLimit": WINDOW_CHAPTER_LIMIT,
        "backlogChapterLimit": BACKLOG_CHAPTER_LIMIT,
        "backlogRecheckMinutes": BACKLOG_RECHECK_MINUTES,
        "processingPlaceholder": PROCESSING_PLACEHOLDER,
        "retryDelaysMinutes": list(RETRY_DELAYS_MINUTES),
    }


def _merge_defaults(defaults: dict[str, Any], value: Any) -> dict[str, Any]:
    merged = deepcopy(defaults)
    if isinstance(value, dict):
        merged.update(value)
    return merged


def _shared_book_dual_write_value(
    config: dict[str, Any],
    *,
    explicit_dual_write: bool,
) -> bool:
    """Return the effective dual-write flag.

    When the operator explicitly set the flag, honor it. Otherwise default to
    dual-write=true while shared storage is enabled (the rollback-safe migration
    state) and false when shared storage is disabled.
    """
    use_shared = bool(config.get("useSharedBookStorage", False))
    if explicit_dual_write:
        return bool(config.get("sharedBookStorageDualWrite", False))
    return use_shared


def _normalize_content_workflow(value: Any, *, explicit_dual_write: bool | None = None) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    config = _merge_defaults(DEFAULT_CONTENT_WORKFLOW, raw)

    config["useSharedBookStorage"] = bool(config.get("useSharedBookStorage", False))

    # When shared storage is enabled the default read mode is "shared"; when disabled
    # it falls back to "legacy". Invalid values are normalized to the default for the
    # current mode.
    if config["useSharedBookStorage"]:
        default_read_mode = "shared"
    else:
        default_read_mode = "legacy"
    read_mode = str(config.get("sharedBookStorageReadMode", default_read_mode) or default_read_mode).strip().lower()
    if read_mode not in {"legacy", "shared", "dual_verify"}:
        read_mode = default_read_mode

    if explicit_dual_write is None:
        explicit_dual_write = "sharedBookStorageDualWrite" in raw
    dual_write = _shared_book_dual_write_value(
        config,
        explicit_dual_write=explicit_dual_write,
    )

    if config["useSharedBookStorage"]:
        # Keep the configured read mode; dual-write defaults to true unless explicitly false.
        pass
    else:
        read_mode = "legacy"
        dual_write = False

    try:
        min_readable_chapters = int(config.get("minReadableChaptersForDiscovery", 50) or 50)
    except (TypeError, ValueError):
        min_readable_chapters = 50
    config["minReadableChaptersForDiscovery"] = max(0, min_readable_chapters)

    try:
        stage3_max_backlog = int(config.get("stage3MaxBacklogPerBook", 0) or 0)
    except (TypeError, ValueError):
        stage3_max_backlog = 0
    config["stage3MaxBacklogPerBook"] = max(0, stage3_max_backlog)

    try:
        ai_token_budget = int(config.get("aiTokenBudgetPerHour", 0) or 0)
    except (TypeError, ValueError):
        ai_token_budget = 0
    config["aiTokenBudgetPerHour"] = max(0, ai_token_budget)

    try:
        ai_failure_rate = float(config.get("aiFailureRateThreshold", 0.0) or 0.0)
    except (TypeError, ValueError):
        ai_failure_rate = 0.0
    config["aiFailureRateThreshold"] = min(max(ai_failure_rate, 0.0), 1.0)

    try:
        cooldown_minutes = int(config.get("aiCircuitBreakerCooldownMinutes", 30) or 30)
    except (TypeError, ValueError):
        cooldown_minutes = 30
    config["aiCircuitBreakerCooldownMinutes"] = max(1, cooldown_minutes)
    config["stage3PeakHourSkipEnabled"] = bool(config.get("stage3PeakHourSkipEnabled", False))
    for key in ("primarySourcePriority", "candidateSourcePriority"):
        raw_priority = config.get(key, [])
        if isinstance(raw_priority, list):
            config[key] = [str(item).strip() for item in raw_priority if str(item).strip()]
        else:
            config[key] = []

    config["sharedBookStorageReadMode"] = read_mode
    config["sharedBookStorageDualWrite"] = dual_write

    raw_book_ids = config.get("sharedBookCutoverBookIds", [])
    if isinstance(raw_book_ids, list):
        config["sharedBookCutoverBookIds"] = [str(item) for item in raw_book_ids if str(item).strip()]
    else:
        config["sharedBookCutoverBookIds"] = []

    return config


def mask_api_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}...{value[-4:]}"


def _looks_masked(value: str) -> bool:
    """Return True if the value looks like a masked API key (e.g. 'sk-...3456')."""
    if not value:
        return False
    return "..." in value or value == "*" * len(value)


def _provider_to_dict(provider) -> dict[str, Any]:
    """Serialize AppConfig AI provider dataclass to frontend-facing dict."""
    config = _merge_defaults(DEFAULT_AI_PROVIDER_CONFIG, {
        "provider": provider.provider,
        "name": provider.name,
        "baseUrl": provider.base_url,
        "apiKey": provider.api_key,
        "apiKeyField": provider.api_key_field,
        "model": provider.model,
        "modelContextLength": provider.model_context_length,
        "maxContextUseRatio": provider.max_context_use_ratio,
        "maxOutputTokens": provider.max_output_tokens,
        "timeoutMs": provider.timeout_ms,
        "aiMaxConcurrency": provider.ai_max_concurrency,
        "bookDefaultConcurrency": provider.book_default_concurrency,
        "temperature": provider.temperature,
        "topP": provider.top_p,
        "frequencyPenalty": provider.frequency_penalty,
        "presencePenalty": provider.presence_penalty,
        "seed": provider.seed,
        "endpointCandidates": provider.endpoint_candidates,
        "modelsUrl": provider.models_url,
        "customHeaders": provider.custom_headers,
        "customBodyParams": provider.custom_body_params,
        "thinkingLevel": provider.thinking_level,
        "compatOverrides": provider.compat_overrides,
    })
    config["hasApiKey"] = bool(config.get("apiKey"))
    return config


def _provider_from_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Build a normalized AI provider dict ready to be stored under ai.provider."""
    current = _provider_to_dict(AppConfig.get().ai_provider)
    api_key = str(data.get("apiKey") or "")
    if _looks_masked(api_key) or not api_key:
        data = {k: v for k, v in data.items() if k != "apiKey"}
    current.update(data)
    return current


class AggregateSettingsRepository:
    """Read/write aggregate settings from the unified app_config.json."""

    def __init__(self, db_path: Any | None = None):
        # db_path is kept for API compatibility but is no longer used.
        self._cfg = AppConfig.get()

    def content_workflow(self) -> dict[str, Any]:
        self._cfg.reload()
        return _normalize_content_workflow(self._cfg.aggregate.content_workflow)

    def ai_provider_config(self) -> dict[str, Any]:
        self._cfg.reload()
        return _provider_to_dict(self._cfg.ai_provider)

    def get_settings(self) -> dict[str, Any]:
        workflow = self.content_workflow()
        return {
            "contentWorkflow": workflow,
            "sharedBookStorageContract": shared_book_storage_contract(workflow),
            "aiProviderConfig": self.ai_provider_config(),
            "runtime": runtime_contract(),
        }

    def save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "contentWorkflow" in payload:
            value = payload.get("contentWorkflow")
            if isinstance(value, dict):
                self._cfg.reload()
                stored_wf = self._cfg.aggregate.content_workflow
                current_wf = _merge_defaults(DEFAULT_CONTENT_WORKFLOW, stored_wf)
                current_wf.update(value)
                self._cfg.set(
                    "aggregate.contentWorkflow",
                    _normalize_content_workflow(
                        current_wf,
                        explicit_dual_write=("sharedBookStorageDualWrite" in value),
                    ),
                )

        if "aiProviderConfig" in payload:
            value = payload.get("aiProviderConfig")
            if isinstance(value, dict):
                self._cfg.set("ai.provider", _provider_from_dict(value))

        self._cfg.save()
        return self.get_settings()
