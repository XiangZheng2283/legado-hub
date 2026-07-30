"""Book-level shared source-map refresh via the existing backend search flow."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from app.source_plugins.id_codec import decode_book_id, encode_book_id
from app.services.library_books import LibraryBooksService
from app.services.live_acceptance import normalize_author_key, normalize_text
from app.services.search_coordinator import SearchCoordinator
from app.services.shared_book_storage import SharedBookStorage


logger = logging.getLogger(__name__)


class _CatalogLike(Protocol):
    async def book_detail(self, book_id: str, user_agent: str = "") -> dict[str, Any]: ...

    async def toc(self, book_id: str, user_agent: str = "") -> dict[str, Any]: ...


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
        catalog: _CatalogLike | None = None,
        chapter_count_concurrency: int = 4,
        refresh_ttl_hours: int = 6,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.library_books = library_books or LibraryBooksService()
        self.search_coordinator = search_coordinator or SearchCoordinator()
        self.storage = storage or self.library_books.shared_book_storage
        self._catalog = catalog
        self.chapter_count_concurrency = max(1, int(chapter_count_concurrency or 1))
        self.refresh_ttl = timedelta(hours=max(1, int(refresh_ttl_hours or 6)))
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
        if health_status and health_status not in {"healthy", "stale"}:
            return True, "unhealthy_status"
        verified_at = _parse_dt(health.get("lastVerifiedAt"))
        if verified_at is None:
            return True, "missing_last_verified_at"
        if self._now() - verified_at >= self.refresh_ttl:
            return True, "ttl_expired"
        if health_status == "stale":
            return False, "stale_waiting_ttl"
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
            # ``limit`` truncates the flattened result list, not the number
            # of sources. Keep every selected source's result here, then
            # deduplicate to its best matching book below.
            limit=None,
        )
        third_party_sources = self._select_matching_sources(
            items,
            target_name=book_name,
            target_author=author,
        )

        existing_sources = resolved_payload.get("sources") if isinstance(resolved_payload.get("sources"), list) else []
        primary_source_id = str(resolved_payload.get("primarySourceId", "") or "").strip()
        merged_sources = self._merge_sources(
            existing_sources,
            third_party_sources,
            primary_source_id=primary_source_id,
        )
        stale_source_ids = {
            str(item.get("sourceId", "") or "").strip()
            for item in merged_sources
            if isinstance(item, dict)
            and not third_party_sources
            and str(item.get("sourceId", "") or "").strip() != primary_source_id
            and not self.library_books._is_official(str(item.get("sourceId", "") or ""))
        }
        await self._fill_missing_chapter_counts(merged_sources)
        verified_at = self._now().isoformat()
        missing_critical_source = not any(
            str(item.get("sourceId", "") or "").strip()
            and not self.library_books._is_official(str(item.get("sourceId", "") or ""))
            for item in merged_sources
            if isinstance(item, dict)
        )
        status = (
            "missing_critical_source"
            if missing_critical_source
            else "stale"
            if stale_source_ids
            else "healthy"
        )

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
            stale_source_ids=stale_source_ids,
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
            source_book_id = str(item.get("bookId", "") or "").strip()
            try:
                decoded_source_id, decoded_book_url = decode_book_id(source_book_id)
            except Exception:
                decoded_source_id, decoded_book_url = "", ""
            if decoded_source_id != source_id or not decoded_book_url:
                source_book_id = encode_book_id(source_id, raw_book_url)
            normalized = {
                "bookId": source_book_id,
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
        primary_source_id: str,
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
            is_official = source_id == primary_source_id or self.library_books._is_official(source_id)
            if discovered_sources and not is_official:
                continue
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

    @staticmethod
    def _positive_int(value: object) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _catalog_book_id(source: dict[str, Any]) -> str:
        source_id = str(source.get("sourceId", "") or "").strip()
        if not source_id:
            return ""

        book_id = str(source.get("bookId", "") or "").strip()
        raw_book_url = str(source.get("bookUrl", "") or "").strip()
        candidates = [book_id]
        if "/api/legado/book/" in raw_book_url:
            candidates.append(raw_book_url.rsplit("/", 1)[-1])
        for candidate in candidates:
            try:
                decoded_source_id, decoded_book_url = decode_book_id(candidate)
            except Exception:
                continue
            if decoded_source_id == source_id and decoded_book_url:
                return candidate

        if raw_book_url and "/api/legado/book/" not in raw_book_url:
            return encode_book_id(source_id, raw_book_url)
        return ""

    def _get_catalog(self) -> _CatalogLike:
        if self._catalog is None:
            from app.services.catalog import Catalog

            self._catalog = Catalog()
        return self._catalog

    async def _fill_missing_chapter_counts(self, sources: list[dict[str, Any]]) -> None:
        """Fill absent source-map chapter counts from each plugin's real TOC."""
        missing = [
            source
            for source in sources
            if isinstance(source, dict) and self._positive_int(source.get("chapterCount")) <= 0
        ]
        if not missing:
            return

        semaphore = asyncio.Semaphore(self.chapter_count_concurrency)

        async def fill_one(source: dict[str, Any]) -> None:
            async with semaphore:
                await self._fill_missing_chapter_count(source)

        await asyncio.gather(*(fill_one(source) for source in missing))

    async def _fill_missing_chapter_count(self, source: dict[str, Any]) -> None:
        """Resolve one missing count without failing the source-map refresh."""
        source_id = str(source.get("sourceId", "") or "").strip()
        book_id = self._catalog_book_id(source)
        if not source_id or not book_id:
            return

        try:
            catalog = self._get_catalog()
            detail = await catalog.book_detail(book_id)
            detail_data = detail.get("data") if isinstance(detail, dict) else None
            if isinstance(detail_data, dict):
                raw_toc_url = str(
                    detail_data.get("rawTocUrl") or detail_data.get("tocUrl") or ""
                ).strip()
                if raw_toc_url and not str(source.get("tocUrl", "") or "").strip():
                    source["tocUrl"] = raw_toc_url

            toc = await catalog.toc(book_id)
        except Exception:
            logger.warning(
                "Failed to fill chapter count for source %s",
                source_id,
                exc_info=True,
            )
            return

        if not isinstance(toc, dict):
            return
        debug = toc.get("debug") if isinstance(toc.get("debug"), dict) else {}
        chapters = toc.get("chapters")
        if debug.get("error") or not isinstance(chapters, list) or not chapters:
            return
        source["chapterCount"] = len(chapters)

    def _build_private_source_refs(
        self,
        *,
        aggregate_book_id: str,
        payload: dict[str, Any],
        merged_sources: list[dict[str, Any]],
        verified_at: str,
        stale_source_ids: set[str],
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
                    "lastChapter": item.get("lastChapter", "") or "",
                    "chapterCount": int(item.get("chapterCount", 0) or 0),
                    "lastVerifiedAt": verified_at,
                    "status": (
                        "stale"
                        if str(item.get("sourceId", "") or "").strip() in stale_source_ids
                        else "healthy"
                    ),
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
                items = (
                    source_refs.get("sourceMapRefs")
                    if isinstance(source_refs, dict)
                    and str(source_refs.get("bookId", "") or "") == aggregate_book_id
                    else []
                )
                if isinstance(items, list):
                    refs = [item for item in items if isinstance(item, dict)]

        normalized: list[dict[str, Any]] = []
        fallback_payload = payload if isinstance(payload, dict) else {}
        payload_sources = fallback_payload.get("sources") if isinstance(fallback_payload.get("sources"), list) else []
        payload_by_key = {
            (
                str(item.get("sourceId", "") or "").strip(),
                str(item.get("bookId", "") or "").strip(),
            ): item
            for item in payload_sources
            if isinstance(item, dict)
        }
        for item in refs:
            source_id = str(item.get("sourceId", "") or "").strip()
            source_book_id = str(item.get("sourceBookId", "") or item.get("bookId", "") or "").strip()
            if not source_id or not source_book_id or source_id == primary_source_id:
                continue
            payload_item = payload_by_key.get((source_id, source_book_id), {})
            normalized.append(
                {
                    "sourceId": source_id,
                    "sourceName": item.get("sourceName", "") or source_id,
                    "bookId": source_book_id,
                    "bookUrl": item.get("bookUrl", "") or "",
                    "tocUrl": item.get("tocUrl", "") or "",
                    "score": int(item.get("priority", item.get("score", 0)) or 0),
                    "priority": int(item.get("priority", item.get("score", 0)) or 0),
                    "lastChapter": item.get("lastChapter", "") or payload_item.get("lastChapter", "") or "",
                    "chapterCount": int(item.get("chapterCount", payload_item.get("chapterCount", 0)) or 0),
                }
            )

        if normalized:
            normalized.sort(key=lambda item: (-int(item.get("priority", 0) or 0), item.get("sourceId", "")))
            return normalized

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
