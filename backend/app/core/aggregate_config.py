"""Aggregate source configuration management.

Aggregate settings now live in backend/config/app_config.json under the
``aggregate`` section. This module keeps the same public API but reads/writes
that section instead of a separate aggregate_source.json file.
"""

from __future__ import annotations

from typing import Any

from app.core.app_config import AppConfig


def load_aggregate_config() -> dict:
    cfg = AppConfig.get().aggregate
    return {
        "name": cfg.name,
        "version": cfg.version,
        "group": cfg.group,
        "enabled": cfg.enabled,
        "base_url_mode": cfg.base_url_mode,
        "generated_path": cfg.generated_path,
        "contentWorkflow": cfg.content_workflow,
        "last_generated_at": AppConfig.get().get_value("aggregate.lastGeneratedAt", ""),
        "parser_progress": AppConfig.get().get_value("aggregate.parserProgress", _default_progress()),
    }


def save_aggregate_config(config: dict) -> None:
    cfg = AppConfig.get()
    if "contentWorkflow" in config:
        cfg.set("aggregate.contentWorkflow", config["contentWorkflow"])
    for key in ("name", "version", "group", "enabled", "base_url_mode", "generated_path"):
        if key in config:
            cfg.set(f"aggregate.{key}", config[key])
    cfg.save()


def update_progress(progress: dict) -> None:
    cfg = AppConfig.get()
    cfg.set("aggregate.parserProgress", {**_default_progress(), **progress})
    cfg.set("aggregate.lastGeneratedAt", _now())
    cfg.save()


def _default_progress() -> dict[str, Any]:
    return {
        "configured_sources": 0,
        "enabled_sources": 0,
        "healthy_sources": 0,
        "proxy_sources": 0,
        "unsupported_sources": 0,
    }


def _default_config() -> dict:
    return {
        "name": "LegadoHub 聚合",
        "version": "0.0.1",
        "group": "聚合,LegadoHub",
        "enabled": True,
        "base_url_mode": "request_host",
        "generated_path": "backend/generated/legadohub-source.json",
        "last_generated_at": "",
        "parser_progress": _default_progress(),
    }


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
