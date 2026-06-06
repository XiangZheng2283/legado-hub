"""Adapt raw Legado source dicts into internal execution specs."""

from __future__ import annotations

from pathlib import Path

from app.rules.legado_loader import load_source_file


def adapt_source(path: Path) -> dict:
    """Adapt a single-object source file (backward compat)."""
    objects = load_source_file(path)
    if not objects:
        raise ValueError(f"No source objects in {path}")
    return adapt_source_dict(objects[0])


def adapt_source_dict(raw: dict) -> dict:
    """Adapt a raw Legado source dict into internal execution spec."""
    return {
        "sourceName": raw.get("bookSourceName", ""),
        "sourceUrl": raw.get("bookSourceUrl", ""),
        "searchUrl": raw.get("searchUrl", ""),
        "header": raw.get("header", ""),
        "ruleSearch": raw.get("ruleSearch", {}),
        "ruleBookInfo": raw.get("ruleBookInfo", {}),
        "ruleToc": raw.get("ruleToc", {}),
        "ruleContent": raw.get("ruleContent", {}),
        "exploreUrl": raw.get("exploreUrl", ""),
        "enabledExplore": raw.get("enabledExplore", False),
        "enabledCookieJar": raw.get("enabledCookieJar", False),
        "raw": raw,
    }
