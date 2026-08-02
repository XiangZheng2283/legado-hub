"""Profile identity helpers for Source Access Bridge."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from pathlib import Path


def _safe_part(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or fallback


def make_profile_id(plugin_id: str, domain_profile: str = "default", proxy_profile: str = "direct") -> str:
    """Build a stable profile id bound to plugin, domain profile, and proxy."""
    plugin = _safe_part(plugin_id, "plugin")
    domain = _safe_part(domain_profile, "default")
    proxy = _safe_part(proxy_profile, "direct")
    digest = hashlib.sha256(f"{plugin_id}|{domain_profile}|{proxy_profile}".encode("utf-8")).hexdigest()[:12]
    return f"{plugin}-{domain}-{digest}" if proxy == "direct" else f"{plugin}-{domain}-{digest}-{proxy}"


@dataclass(frozen=True)
class BrowserProfileRef:
    plugin_id: str
    domain_profile: str = "default"
    proxy_profile: str = "direct"

    @property
    def profile_id(self) -> str:
        return make_profile_id(self.plugin_id, self.domain_profile, self.proxy_profile)


def profile_path(root: Path, ref: BrowserProfileRef) -> Path:
    """Return the profile directory for a profile reference."""
    return Path(root).resolve() / ref.profile_id


class BrowserProfileStore:
    """Persist Browserless storage state under stable profile directories."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def directory(self, ref: BrowserProfileRef) -> Path:
        return profile_path(self.root, ref)

    def storage_state_path(self, ref: BrowserProfileRef) -> Path:
        return self.storage_state_path_by_id(ref.profile_id)

    def directory_by_id(self, profile_id: str) -> Path:
        return self.root.resolve() / _safe_part(profile_id, "profile")

    def storage_state_path_by_id(self, profile_id: str) -> Path:
        return self.directory_by_id(profile_id) / "storage_state.json"

    def user_agent_path_by_id(self, profile_id: str) -> Path:
        return self.directory_by_id(profile_id) / "user_agent.txt"

    def read_storage_state(self, ref: BrowserProfileRef) -> dict[str, Any] | None:
        path = self.storage_state_path(ref)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def write_storage_state(self, ref: BrowserProfileRef, state: dict[str, Any]) -> Path:
        directory = self.directory(ref)
        directory.mkdir(parents=True, exist_ok=True)
        path = self.storage_state_path(ref)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def read_storage_state_by_id(self, profile_id: str) -> dict[str, Any] | None:
        path = self.storage_state_path_by_id(profile_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def write_storage_state_by_id(self, profile_id: str, state: dict[str, Any]) -> Path:
        directory = self.directory_by_id(profile_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = self.storage_state_path_by_id(profile_id)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def read_user_agent_by_id(self, profile_id: str) -> str:
        path = self.user_agent_path_by_id(profile_id)
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def write_user_agent_by_id(self, profile_id: str, user_agent: str) -> None:
        directory = self.directory_by_id(profile_id)
        directory.mkdir(parents=True, exist_ok=True)
        self.user_agent_path_by_id(profile_id).write_text(user_agent, encoding="utf-8")

    def clear_by_id(self, profile_id: str) -> None:
        """Drop a challenged browser state without touching unrelated profiles."""
        self.storage_state_path_by_id(profile_id).unlink(missing_ok=True)
        self.user_agent_path_by_id(profile_id).unlink(missing_ok=True)



