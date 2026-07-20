"""Host-managed cookie store for source plugins.

Cookie files live under backend/config/cookies/<plugin_id>.json. The host does
not interpret the payload structure; plugins define their own schema. The host
only provides load/save/clear/has primitives.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from app.config import CONFIG_DIR

COOKIE_DIR = CONFIG_DIR / "cookies"
PLUGIN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class CookieStore:
    """File-based cookie payload store keyed by plugin_id."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or COOKIE_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.base_dir.chmod(0o700)

    def path_for(self, plugin_id: str) -> Path:
        normalized = str(plugin_id or "").strip()
        if not PLUGIN_ID_PATTERN.fullmatch(normalized):
            raise ValueError("Invalid plugin id for cookie storage")
        return self.base_dir / f"{normalized}.json"

    def has(self, plugin_id: str) -> bool:
        return self.path_for(plugin_id).exists()

    def load(self, plugin_id: str) -> Any:
        path = self.path_for(plugin_id)
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return raw

    def save(self, plugin_id: str, payload: Any) -> None:
        path = self.path_for(plugin_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            if os.name != "nt":
                temporary_path.chmod(0o600)
            os.replace(temporary_path, path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def clear(self, plugin_id: str) -> None:
        path = self.path_for(plugin_id)
        if path.exists():
            path.unlink()

    def list_plugin_ids(self) -> list[str]:
        """Return all plugin ids that have a saved cookie file."""
        ids: list[str] = []
        if not self.base_dir.exists():
            return ids
        for path in self.base_dir.glob("*.json"):
            if path.is_file():
                ids.append(path.stem)
        return ids


def migrate_legacy_plugin_cookies(store: CookieStore | None = None) -> dict[str, bool]:
    """One-time migration of plugin-directory Cookie.json files to the host store.

    Old path: plugins/sources/<...>/<plugin_id>/Cookie.json
    New path: backend/config/cookies/<plugin_id>.json

    Returns a map of plugin_id -> migrated.
    """
    from app.config import PLUGINS_DIR

    store = store or CookieStore()
    migrated: dict[str, bool] = {}
    if not PLUGINS_DIR.exists():
        return migrated

    for cookie_path in PLUGINS_DIR.rglob("Cookie.json"):
        # Resolve plugin id from the parent directory name heuristic.
        plugin_dir = cookie_path.parent
        plugin_id = plugin_dir.name
        if not plugin_id:
            continue
        try:
            already_exists = store.has(plugin_id)
        except ValueError:
            continue
        if already_exists:
            migrated[plugin_id] = False
            continue
        try:
            payload = json.loads(cookie_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        store.save(plugin_id, payload)
        migrated[plugin_id] = True
    return migrated
