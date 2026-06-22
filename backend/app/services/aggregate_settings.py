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

from app.config import BACKEND_ROOT
from app.core.app_config import AppConfig

logger = logging.getLogger(__name__)

PROCESSING_PLACEHOLDER = "聚合处理中……请先查看其他源或稍后刷新。"
WINDOW_CHAPTER_LIMIT = 5
RETRY_DELAYS_MINUTES = [5, 15, 30, 60, 120]

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
    "sourceCandidateLimit": 6,
    "purifyMode": "conservative",
    "primarySourceMode": "official",
    "primarySourcePriority": ["qidian_com_web"],  # Ordered list of preferred primary source IDs.
    "minSourceScore": 100,
    "aiEnabled": False,
    "blockedWordRepair": True,
    "sensitiveLexiconEnabled": True,
    "sensitiveLexiconPath": DEFAULT_LEXICON_PATH,
    "includePreviousChapters": 3,
    "deviationThreshold": 0.90,
    "promptTemplate": "",
    "systemPrompt": "",
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


def runtime_contract() -> dict[str, Any]:
    return {
        "windowChapterLimit": WINDOW_CHAPTER_LIMIT,
        "processingPlaceholder": PROCESSING_PLACEHOLDER,
        "retryDelaysMinutes": list(RETRY_DELAYS_MINUTES),
    }


def _merge_defaults(defaults: dict[str, Any], value: Any) -> dict[str, Any]:
    merged = deepcopy(defaults)
    if isinstance(value, dict):
        merged.update(value)
    return merged


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
        return _merge_defaults(DEFAULT_CONTENT_WORKFLOW, self._cfg.aggregate.content_workflow)

    def ai_provider_config(self) -> dict[str, Any]:
        return _provider_to_dict(self._cfg.ai_provider)

    def get_settings(self) -> dict[str, Any]:
        return {
            "contentWorkflow": self.content_workflow(),
            "aiProviderConfig": self.ai_provider_config(),
            "runtime": runtime_contract(),
        }

    def save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "contentWorkflow" in payload:
            value = payload.get("contentWorkflow")
            if isinstance(value, dict):
                current_wf = _merge_defaults(DEFAULT_CONTENT_WORKFLOW, self._cfg.aggregate.content_workflow)
                current_wf.update(value)
                self._cfg.set("aggregate.contentWorkflow", current_wf)

        if "aiProviderConfig" in payload:
            value = payload.get("aiProviderConfig")
            if isinstance(value, dict):
                self._cfg.set("ai.provider", _provider_from_dict(value))

        self._cfg.save()
        return self.get_settings()
