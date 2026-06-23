"""Virtual aggregate source entries for Reading/Legado search results."""

from __future__ import annotations

import base64
import json
from typing import Any

from app.config import HOST, PORT
from app.source_plugins.id_codec import encode_book_id
from app.source_plugins.loader import PluginLoader

VIRTUAL_SOURCE_ID = "legadohub_ai_aggregate"
VIRTUAL_SOURCE_NAME = "LegadoHub AI聚合"
LIBRARY_BOOK_PREFIX = "legadohub://aggregate/library/"


def _pack_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def unpack_aggregate_book_url(book_url: str) -> dict[str, Any]:
    if book_url.startswith(LIBRARY_BOOK_PREFIX):
        aggregate_book_id = book_url[len(LIBRARY_BOOK_PREFIX):].strip()
        if not aggregate_book_id:
            raise ValueError("invalid aggregate library book url")
        return {"aggregateBookId": aggregate_book_id, "library": True}
    prefix = "legadohub://aggregate/book/"
    if not book_url.startswith(prefix):
        raise ValueError("invalid aggregate book url")
    encoded = book_url[len(prefix):]
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += "=" * padding
    payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def make_library_aggregate_book_url(aggregate_book_id: str) -> str:
    return f"{LIBRARY_BOOK_PREFIX}{aggregate_book_id}"


