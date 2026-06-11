"""Helpers for source-owned search result enrichment."""

from __future__ import annotations

import asyncio
from typing import Any


DEFAULT_ENRICH_FIELDS = (
    "author",
    "coverUrl",
    "intro",
    "kind",
    "lastChapter",
    "wordCount",
    "updateTime",
)


def needs_detail_enrichment(item: dict[str, Any], fields: tuple[str, ...] = DEFAULT_ENRICH_FIELDS) -> bool:
    """Return true when a search result should be completed from detail()."""
    if not item.get("bookUrl"):
        return False
    return any(not item.get(field) for field in fields)


async def enrich_search_items_from_detail(
    source: Any,
    ctx: Any,
    items: list[dict[str, Any]],
    *,
    limit: int = 3,
    timeout: float = 3.0,
    fields: tuple[str, ...] = DEFAULT_ENRICH_FIELDS,
) -> list[dict[str, Any]]:
    """Let a source complete sparse search results with its own detail parser.

    The scheduler intentionally does not call this helper. Source plugins opt in
    from their search() method when the site's search page omits standard fields.
    """
    enriched = 0
    for item in items:
        if enriched >= limit:
            break
        if not isinstance(item, dict) or not needs_detail_enrichment(item, fields):
            continue
        try:
            detail = await asyncio.wait_for(source.detail(ctx, item["bookUrl"]), timeout=timeout)
        except Exception as exc:
            trace = getattr(ctx, "trace", None)
            if callable(trace):
                trace("search_detail_enrich_error", url=item.get("bookUrl", ""), message=str(exc))
            continue
        if not isinstance(detail, dict):
            continue
        for field in fields:
            if not item.get(field) and detail.get(field):
                item[field] = detail[field]
        if detail.get("tocUrl"):
            item.setdefault("tocUrl", detail["tocUrl"])
        item.setdefault("extra", {})
        if isinstance(item["extra"], dict):
            item["extra"]["detailEnriched"] = True
        enriched += 1
    return items
