"""Book-level shared source-map refresh via the existing backend search flow."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.services.library_books import LibraryBooksService
from app.services.live_acceptance import normalize_author_key, normalize_text
from app.services.search_coordinator import SearchCoordinator
from app.services.shared_book_storage import SharedBookStorage


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


class SharedBookSourceMapService:
    def __init__(
        self,
        *,
        library_books: LibraryBooksService | None = None,
        search_coordinator: SearchCoordinator | None = None,
        storage: SharedBookStorage | None = None,
        refresh_ttl_hours: int = 24,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.library_books = library_books or LibraryBooksService()
        self.search_coordinator = search_coordinator or SearchCoordinator()
        self.storage = storage or self.library_books.shared_book_storage
        self.refresh_ttl = timedelta(hours=max(1, int(refresh_ttl_hours or 24)))
        self._now_provider = now_provider or _utc_now

    def _now(self) -> datetime:
        return self._now_provider()

    def should_refresh(
        self,
        aggregate_book_id: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        metadata = self.library_books.load_shared_metadata(aggregate_book_id)
        if not metadata:
            return False, "no_metadata"
        source_map = metadata.get("sourceMap") if isinstance(metadata.get("sourceMap"), dict) else {}
        health = source_map.get("health") if isinstance(source_map.get("health"), dict) else {}
        if not health:
            return True, "missing_health"
        health_status = str(health.get("status", "") or "").strip()
        if bool(health.get("missingCriticalSource")):
            return True, "missing_critical_source"
        if health_status and health_status != "healthy":
            return True, "unhealthy_status"
        verified_at = _parse_dt(health.get("lastVerifiedAt"))
        if verified_at is None:
            return True, "missing_last_verified_at"
        if self._now() - verified_at >= self.refresh_ttl:
            return True, "ttl_expired"
        return False, "fresh"

    async def refresh_for_book(
        self,
        aggregate_book_id: str,
        *,
        payload: dict[str, Any] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        book = self.library_books.get_book(aggregate_book_id) or {}
        if not book:
            return {"bookId": aggregate_book_id, "success": False, "error": "book_not_found"}

        resolved_payload = payload if isinstance(payload, dict) and payload else self.library_books.load_payload(aggregate_book_id)
        if not isinstance(resolved_payload, dict):
            resolved_payload = {}

        book_name = str(book.get("name") or resolved_payload.get("name") or "").strip()
        author = str(book.get("author") or resolved_payload.get("author") or "").strip()
        if not book_name:
            return {"bookId": aggregate_book_id, "success": False, "error": "missing_book_name"}

        if not force:
            should_refresh, reason = self.should_refresh(aggregate_book_id, payload=resolved_payload)
            if not should_refresh:
                return {"bookId": aggregate_book_id, "success": True, "refreshed": False, "reason": reason}

        third_party_source_ids = self.search_coordinator.resolve_third_party_source_ids()
        items = await self.search_coordinator.search_source_map_candidates(
            book_name,
            source_ids=third_party_source_ids,
            limit=len(third_party_source_ids) or None,
        )
        third_party_sources = self._select_matching_sources(
            items,
            target_name=book_name,
            target_author=author,
        )

        existing_sources = resolved_payload.get("sources") if isinstance(resolved_payload.get("sources"), list) else []
        merged_sources = self._merge_sources(
            existing_sources,
            third_party_sources,
            primary_source_id=str(resolved_payload.get("primarySourceId", "") or "").strip(),
        )
        verified_at = self._now().isoformat()
        missing_critical_source = not any(
            str(item.get("sourceId", "") or "").strip()
            and not self.library_books._is_official(str(item.get("sourceId", "") or ""))
            for item in merged_sources
            if isinstance(item, dict)
        )
        status = "missing_critical_source" if missing_critical_source else "healthy"

        metadata = self.library_books.load_shared_metadata(aggregate_book_id)
        if not metadata:
            metadata = self.storage.build_shared_metadata(
                {
                    **resolved_payload,
                    "name": book_name,
                    "author": author,
                    "sources": merged_sources,
                }
            )
        summary = self._build_summary_rows(merged_sources)
        metadata["sourceMap"] = {
            "summary": summary,
            "health": {
                "lastVerifiedAt": verified_at,
                "status": status,
                "missingCriticalSource": missing_critical_source,
            },
        }
        metadata["sourceMapSummary"] = summary

        source_refs = self._build_private_source_refs(
            aggregate_book_id=aggregate_book_id,
            payload=resolved_payload,
            merged_sources=merged_sources,
            verified_at=verified_at,
        )

        metadata_path = self.storage.metadata_path(book_name=book_name, author=author)
        source_refs_path = self.storage.source_refs_path(book_name=book_name, author=author)
        self.storage.atomic_write_json(metadata_path, metadata)
        self.storage.atomic_write_json(source_refs_path, source_refs)
        self.library_books.save_payload_sources(aggregate_book_id, merged_sources)

        return {
            "bookId": aggregate_book_id,
            "success": True,
            "refreshed": True,
            "sourceCount": len(summary),
            "health": metadata["sourceMap"]["health"],
        }

    def _select_matching_sources(
        self,
        items: list[dict[str, Any]],
        *,
        target_name: str,
        target_author: str,
    ) -> list[dict[str, Any]]:
        name_key = normalize_text(target_name)
        author_key = normalize_author_key(target_author)
        best_by_source: dict[str, tuple[int, dict[str, Any]]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("sourceId", "") or "").strip()
            raw_book_url = str(item.get("rawBookUrl") or item.get("bookUrl") or "").strip()
            if not source_id or not raw_book_url:
                continue
            item_name = normalize_text(item.get("name", ""))
            item_author = normalize_author_key(item.get("author", ""))
            title_matches = bool(name_key and item_name and (item_name == name_key or name_key in item_name or item_name in name_key))
            author_matches = not author_key or not item_author or item_author == author_key or author_key in item_author or item_author in author_key
            if not title_matches or not author_matches:
                continue
            match_score = int(item.get("score", 0) or 0)
            if item_name == name_key:
                match_score += 1000
            if author_key and item_author == author_key:
                match_score += 250
            normalized = {
                "bookId": item.get("bookId", "") or f"{source_id}:{raw_book_url}",
                "sourceId": source_id,
                "sourceName": item.get("sourceName", "") or source_id,
                "bookUrl": raw_book_url,
                "tocUrl": item.get("tocUrl", "") or "",
                "score": int(item.get("score", 0) or 0),
                "lastChapter": item.get("lastChapter", "") or "",
                "chapterCount": int(item.get("chapterCount", 0) or 0),
                "bookStatus": item.get("bookStatus", "") or item.get("status", "") or "",
                "author": item.get("author", "") or "",
                "name": item.get("name", "") or "",
            }
            current = best_by_source.get(source_id)
            if current is None or match_score > current[0]:
                best_by_source[source_id] = (match_score, normalized)
        ranked = sorted(best_by_source.values(), key=lambda item: (-item[0], item[1].get("sourceName", "")))
        return [item[1] for item in ranked]

    def _merge_sources(
        self,
        existing_sources: list[dict[str, Any]],
        discovered_sources: list[dict[str, Any]],
        *,
        primary_source_id: str = "",
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for source in existing_sources:
            if not isinstance(source, dict):
                continue
            source_id = str(source.get("sourceId", "") or "").strip()
            book_id = str(source.get("bookId", "") or "").strip()
            if not source_id or not book_id:
                continue
            if source_id == primary_source_id or self.library_books._is_official(source_id):
                seen.add((source_id, book_id))
                merged.append(dict(source))
        for source in discovered_sources:
            source_id = str(source.get("sourceId", "") or "").strip()
            book_id = str(source.get("bookId", "") or "").strip()
            key = (source_id, book_id)
            if not source_id or not book_id or key in seen:
                continue
            seen.add(key)
            merged.append(dict(source))
        return merged

    def _build_summary_rows(self, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.storage.build_shared_metadata({"sources": sources}).get("sourceMapSummary", [])

    def _build_private_source_refs(
        self,
        *,
        aggregate_book_id: str,
        payload: dict[str, Any],
        merged_sources: list[dict[str, Any]],
        verified_at: str,
    ) -> dict[str, Any]:
        primary_source_id = str(payload.get("primarySourceId", "") or "").strip()
        primary_book_id = str(payload.get("primaryBookId", "") or "").strip()
        return {
            "schemaVersion": 1,
            "bookId": aggregate_book_id,
            "primarySource": {
                "sourceId": primary_source_id,
                "sourceName": payload.get("primarySourceName", "") or primary_source_id,
                "bookId": primary_book_id,
                "bookUrl": payload.get("primaryBookUrl", "") or "",
                "tocUrl": payload.get("primaryTocUrl", "") or "",
            },
            "sourceMapRefs": [
                {
                    "sourceId": item.get("sourceId", "") or "",
                    "sourceName": item.get("sourceName", "") or "",
                    "sourceBookId": item.get("bookId", "") or "",
                    "bookUrl": item.get("bookUrl", "") or "",
                    "tocUrl": item.get("tocUrl", "") or "",
                    "lastVerifiedAt": verified_at,
                    "status": "healthy",
                    "priority": int(item.get("score", 0) or 0),
                }
                for item in merged_sources
                if isinstance(item, dict)
            ],
        }

    def load_current_source_map_refs(
        self,
        aggregate_book_id: str,
        *,
        payload: dict[str, Any] | None = None,
        primary_source_id: str = "",
    ) -> list[dict[str, Any]]:
        """Load the current persisted source-map refs for Stage 2 candidate attempts."""
        book = self.library_books.get_book(aggregate_book_id) or {}
        book_name = str(book.get("name", "") or "").strip()
        author = str(book.get("author", "") or "").strip()
        refs: list[dict[str, Any]] = []

        if book_name:
            path = self.storage.source_refs_path(book_name=book_name, author=author)
            if path.exists():
                try:
                    source_refs = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    source_refs = {}
                items = source_refs.get("sourceMapRefs") if isinstance(source_refs, dict) else []
                if isinstance(items, list):
                    refs = [item for item in items if isinstance(item, dict)]

        normalized: list[dict[str, Any]] = []
        for item in refs:
            source_id = str(item.get("sourceId", "") or "").strip()
            source_book_id = str(item.get("sourceBookId", "") or item.get("bookId", "") or "").strip()
            if not source_id or not source_book_id or source_id == primary_source_id:
                continue
            normalized.append(
                {
                    "sourceId": source_id,
                    "sourceName": item.get("sourceName", "") or source_id,
                    "bookId": source_book_id,
                    "bookUrl": item.get("bookUrl", "") or "",
                    "tocUrl": item.get("tocUrl", "") or "",
                    "score": int(item.get("priority", item.get("score", 0)) or 0),
                    "priority": int(item.get("priority", item.get("score", 0)) or 0),
                }
            )

        if normalized:
            normalized.sort(key=lambda item: (-int(item.get("priority", 0) or 0), item.get("sourceId", "")))
            return normalized

        fallback_payload = payload if isinstance(payload, dict) else {}
        payload_sources = fallback_payload.get("sources") if isinstance(fallback_payload.get("sources"), list) else []
        fallback_rows: list[dict[str, Any]] = []
        for item in payload_sources:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("sourceId", "") or "").strip()
            book_id = str(item.get("bookId", "") or "").strip()
            if not source_id or not book_id or source_id == primary_source_id:
                continue
            fallback_rows.append(dict(item))
        fallback_rows.sort(key=lambda item: (-int(item.get("score", 0) or 0), str(item.get("sourceId", ""))))
        return fallback_rows
