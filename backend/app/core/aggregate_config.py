"""Aggregate source configuration management."""

from __future__ import annotations

import json

from app.config import AGGREGATE_CONFIG_PATH

CONFIG_PATH = AGGREGATE_CONFIG_PATH


def load_aggregate_config() -> dict:
    if not CONFIG_PATH.exists():
        return _default_config()
    text = CONFIG_PATH.read_text(encoding="utf-8")
    return json.loads(text)


def save_aggregate_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def update_progress(progress: dict) -> None:
    config = load_aggregate_config()
    config["parser_progress"] = progress
    config["last_generated_at"] = _now()
    save_aggregate_config(config)


def _default_config() -> dict:
    return {
        "name": "LegadoHub 聚合",
        "version": "0.0.1",
        "group": "聚合,LegadoHub",
        "enabled": True,
        "base_url_mode": "request_host",
        "generated_path": "backend/generated/legadohub-source.json",
        "last_generated_at": "",
        "parser_progress": {
            "configured_sources": 0,
            "enabled_sources": 0,
            "healthy_sources": 0,
            "proxy_sources": 0,
            "unsupported_sources": 0,
        },
    }


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
