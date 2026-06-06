"""Manage the curated source pool from config/phase2_sources.json."""

from __future__ import annotations

import json
from pathlib import Path

from app.rules.legado_adapter import adapt_source

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "phase2_sources.json"


class SourcePool:
    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or CONFIG_PATH
        self._config: dict | None = None
        self._sources: dict[str, dict] = {}

    def load(self) -> None:
        text = self.config_path.read_text(encoding="utf-8")
        self._config = json.loads(text)
        self._sources = {}
        for entry in self._config.get("sources", []):
            sid = entry["id"]
            path = Path(entry["path"])
            if path.exists():
                adapted = adapt_source(path)
                adapted["enabled"] = entry.get("enabled", True)
                adapted["priority"] = entry.get("priority", 0)
                adapted["proxyMode"] = entry.get("proxy_mode", "auto")
                adapted["configId"] = sid
                self._sources[sid] = adapted

    def get_proxy_config(self) -> dict:
        if self._config is None:
            self.load()
        return self._config.get("proxy", {}) if self._config else {}

    def get_config(self) -> dict:
        if self._config is None:
            self.load()
        return self._config or {}

    def get_enabled_sources(self) -> list[tuple[str, dict]]:
        if self._config is None:
            self.load()
        result = []
        for sid, src in self._sources.items():
            if src.get("enabled", True):
                result.append((sid, src))
        # Sort by priority descending
        result.sort(key=lambda x: x[1].get("priority", 0), reverse=True)
        return result

    def get_source(self, source_id: str) -> dict | None:
        if self._config is None:
            self.load()
        return self._sources.get(source_id)
