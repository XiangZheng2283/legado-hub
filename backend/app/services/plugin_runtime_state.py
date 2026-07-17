"""Lightweight runtime state for plugin ping health and errors.

This module intentionally does NOT use the main SQLite database.  State is kept
in a small JSON file under backend/runtime/ so it can be:

- cheaply cleared by deleting the file
- excluded from backups if desired
- rebuilt from scratch on demand

Long-lived facts (plugin metadata, enabled flags, aggregate sources) still live
in the database / app_config.  This file only holds ephemeral runtime state.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from app.config import RUNTIME_DIR

RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = RUNTIME_DIR / "plugin_state.json"

MAX_ATTEMPTS_PER_PLUGIN = 20


def _now_ms() -> int:
    return int(time.time() * 1000)


class PluginRuntimeState:
    """In-memory + JSON-backed runtime state for plugins."""

    def __init__(self, state_file: Path | str | None = None) -> None:
        self._state_file = Path(state_file) if state_file else STATE_FILE
        self._state: dict[str, Any] = {"version": 1, "plugins": {}}
        self._load()

    def _load(self) -> None:
        if not self._state_file.exists():
            return
        try:
            with open(self._state_file, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            plugins = loaded.get("plugins") if isinstance(loaded, dict) else None
            if isinstance(plugins, dict):
                for plugin_state in plugins.values():
                    if not isinstance(plugin_state, dict):
                        continue
                    last_smoke = plugin_state.pop("lastSmoke", None)
                    if isinstance(plugin_state.get("attempts"), list):
                        plugin_state["attempts"] = [
                            item for item in plugin_state["attempts"]
                            if not isinstance(item, dict) or item.get("type") != "smoke"
                        ]
                    if isinstance(last_smoke, dict) and last_smoke.get("error"):
                        last_error = plugin_state.get("lastError") or {}
                        if last_error.get("message") == last_smoke["error"]:
                            plugin_state.pop("lastError", None)
                self._state = loaded
        except (json.JSONDecodeError, OSError):
            self._state = {"version": 1, "plugins": {}}

    def _save(self) -> None:
        tmp = self._state_file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._state, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self._state_file)

    def _plugin_state(self, plugin_id: str) -> dict[str, Any]:
        return self._state["plugins"].setdefault(plugin_id, {})

    def record_ping(
        self,
        plugin_id: str,
        status: str,
        latency_ms: int,
        url: str | None = None,
        error: str | None = None,
        proxy_used: bool = False,
    ) -> None:
        entry = {
            "type": "ping",
            "status": status,
            "latencyMs": latency_ms,
            "url": url or "",
            "error": error or "",
            "proxyUsed": proxy_used,
            "timestamp": _now_ms(),
        }
        ps = self._plugin_state(plugin_id)
        ps["lastPing"] = entry
        if error:
            ps["lastError"] = {"message": error, "timestamp": _now_ms()}
        self._append_attempt(plugin_id, entry)
        self._save()

    def record_error(self, plugin_id: str, error: str) -> None:
        entry = {
            "type": "error",
            "message": str(error),
            "timestamp": _now_ms(),
        }
        ps = self._plugin_state(plugin_id)
        ps["lastError"] = {"message": str(error), "timestamp": _now_ms()}
        self._append_attempt(plugin_id, entry)
        self._save()

    def _append_attempt(self, plugin_id: str, entry: dict[str, Any]) -> None:
        ps = self._plugin_state(plugin_id)
        attempts = ps.setdefault("attempts", [])
        attempts.append(entry)
        if len(attempts) > MAX_ATTEMPTS_PER_PLUGIN:
            ps["attempts"] = attempts[-MAX_ATTEMPTS_PER_PLUGIN:]

    def get_state(self, plugin_id: str) -> dict[str, Any]:
        return self._plugin_state(plugin_id).copy()

    def get_all_states(self) -> dict[str, dict[str, Any]]:
        return {k: v.copy() for k, v in self._state["plugins"].items()}

    def get_attempts(self, plugin_id: str, limit: int = 20) -> list[dict[str, Any]]:
        ps = self._plugin_state(plugin_id)
        attempts = [item for item in ps.get("attempts", []) if item.get("type") != "smoke"]
        attempts.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
        return attempts[:limit]

    def clear(self) -> None:
        self._state = {"version": 1, "plugins": {}}
        if self._state_file.exists():
            self._state_file.unlink()


# Process-wide singleton
_runtime_state: PluginRuntimeState | None = None


def get_runtime_state() -> PluginRuntimeState:
    global _runtime_state
    if _runtime_state is None:
        _runtime_state = PluginRuntimeState()
    return _runtime_state