def unpack_aggregate_chapter_url(chapter_url: str) -> dict[str, Any]:
    prefix = "legadohub://aggregate/chapter/"
    if not chapter_url.startswith(prefix):
        raise ValueError("invalid aggregate chapter url")
    encoded = chapter_url[len(prefix):]
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += "=" * padding
    payload = json.loads(base64.urlsafe_b64decode(encoded).decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def make_aggregate_book_url(group: dict[str, Any]) -> str:
    items = [dict(item) for item in group.get("items", []) if isinstance(item, dict)]
    sources = []
    for item in items:
        book_id = item.get("bookId", "")
        raw_book_url = item.get("rawBookUrl") or item.get("bookUrl", "")
        source_id = item.get("sourceId", "")
        if not book_id and source_id and raw_book_url:
            book_id = encode_book_id(source_id, raw_book_url)
        if not book_id:
            continue
        sources.append({
            "bookId": book_id,
            "sourceId": source_id,
            "sourceName": item.get("sourceName", ""),
            "bookUrl": raw_book_url,
            "score": item.get("score", 0),
            "lastChapter": item.get("lastChapter", ""),
        })
    payload = {
        "candidateId": group.get("candidateId", ""),
        "name": group.get("name", ""),
        "author": group.get("author", ""),
        "sources": sources,
    }
    return f"legadohub://aggregate/book/{_pack_payload(payload)}"


def make_aggregate_chapter_url(
    aggregate_book_id: str,
    source_chapter_id: str,
    title: str = "",
    index: int = 0,
) -> str:
    payload = {
        "aggregateBookId": aggregate_book_id,
        "sourceChapterId": source_chapter_id,
        "title": title,
        "index": index,
    }
    return f"legadohub://aggregate/chapter/{_pack_payload(payload)}"


def make_aggregate_search_item(
    group: dict[str, Any],
    base_api: str | None = None,
    plugins: dict[str, Any] | None = None,
    min_source_score: int = 0,
) -> dict[str, Any] | None:
    items = [dict(item) for item in group.get("items", []) if isinstance(item, dict)]
    if not items:
        return None

    base_api = base_api or f"http://{HOST}:{PORT}"

    # Filter items below min source score.
    if min_source_score > 0:
        items = [i for i in items if i.get("score", 0) >= min_source_score]
    if not items:
        return None

    best = max(items, key=lambda item: item.get("score", 0))
    aggregate_book_url = make_aggregate_book_url(group)
    book_id = encode_book_id(VIRTUAL_SOURCE_ID, aggregate_book_url)
    actual_source_count = len(items)
    latest = str(best.get("lastChapter", "") or "").strip()
    author = str(group.get("author") or best.get("author", "") or "").strip()
    reading_parts = [VIRTUAL_SOURCE_NAME]
    if latest:
        reading_parts.append(latest)

    payload = unpack_aggregate_book_url(aggregate_book_url)
    primary_book_id = primary_book_id_from_payload(payload, plugins=plugins)
    primary_source_id = primary_book_id.split(":", 1)[0] if ":" in primary_book_id else ""

    if plugins is None:
        try:
            plugins = PluginLoader().load_all()
        except Exception:
            plugins = {}

    official_source_ids = sorted({
        item.get("sourceId", "")
        for item in items
        if item.get("sourceId") and plugins.get(item.get("sourceId")) and plugins[item.get("sourceId")].metadata.is_official_source()
    })
    primary_source_is_official = bool(
        primary_source_id and plugins.get(primary_source_id) and plugins[primary_source_id].metadata.is_official_source()
    )

    # Weighted average score (not best+1).
    avg_score = sum(i.get("score", 0) for i in items) / len(items) if items else 0
    aggregate_score = int(avg_score) + 1  # +1 to beat any single source at the average

    # Candidate summary for debugging/display.
    candidate_summary = [
        {"sourceId": i.get("sourceId", ""), "score": i.get("score", 0)}
        for i in sorted(items, key=lambda x: -x.get("score", 0))
    ]

    return {
        "sourceId": VIRTUAL_SOURCE_ID,
        "sourceName": VIRTUAL_SOURCE_NAME,
        "name": group.get("name") or best.get("name", ""),
        "author": author,
        "coverUrl": best.get("coverUrl", ""),
        "intro": f"聚合源：基于 {actual_source_count} 个候选书源，后续在此链路执行 AI 聚合、正文净化和屏蔽词修复。",
        "kind": "AI聚合",
        "lastChapter": latest,
        "readingLastChapter": " · ".join(reading_parts),
        "wordCount": best.get("wordCount", ""),
        "bookId": book_id,
        "rawBookUrl": aggregate_book_url,
        "bookUrl": f"{base_api}/api/legado/book/{book_id}",
        "candidateId": group.get("candidateId", ""),
        "aggregate": True,
        "sourceCount": actual_source_count,
        "score": aggregate_score,
        "candidateSummary": candidate_summary,
        "hasOfficialSource": bool(official_source_ids),
        "officialSourceIds": official_source_ids,
        "primarySourceId": primary_source_id,
        "primarySourceIsOfficial": primary_source_is_official,
    }


def aggregate_items_for_groups(
    groups: list[dict[str, Any]],
    base_api: str | None = None,
    plugins: dict[str, Any] | None = None,
    min_source_score: int = 0,
) -> list[dict[str, Any]]:
    if plugins is None:
        try:
            plugins = PluginLoader().load_all()
        except Exception:
            plugins = {}
    aggregate_items = []
    for group in groups:
        item = make_aggregate_search_item(
            group, base_api=base_api, plugins=plugins,
            min_source_score=min_source_score,
        )
        if item:
            aggregate_items.append(item)
    return aggregate_items


def primary_book_id_from_payload(payload: dict[str, Any], plugins: dict[str, Any] | None = None,
                                 source_priority: list[str] | None = None) -> str:
    """Select the best primary book ID from aggregate payload sources.

    Selection order:
    1. If *source_priority* is provided, find the first source whose sourceId
       appears in the priority list (respecting list order).
    2. Otherwise, fall back to official-first + highest-score logic.
    """
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    valid_sources = [s for s in sources if isinstance(s, dict) and s.get("bookId")]
    if not valid_sources:
        return ""

    # Path 1: user-configured priority list.
    if source_priority:
        for preferred_id in source_priority:
            for source in valid_sources:
                if source.get("sourceId") == preferred_id:
                    return source["bookId"]

    # Path 2: official-first + score-based fallback.
    if plugins is None:
        try:
            plugins = PluginLoader().load_all()
        except Exception:
            plugins = {}

    def _official_priority(source: dict[str, Any]) -> int:
        source_id = source.get("sourceId", "")
        plugin = plugins.get(source_id)
        return 1 if plugin and plugin.metadata.is_official_source() else 0

    ranked = sorted(
        valid_sources,
        key=lambda source: (_official_priority(source), source.get("score", 0)),
        reverse=True,
    )
    return ranked[0]["bookId"] if ranked else ""

