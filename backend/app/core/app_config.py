"""Unified application configuration.

All routine host configuration lives in backend/config/app_config.json.
This module loads it once and exposes typed getters so the rest of the
runtime does not scatter JSON reads across multiple files.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import CONFIG_DIR

APP_CONFIG_PATH = CONFIG_DIR / "app_config.json"


@dataclass
class ProxyConfig:
    enabled: bool = False
    url: str = ""
    allow_auto_retry: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProxyConfig":
        return cls(
            enabled=bool(data.get("enabled", False)),
            url=str(data.get("url", "")),
            allow_auto_retry=bool(data.get("allowAutoRetry", False)),
        )


@dataclass
class SearchConfig:
    task_concurrency: int = 4
    global_source_concurrency: int = 20
    site_concurrency: int = 3
    browser_source_concurrency: int = 2
    source_timeout_seconds: float = 8.0
    overall_timeout_seconds: float = 120.0
    fast_source_timeout_seconds: float = 5.0
    browser_source_timeout_seconds: float = 30.0
    browser_search_timeout_seconds: float = 30.0
    first_result_timeout_seconds: float = 5.0
    score_filter: int = 100
    cache_ttl_seconds: int = 600
    max_results_per_source: int = 50
    default_user_agent: str = ""
    # Dual timeout
    source_soft_timeout_seconds: float = 6.0
    source_hard_timeout_seconds: float = 25.0
    aggregate_overall_timeout_seconds: float = 180.0
    # Official source
    official_source_in_normal_search: bool = False
    official_source_bonus: int = 50

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SearchConfig":
        return cls(
            task_concurrency=int(data.get("taskConcurrency", 4)),
            global_source_concurrency=int(data.get("globalSourceConcurrency", 20)),
            site_concurrency=int(data.get("siteConcurrency", 3)),
            browser_source_concurrency=int(data.get("browserSourceConcurrency", 2)),
            source_timeout_seconds=float(data.get("sourceTimeoutSeconds", 8.0)),
            overall_timeout_seconds=float(data.get("overallTimeoutSeconds", 120.0)),
            fast_source_timeout_seconds=float(data.get("fastSourceTimeoutSeconds", 5.0)),
            browser_source_timeout_seconds=float(data.get("browserSourceTimeoutSeconds", 30.0)),
            browser_search_timeout_seconds=float(data.get("browserSearchTimeoutSeconds", 30.0)),
            first_result_timeout_seconds=float(data.get("firstResultTimeoutSeconds", 5.0)),
            score_filter=int(data.get("scoreFilter", 100)),
            cache_ttl_seconds=int(data.get("cacheTtlSeconds", 600)),
            max_results_per_source=int(data.get("maxResultsPerSource", 50)),
            default_user_agent=str(data.get("defaultUserAgent", "")),
            source_soft_timeout_seconds=float(data.get("sourceSoftTimeoutSeconds", 6.0)),
            source_hard_timeout_seconds=float(data.get("sourceHardTimeoutSeconds", 25.0)),
            aggregate_overall_timeout_seconds=float(data.get("aggregateOverallTimeoutSeconds", 180.0)),
            official_source_in_normal_search=bool(data.get("officialSourceInNormalSearch", False)),
            official_source_bonus=int(data.get("officialSourceBonus", 50)),
        )


@dataclass
class AggregateConfig:
    name: str = "LegadoHub 聚合"
    version: str = "0.0.1"
    group: str = "聚合,LegadoHub"
    enabled: bool = True
    base_url_mode: str = "request_host"
    generated_path: str = "backend/generated/legadohub-source.json"
    content_workflow: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AggregateConfig":
        return cls(
            name=str(data.get("name", "LegadoHub 聚合")),
            version=str(data.get("version", "0.0.1")),
            group=str(data.get("group", "聚合,LegadoHub")),
            enabled=bool(data.get("enabled", True)),
            base_url_mode=str(data.get("baseUrlMode", "request_host")),
            generated_path=str(data.get("generatedPath", "backend/generated/legadohub-source.json")),
            content_workflow=dict(data.get("contentWorkflow", {})),
        )


@dataclass
class AIProviderConfig:
    provider: str = "openai_compatible"
    name: str = ""
    base_url: str = ""
    api_key: str = ""
    api_key_field: str = "api_key"
    model: str = ""
    model_context_length: int = 256000
    max_context_use_ratio: float = 0.5
    max_output_tokens: int = 8192
    timeout_ms: int = 120000
    ai_max_concurrency: int = 2
    book_default_concurrency: int = 1
    temperature: float = 0.3
    top_p: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    seed: int = 0
    endpoint_candidates: list[str] = field(default_factory=list)
    models_url: str = ""
    custom_headers: dict[str, str] = field(default_factory=dict)
    custom_body_params: dict[str, Any] = field(default_factory=dict)
    thinking_level: str = "medium"
    compat_overrides: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AIProviderConfig":
        return cls(
            provider=str(data.get("provider", "openai_compatible")),
            name=str(data.get("name", "")),
            base_url=str(data.get("baseUrl", "")),
            api_key=str(data.get("apiKey", "")),
            api_key_field=str(data.get("apiKeyField", "api_key")),
            model=str(data.get("model", "")),
            model_context_length=int(data.get("modelContextLength", 256000)),
            max_context_use_ratio=float(data.get("maxContextUseRatio", 0.5)),
            max_output_tokens=int(data.get("maxOutputTokens", 8192)),
            timeout_ms=int(data.get("timeoutMs", 120000)),
            ai_max_concurrency=int(data.get("aiMaxConcurrency", 2)),
            book_default_concurrency=int(data.get("bookDefaultConcurrency", 1)),
            temperature=float(data.get("temperature", 0.3)),
            top_p=float(data.get("topP", 1.0)),
            frequency_penalty=float(data.get("frequencyPenalty", 0.0)),
            presence_penalty=float(data.get("presencePenalty", 0.0)),
            seed=int(data.get("seed", 0)),
            endpoint_candidates=list(data.get("endpointCandidates", [])),
            models_url=str(data.get("modelsUrl", "")),
            custom_headers=dict(data.get("customHeaders", {})),
            custom_body_params=dict(data.get("customBodyParams", {})),
            thinking_level=str(data.get("thinkingLevel", "medium")),
            compat_overrides=dict(data.get("compatOverrides", {})),
        )


@dataclass
class DebugConfig:
    log_level: str = "info"
    bypass_cache_default: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DebugConfig":
        return cls(
            log_level=str(data.get("logLevel", "info")),
            bypass_cache_default=bool(data.get("bypassCacheDefault", False)),
        )


class AppConfig:
    """Runtime configuration singleton.

    Loads backend/config/app_config.json. The file is the single source of
    truth for routine host settings.
    """

    _instance: AppConfig | None = None
    _lock = threading.Lock()

    def __init__(self, path: Path | None = None):
        self.path = path or APP_CONFIG_PATH
        self._data: dict[str, Any] = {}
        self._load()

    @classmethod
    def get(cls) -> "AppConfig":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._instance = None

    def _load(self) -> None:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._data = raw if isinstance(raw, dict) else {}
            except (json.JSONDecodeError, OSError):
                self._data = {}
        else:
            self._data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def raw(self) -> dict[str, Any]:
        return dict(self._data)

    def _section(self, key: str) -> dict[str, Any]:
        return dict(self._data.get(key, {}))

    @property
    def proxy(self) -> ProxyConfig:
        return ProxyConfig.from_dict(self._section("proxy"))

    @property
    def search(self) -> SearchConfig:
        return SearchConfig.from_dict(self._section("search"))

    @property
    def aggregate(self) -> AggregateConfig:
        return AggregateConfig.from_dict(self._section("aggregate"))

    @property
    def ai_provider(self) -> AIProviderConfig:
        return AIProviderConfig.from_dict(self._section("ai").get("provider", {}))

    @property
    def debug(self) -> DebugConfig:
        return DebugConfig.from_dict(self._section("debug"))

    def is_plugin_enabled(self, plugin_id: str, default: bool = True) -> bool:
        """Return runtime enabled state for a plugin from app_config.json.

        When no explicit entry exists, fall back to the plugin metadata default.
        """
        enabled_map = self._section("plugins").get("enabled", {})
        if plugin_id in enabled_map:
            return bool(enabled_map[plugin_id])
        return default

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        """Persist runtime enabled state for a plugin to app_config.json."""
        if "plugins" not in self._data or not isinstance(self._data["plugins"], dict):
            self._data["plugins"] = {}
        if "enabled" not in self._data["plugins"] or not isinstance(self._data["plugins"]["enabled"], dict):
            self._data["plugins"]["enabled"] = {}
        self._data["plugins"]["enabled"][plugin_id] = bool(enabled)
        self.save()

    def get_value(self, key: str, default: Any = None) -> Any:
        parts = key.split(".")
        current: Any = self._data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def set(self, key: str, value: Any) -> None:
        parts = key.split(".")
        current = self._data
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value
