"""Adapt raw Legado source dicts into internal LegadoSource models."""

from __future__ import annotations

from app.legado_engine.models import LegadoSource


def adapt_source_dict(raw: dict) -> LegadoSource:
    """Convert a raw Legado source dict into a LegadoSource model."""
    return LegadoSource(
        source_id=raw.get("configId", ""),
        source_name=raw.get("bookSourceName", ""),
        source_url=raw.get("bookSourceUrl", ""),
        search_url=raw.get("searchUrl", ""),
        explore_url=raw.get("exploreUrl", ""),
        header=raw.get("header", ""),
        enabled_cookie_jar=raw.get("enabledCookieJar", False),
        rule_search=raw.get("ruleSearch", {}),
        rule_book_info=raw.get("ruleBookInfo", {}),
        rule_toc=raw.get("ruleToc", {}),
        rule_content=raw.get("ruleContent", {}),
        raw=raw.get("raw", raw),
    )


def to_execution_dict(source: LegadoSource) -> dict:
    """Convert LegadoSource back to the execution dict used by existing pipelines."""
    return {
        "sourceName": source.source_name,
        "sourceUrl": source.source_url,
        "searchUrl": source.search_url,
        "header": source.header,
        "ruleSearch": source.rule_search,
        "ruleBookInfo": source.rule_book_info,
        "ruleToc": source.rule_toc,
        "ruleContent": source.rule_content,
        "exploreUrl": source.explore_url,
        "enabledExplore": bool(source.explore_url),
        "enabledCookieJar": source.enabled_cookie_jar,
        "raw": source.raw,
    }
