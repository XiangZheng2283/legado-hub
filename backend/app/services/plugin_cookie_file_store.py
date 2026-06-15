"""File-based cookie store scoped per plugin directory.

Cookie.json is written to the plugin's own root directory, e.g.:
  plugins/sources/official/qidian_com/Cookie.json
  plugins/sources/official/qidian_com_app/Cookie.json

Previously this module was hardcoded to qidian_com only. It is now generic:
scan plugins/sources for a directory whose metadata.yaml id matches the
plugin_id, and use that directory as the cookie home.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from app.config import PLUGINS_DIR


# ---------------------------------------------------------------------------
# Plugin directory resolution
# ---------------------------------------------------------------------------

_plugin_dir_cache: dict[str, Path | None] = {}


def _resolve_plugin_dir(plugin_id: str) -> Path | None:
    """Locate plugin directory by scanning plugins/sources recursively."""
    if plugin_id in _plugin_dir_cache:
        return _plugin_dir_cache[plugin_id]

    if not PLUGINS_DIR.exists():
        _plugin_dir_cache[plugin_id] = None
        return None

    for metadata_path in PLUGINS_DIR.rglob("metadata.yaml"):
        try:
            raw = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw.get("id") == plugin_id:
                plugin_dir = metadata_path.parent
                _plugin_dir_cache[plugin_id] = plugin_dir
                return plugin_dir
        except Exception:
            continue

    _plugin_dir_cache[plugin_id] = None
    return None


def invalidate_plugin_dir_cache(plugin_id: str | None = None) -> None:
    """Clear the plugin directory cache.

    Call with no argument to clear the entire cache, or pass a plugin_id
    to remove a single entry (useful after plugin reloads).
    """
    global _plugin_dir_cache
    if plugin_id is None:
        _plugin_dir_cache = {}
    else:
        _plugin_dir_cache.pop(plugin_id, None)


# ---------------------------------------------------------------------------
# Cookie.json operations
# ---------------------------------------------------------------------------

def has_plugin_dir(plugin_id: str) -> bool:
    """Return True if a plugin directory exists for the given plugin ID."""
    return _resolve_plugin_dir(plugin_id) is not None


def path_for(plugin_id: str) -> Path:
    """Return the Cookie.json path for a plugin.

    Falls back to the legacy qidian_com path if the plugin directory cannot be
    resolved, so existing callers/tests keep working.
    """
    plugin_dir = _resolve_plugin_dir(plugin_id)
    if plugin_dir is None:
        # Legacy fallback for unknown plugin IDs / tests.
        return PLUGINS_DIR / "official" / "qidian_com" / "Cookie.json"
    return plugin_dir / "Cookie.json"


def exists(plugin_id: str) -> bool:
    return path_for(plugin_id).exists()


def load(plugin_id: str) -> dict[str, dict[str, str]]:
    """Load cookie jar from Cookie.json for a plugin.

    Returns an empty dict if the file is missing/unreadable or the plugin
    directory cannot be found.
    """
    cookie_path = path_for(plugin_id)
    if not cookie_path.exists():
        return {}

    try:
        raw = json.loads(cookie_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    if not isinstance(raw, dict):
        return {}

    cookies = raw.get("cookies")
    if isinstance(cookies, dict):
        return {
            str(domain): {str(k): str(v) for k, v in jar.items() if v is not None}
            for domain, jar in cookies.items()
            if isinstance(jar, dict)
        }

    # Compatibility: legacy files that stored the jar directly.
    if all(isinstance(v, dict) for v in raw.values() if isinstance(v, dict)):
        return {
            str(domain): {str(k): str(v) for k, v in jar.items() if v is not None}
            for domain, jar in raw.items()
            if isinstance(jar, dict)
        }

    return {}


def save(plugin_id: str, cookie_jar: dict[str, dict[str, str]]) -> None:
    """Write normalized cookie jar to the plugin's Cookie.json."""
    cookie_path = path_for(plugin_id)
    cookie_path.parent.mkdir(parents=True, exist_ok=True)

    normalized: dict[str, dict[str, str]] = {}
    for domain, jar in cookie_jar.items():
        if not isinstance(jar, dict):
            continue
        filtered = {str(k): str(v) for k, v in jar.items() if v is not None}
        if filtered:
            normalized[str(domain)] = filtered

    payload: dict[str, Any] = {
        "pluginId": plugin_id,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "cookies": normalized,
    }
    cookie_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clear(plugin_id: str) -> None:
    """Delete Cookie.json for a plugin."""
    cookie_path = path_for(plugin_id)
    if cookie_path.exists():
        cookie_path.unlink()
