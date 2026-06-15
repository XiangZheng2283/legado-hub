"""Settings repository and runtime constants for AI aggregate processing."""

from __future__ import annotations

import json
import logging
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_defaults(defaults: dict[str, Any], value: Any) -> dict[str, Any]:
    merged = deepcopy(defaults)
    if isinstance(value, dict):
        merged.update(value)
    return merged


def _loads_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


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


# ── JSON file helpers ────────────────────────────────────────────────────────


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class AggregateSettingsRepository:
    """Read/write aggregate settings.

    - contentWorkflow: stored in SQLite aggregate_settings table (unchanged)
    - aiProviderConfig: stored as plain-text JSON file at AI_PROVIDER_CONFIG_PATH
    """

    def __init__(self, db_path: str | Path | None = None):
        from app.config import DB_PATH, AI_PROVIDER_CONFIG_PATH

        self.db_path = Path(db_path or DB_PATH)
        self._ai_config_path = AI_PROVIDER_CONFIG_PATH

    # ── DB helpers (for contentWorkflow) ─────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def migrate_legacy_settings(self, conn: sqlite3.Connection) -> None:
        """Migrate contentWorkflow from admin_settings to aggregate_settings if needed."""
        row = conn.execute(
            "SELECT value_json FROM aggregate_settings WHERE key = 'contentWorkflow'"
        ).fetchone()
        if row:
            return
        legacy = conn.execute(
            "SELECT value_json FROM admin_settings WHERE key = 'contentWorkflow'"
        ).fetchone()
        if not legacy:
            return
        conn.execute(
            "INSERT OR REPLACE INTO aggregate_settings (key, value_json, updated_at) VALUES (?, ?, ?)",
            ("contentWorkflow", legacy[0], _now()),
        )

    def _db_get_raw(self, key: str) -> dict[str, Any]:
        with self._conn() as conn:
            self.migrate_legacy_settings(conn)
            row = conn.execute(
                "SELECT value_json FROM aggregate_settings WHERE key = ?",
                (key,),
            ).fetchone()
            conn.commit()
        return _loads_dict(row[0] if row else None)

    def content_workflow(self) -> dict[str, Any]:
        return _merge_defaults(DEFAULT_CONTENT_WORKFLOW, self._db_get_raw("contentWorkflow"))

    # ── AI provider config (JSON file) ──────────────────────────────────────

    def _migrate_ai_config_from_db(self) -> dict[str, Any]:
        """One-time migration: read encrypted aiProviderConfig from DB,
        decrypt the API key, and write to the JSON file."""
        raw = self._db_get_raw("aiProviderConfig")
        if not raw:
            return {}
        # Decrypt the API key if it was encrypted.
        api_key = str(raw.get("apiKey") or "")
        if api_key:
            try:
                from app.ai.encryption import decrypt_api_key
                raw["apiKey"] = decrypt_api_key(api_key)
            except Exception:
                pass  # Keep as-is if decryption fails (already plaintext).
        _write_json_file(self._ai_config_path, raw)
        logger.info("Migrated aiProviderConfig from database to %s", self._ai_config_path)
        return raw

    def ai_provider_config(self) -> dict[str, Any]:
        """Read AI provider config from JSON file. Falls back to DB migration."""
        raw = _read_json_file(self._ai_config_path)
        if not raw:
            raw = self._migrate_ai_config_from_db()
        config = _merge_defaults(DEFAULT_AI_PROVIDER_CONFIG, raw)
        config["hasApiKey"] = bool(config.get("apiKey"))
        return config

    def _save_ai_provider_config(self, incoming: dict[str, Any]) -> None:
        """Save AI provider config to JSON file, preserving existing API key if masked."""
        current = self.ai_provider_config()
        api_key = str(incoming.get("apiKey") or "")
        if _looks_masked(api_key) or not api_key:
            # Preserve the existing real key.
            incoming = {k: v for k, v in incoming.items() if k != "apiKey"}
        current.update(incoming)
        _write_json_file(self._ai_config_path, current)

    # ── Public API ──────────────────────────────────────────────────────────

    def get_settings(self) -> dict[str, Any]:
        return {
            "contentWorkflow": self.content_workflow(),
            "aiProviderConfig": self.ai_provider_config(),
            "runtime": runtime_contract(),
        }

    def save_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        # ── contentWorkflow → database (unchanged) ──────────────────────────
        if "contentWorkflow" in payload:
            current_wf = _merge_defaults(DEFAULT_CONTENT_WORKFLOW, self._db_get_raw("contentWorkflow"))
            value = payload.get("contentWorkflow")
            if isinstance(value, dict):
                current_wf.update(value)
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO aggregate_settings (key, value_json, updated_at) VALUES (?, ?, ?)",
                    ("contentWorkflow", json.dumps(current_wf, ensure_ascii=False), _now()),
                )
                conn.commit()

        # ── aiProviderConfig → JSON file ────────────────────────────────────
        if "aiProviderConfig" in payload:
            value = payload.get("aiProviderConfig")
            if isinstance(value, dict):
                self._save_ai_provider_config(value)

        return self.get_settings()
