"""Unified application configuration.

All routine host configuration lives in backend/config/app_config.json.
This module loads it once and exposes typed getters so the rest of the
runtime does not scatter JSON reads across multiple files.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import CONFIG_DIR

APP_CONFIG_PATH = CONFIG_DIR / "app_config.json"


class AppConfigLoadError(RuntimeError):
    """Raised when an existing application configuration cannot be trusted."""


@dataclass
class AuthConfig:
    admin_password_base64: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuthConfig":
        return cls(admin_password_base64=str(data.get("adminPasswordBase64", "")))

    def admin_password(self) -> str | None:
        """Return the configured admin password if set, otherwise None."""
        value = self.admin_password_base64.strip()
        if not value:
            return None
        try:
            return base64.b64decode(value.encode("ascii")).decode("utf-8")
        except Exception:
            return None


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
    browser_source_timeout_seconds: float = 150.0
    browser_search_timeout_seconds: float = 60.0
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
            browser_source_timeout_seconds=float(data.get("browserSourceTimeoutSeconds", 150.0)),
            browser_search_timeout_seconds=float(data.get("browserSearchTimeoutSeconds", 60.0)),
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
class SubscriptionConfig:
    max_active_per_user: int = 100
    max_new_shared_books_per_day: int = 10
    max_global_provisioning_books: int = 20
    rate_limit_window_seconds: int = 60
    search_rate_limit_per_window: int = 30
    create_rate_limit_per_window: int = 10
    update_rate_limit_per_window: int = 60

    @staticmethod
    def _positive_int(value: Any, default: int) -> int:
        try:
            if isinstance(value, bool):
                raise ValueError
            return max(1, int(value))
        except (TypeError, ValueError):
            return default

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SubscriptionConfig":
        return cls(
            max_active_per_user=cls._positive_int(data.get("maxActivePerUser", 100), 100),
            max_new_shared_books_per_day=cls._positive_int(data.get("maxNewSharedBooksPerDay", 10), 10),
            max_global_provisioning_books=cls._positive_int(data.get("maxGlobalProvisioningBooks", 20), 20),
            rate_limit_window_seconds=cls._positive_int(data.get("rateLimitWindowSeconds", 60), 60),
            search_rate_limit_per_window=cls._positive_int(data.get("searchRateLimitPerWindow", 30), 30),
            create_rate_limit_per_window=cls._positive_int(data.get("createRateLimitPerWindow", 10), 10),
            update_rate_limit_per_window=cls._positive_int(data.get("updateRateLimitPerWindow", 60), 60),
        )


@dataclass
class ChapterCommentConfig:
    segment_enabled: bool = True
    page_enabled: bool = True
    chapter_enabled: bool = True

    @staticmethod
    def _bool_value(data: dict[str, Any], key: str, default: bool) -> bool:
        value = data.get(key, default)
        return value if isinstance(value, bool) else default

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChapterCommentConfig":
        return cls(
            segment_enabled=cls._bool_value(data, "segmentEnabled", True),
            page_enabled=cls._bool_value(data, "pageEnabled", True),
            chapter_enabled=cls._bool_value(data, "chapterEnabled", True),
        )


@dataclass
class ReadingAccessConfig:
    """Operator-facing reading entry base used by generated book sources."""

    public_base_url: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReadingAccessConfig":
        return cls(
            public_base_url=str(data.get("publicBaseUrl", "") or "").strip().rstrip("/"),
        )


@dataclass
class AggregateConfig:
    name: str = "LegadoHub 聚合"
    version: str = "0.0.2"
    group: str = "聚合,LegadoHub"
    enabled: bool = True
    base_url_mode: str = "request_host"
    generated_path: str = "backend/generated/legadohub-source.json"
    content_workflow: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AggregateConfig":
        return cls(
            name=str(data.get("name", "LegadoHub 聚合")),
            version=str(data.get("version", "0.0.2")),
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
        if not self.path.exists():
            self._data = {}
            return
        try:
            payload = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AppConfigLoadError(
                f"Unable to read existing application configuration: {self.path.name}"
            ) from exc
        try:
            raw = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise AppConfigLoadError(
                f"Existing application configuration is not valid JSON: {self.path.name}"
            ) from exc
        if not isinstance(raw, dict):
            raise AppConfigLoadError(
                f"Existing application configuration must contain a JSON object: {self.path.name}"
            )
        self._data = raw

    def reload(self) -> None:
        self._load()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=self.path.parent,
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(self._data, ensure_ascii=False, indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            if os.name != "nt":
                tmp_path.chmod(0o600)
            os.replace(tmp_path, self.path)
            if os.name != "nt":
                directory_fd = os.open(
                    self.path.parent,
                    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                )
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

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
    def subscription(self) -> SubscriptionConfig:
        return SubscriptionConfig.from_dict(self._section("subscription"))

    @property
    def chapter_comment(self) -> ChapterCommentConfig:
        return ChapterCommentConfig.from_dict(self._section("chapterComment"))

    @property
    def reading_access(self) -> ReadingAccessConfig:
        return ReadingAccessConfig.from_dict(self._section("readingAccess"))

    @property
    def ai_provider(self) -> AIProviderConfig:
        return AIProviderConfig.from_dict(self._section("ai").get("provider", {}))

    @property
    def debug(self) -> DebugConfig:
        return DebugConfig.from_dict(self._section("debug"))

    @property
    def auth(self) -> AuthConfig:
        return AuthConfig.from_dict(self._section("auth"))

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

    def unset(self, key: str) -> None:
        parts = key.split(".")
        current: Any = self._data
        for part in parts[:-1]:
            if not isinstance(current, dict) or part not in current:
                return
            current = current[part]
        if isinstance(current, dict):
            current.pop(parts[-1], None)
