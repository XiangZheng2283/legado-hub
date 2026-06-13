"""File-based cookie store scoped to qidian_com only.

Only `qidian_com` reads/writes `plugins/sources/official/qidian_com/Cookie.json`.
All other plugin IDs are no-ops: `load` returns `{}`, `save`/`clear` do nothing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Project root is the parent of the backend directory.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
QIDIAN_COOKIE_PATH = PROJECT_ROOT / "plugins" / "sources" / "official" / "qidian_com" / "Cookie.json"


_SUPPORTED_PLUGIN_ID = "qidian_com"


def _supported(plugin_id: str) -> bool:
    return plugin_id == _SUPPORTED_PLUGIN_ID


def path_for(plugin_id: str) -> Path:
    """Return the Cookie.json path for a plugin.

    Only qidian_com has a real path; everything else resolves to the same path
    but will be guarded by `_supported` in mutating operations.
    """
    return QIDIAN_COOKIE_PATH


def exists(plugin_id: str) -> bool:
    if not _supported(plugin_id):
        return False
    return QIDIAN_COOKIE_PATH.exists()


def load(plugin_id: str) -> dict[str, dict[str, str]]:
    """Load cookie jar from Cookie.json for qidian_com.

    Returns an empty dict for any other plugin or if the file is missing/unreadable.
    """
    if not _supported(plugin_id):
        return {}

    if not QIDIAN_COOKIE_PATH.exists():
        return {}

    try:
        raw = json.loads(QIDIAN_COOKIE_PATH.read_text(encoding="utf-8"))
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
    """Write normalized cookie jar for qidian_com. No-op for other plugins."""
    if not _supported(plugin_id):
        return

    QIDIAN_COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)

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
    QIDIAN_COOKIE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clear(plugin_id: str) -> None:
    """Delete Cookie.json for qidian_com. No-op for other plugins."""
    if not _supported(plugin_id):
        return
    if QIDIAN_COOKIE_PATH.exists():
        QIDIAN_COOKIE_PATH.unlink()
