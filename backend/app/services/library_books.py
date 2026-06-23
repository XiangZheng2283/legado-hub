"""Shared aggregate library services.

Copyright (c) 2026 moo. All rights reserved.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.config import DB_PATH, HOST, PORT
from app.services.aggregate_settings import AggregateSettingsRepository
from app.services.aggregate_virtual_source import (
    VIRTUAL_SOURCE_ID,
    VIRTUAL_SOURCE_NAME,
    primary_book_id_from_payload,
)
from app.services.live_acceptance import normalize_author_key, normalize_text
from app.source_plugins.id_codec import encode_book_id
from app.source_plugins.loader import PluginLoader
from app.storage.db import initialize_database


def make_library_aggregate_book_url(aggregate_book_id: str) -> str:
    return f"legadohub://aggregate/library/{aggregate_book_id}"


def make_library_book_id(aggregate_book_id: str) -> str:
    return encode_book_id(VIRTUAL_SOURCE_ID, make_library_aggregate_book_url(aggregate_book_id))


class LibraryBooksService:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        initialize_database(self.db_path)
        return sqlite3.connect(self.db_path)

    def _plugins(self) -> dict[str, Any]:
        try:
            return PluginLoader().load_all()
        except Exception:
            return {}

    def _is_official(self, source_id: str) -> bool:
        plugin = self._plugins().get(source_id)
        return bool(plugin and plugin.metadata.is_official_source())

    def _merged_book_settings(self) -> dict[str, Any]:
        workflow = AggregateSettingsRepository(self.db_path).content_workflow()
        merged = {
            "autoTrackUpdates": True,
            "updateIntervalMinutes": 60,
            "primarySourceMode": "official",
            "aiAggregateEnabled": True,
            "aiPurifyEnabled": True,
            "sourcePriorityMode": "auto",
            "sourcePriority": [],
        }
        merged.update(
            {
                "autoTrackUpdates": bool(workflow.get("autoAggregate", True)),
                "updateIntervalMinutes": int(workflow.get("aggregateCheckIntervalMinutes") or 60),
                "primarySourceMode": workflow.get("primarySourceMode", "official"),
                "aiAggregateEnabled": bool(workflow.get("aiEnabled", True)),
                "aiPurifyEnabled": bool(workflow.get("blockedWordRepair", True)),
                "sourcePriorityMode": "manual" if workflow.get("primarySourcePriority") else "auto",
                "sourcePriority": list(workflow.get("primarySourcePriority") or []),
            }
        )
        return merged

    def _canonical_name(self, value: str) -> str:
        return normalize_text(value or "")

    def _canonical_author(self, value: str) -> str:
        return normalize_author_key(value or "")

    def _payload_from_group(self, group: dict[str, Any]) -> dict[str, Any]:
        items = [dict(item) for item in group.get("items", []) if isinstance(item, dict)]
        sources = []
        for item in items:
            source_id = item.get("sourceId", "")
            raw_book_url = item.get("rawBookUrl") or item.get("bookUrl", "")
            book_id = item.get("bookId", "")
            if not book_id and source_id and raw_book_url:
                book_id = encode_book_id(source_id, raw_book_url)
            if not source_id or not raw_book_url or not book_id:
                continue
            sources.append(
                {
                    "bookId": book_id,
                    "sourceId": source_id,
                    "sourceName": item.get("sourceName", ""),
                    "bookUrl": raw_book_url,
                    "score": int(item.get("score", 0) or 0),
                    "lastChapter": item.get("lastChapter", "") or "",
                    "coverUrl": item.get("coverUrl", "") or "",
                    "intro": item.get("intro", "") or "",
                    "wordCount": item.get("wordCount", "") or "",
                    "author": item.get("author", "") or "",
                    "name": item.get("name", "") or "",
                }
            )
        return {
            "candidateId": group.get("candidateId", ""),
            "name": group.get("name", "") or (sources[0].get("name", "") if sources else ""),
            "author": group.get("author", "") or (sources[0].get("author", "") if sources else ""),
            "sources": sources,
        }

    def _display_item_for_group(self, group: dict[str, Any]) -> dict[str, Any]:
        items = [dict(item) for item in group.get("items", []) if isinstance(item, dict)]
        if not items:
            return {}
        official_items = [item for item in items if self._is_official(item.get("sourceId", ""))]
        ranked = official_items or sorted(items, key=lambda item: -int(item.get("score", 0) or 0))
        return dict(ranked[0]) if ranked else {}

    def _aggregate_book_row_to_dict(self, row: sqlite3.Row | tuple | None) -> dict[str, Any] | None:
        if not row:
            return None
        if isinstance(row, sqlite3.Row):
            row = tuple(row)
        return {
            "aggregateBookId": row[0],
            "canonicalName": row[1] or "",
            "canonicalAuthor": row[2] or "",
            "name": row[3] or "",
            "author": row[4] or "",
            "coverUrl": row[5] or "",
            "intro": row[6] or "",
            "wordCount": row[7] or "",
            "primaryBookId": row[8] or "",
            "primarySourceId": row[9] or "",
            "addedByUserId": row[10] or "",
            "startChapterIndex": int(row[11] or 1),
            "initialSnapshotLastIndex": int(row[12] or 0),
            "backfillStarted": bool(row[13]),
            "autoArchiveOnComplete": bool(row[14]),
            "searchVisibilityStatus": row[15] or "hidden",
            "bookStatus": row[16] or "unknown",
            "totalChapters": int(row[17] or 0),
            "processedChapters": int(row[18] or 0),
            "visibleProcessedChapters": int(row[19] or 0),
            "failedChapters": int(row[20] or 0),
            "status": row[21] or "active",
            "settingsJson": row[22] or "",
            "currentPolicyVersion": int(row[23] or 1),
            "lastSourceChapterTitle": row[24] or "",
            "lastLocalChapterTitle": row[25] or "",
            "lastCheckTime": row[26] or "",
            "nextCheckTime": row[27] or "",
            "lastError": row[28] or "",
            "archivedAt": row[29] or "",
            "createdAt": row[30] or "",
            "updatedAt": row[31] or "",
        }

    def _book_lookup_row(self, aggregate_book_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT aggregate_book_id, canonical_name, canonical_author, name, author,
                       cover_url, intro, word_count, primary_book_id, primary_source_id,
                       added_by_user_id, start_chapter_index, initial_snapshot_last_index,
                       backfill_started, auto_archive_on_complete, search_visibility_status,
                       book_status, total_chapters, processed_chapters, visible_processed_chapters,
                       failed_chapters, status, settings_json, current_policy_version,
                       last_source_chapter_title, '', last_check_time, next_check_time, last_error,
                       archived_at, created_at, updated_at
                FROM aggregate_book_tasks
                WHERE aggregate_book_id = ?
                """,
                (aggregate_book_id,),
            ).fetchone()
        data = self._aggregate_book_row_to_dict(row)
        if data:
            data["addedByUsername"] = self.username_for_user_id(data.get("addedByUserId", ""))
        return data

    def find_existing_book(self, group: dict[str, Any], *, visible_only: bool = False) -> dict[str, Any] | None:
        payload = self._payload_from_group(group)
        official_sources = [
            src for src in payload.get("sources", [])
            if self._is_official(src.get("sourceId", ""))
        ]
        with self._conn() as conn:
            for source in official_sources:
                row = conn.execute(
                    """
                    SELECT aggregate_book_id
                    FROM aggregate_book_sources
                    WHERE source_id = ? AND source_book_id = ?
                    ORDER BY id ASC
                    LIMIT 1
                    """,
                    (source.get("sourceId", ""), source.get("bookId", "")),
                ).fetchone()
                if row:
                    book = self._book_lookup_row(row[0])
                    if not book:
                        continue
                    if visible_only and book.get("searchVisibilityStatus") != "visible":
                        continue
                    return book

            canonical_name = self._canonical_name(payload.get("name", ""))
            canonical_author = self._canonical_author(payload.get("author", ""))
            if canonical_name:
                row = conn.execute(
                    """
                    SELECT aggregate_book_id, canonical_name, canonical_author, name, author,
                           cover_url, intro, word_count, primary_book_id, primary_source_id,
                           added_by_user_id, start_chapter_index, initial_snapshot_last_index,
                           backfill_started, auto_archive_on_complete, search_visibility_status,
                           book_status, total_chapters, processed_chapters, visible_processed_chapters,
                           failed_chapters, status, settings_json, current_policy_version,
                           last_source_chapter_title, '', last_check_time, next_check_time, last_error,
                           archived_at, created_at, updated_at
                    FROM aggregate_book_tasks
                    WHERE canonical_name = ? AND canonical_author = ?
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (canonical_name, canonical_author),
                ).fetchone()
                book = self._aggregate_book_row_to_dict(row)
                if book:
                    book["addedByUsername"] = self.username_for_user_id(book.get("addedByUserId", ""))
                if book and visible_only and book.get("searchVisibilityStatus") != "visible":
                    return None
                return book
        return None

    def build_subscription_card(self, group: dict[str, Any]) -> dict[str, Any]:
        payload = self._payload_from_group(group)
        display = self._display_item_for_group(group)
        existing = self.find_existing_book(group, visible_only=False)
        items = [dict(item) for item in group.get("items", []) if isinstance(item, dict)]
        source_summary = [
            {
                "sourceId": item.get("sourceId", ""),
                "sourceName": item.get("sourceName", "") or item.get("sourceId", ""),
                "score": int(item.get("score", 0) or 0),
                "official": self._is_official(item.get("sourceId", "")),
            }
            for item in sorted(items, key=lambda x: -int(x.get("score", 0) or 0))
        ]
        return {
            "cardId": group.get("candidateId", ""),
            "candidateId": group.get("candidateId", ""),
            "name": payload.get("name", "") or display.get("name", ""),
            "author": payload.get("author", "") or display.get("author", ""),
            "coverUrl": display.get("coverUrl", ""),
            "intro": display.get("intro", ""),
            "wordCount": display.get("wordCount", ""),
            "lastChapter": display.get("lastChapter", ""),
            "bookStatus": display.get("status", "") or display.get("bookStatus", ""),
            "sourceCount": len(source_summary),
            "sourceSummary": source_summary,
            "hasOfficialSource": any(x["official"] for x in source_summary),
            "officialSourceIds": [x["sourceId"] for x in source_summary if x["official"]],
            "alreadyInLibrary": bool(existing),
            "aggregateBookId": existing.get("aggregateBookId", "") if existing else "",
            "addedByUserId": existing.get("addedByUserId", "") if existing else "",
            "addedByUsername": existing.get("addedByUsername", "") if existing else "",
            "progress": {
                "processedChapters": existing.get("processedChapters", 0) if existing else 0,
                "visibleProcessedChapters": existing.get("visibleProcessedChapters", 0) if existing else 0,
                "totalChapters": existing.get("totalChapters", 0) if existing else 0,
                "status": existing.get("status", "") if existing else "",
                "searchVisibilityStatus": existing.get("searchVisibilityStatus", "") if existing else "",
            },
            "debug": {
                "payload": payload,
                "displaySourceId": display.get("sourceId", ""),
            },
        }

    def create_or_get_shared_book(
        self,
        group: dict[str, Any],
        *,
        added_by_user_id: str,
        start_chapter_index: int,
        auto_archive_on_complete: bool,
    ) -> dict[str, Any]:
        existing = self.find_existing_book(group)
        if existing:
            return {"created": False, "book": existing}

        payload = self._payload_from_group(group)
        if not payload.get("sources"):
            raise ValueError("candidate group has no valid sources")
        plugins = self._plugins()
        settings = self._merged_book_settings()
        primary_book_id = primary_book_id_from_payload(
            payload,
            plugins=plugins,
            source_priority=settings.get("sourcePriority") or [],
        )
        primary_source_id = primary_book_id.split(":", 1)[0] if ":" in primary_book_id else ""
        if not primary_book_id or not primary_source_id:
            raise ValueError("failed to resolve primary source")

        aggregate_book_id = uuid.uuid4().hex
        canonical_name = self._canonical_name(payload.get("name", ""))
        canonical_author = self._canonical_author(payload.get("author", ""))
        display = self._display_item_for_group(group)
        now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()

        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO aggregate_book_tasks (
                    aggregate_book_id, canonical_name, canonical_author, name, author,
                    cover_url, intro, word_count, aggregate_payload_json, primary_book_id,
                    primary_source_id, added_by_user_id, start_chapter_index,
                    initial_snapshot_last_index, backfill_started, auto_archive_on_complete,
                    search_visibility_status, book_status, total_chapters, processed_chapters,
                    visible_processed_chapters, failed_chapters, total_tokens, status,
                    settings_json, current_policy_version, interval_minutes, last_check_time,
                    next_check_time, error_count, last_error, ai_enabled, last_processed_at,
                    archived_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 'hidden', ?, 0, 0, 0, 0, 0, 'active', ?, 1, ?, NULL, NULL, 0, '', ?, NULL, NULL, ?, ?)
                """,
                (
                    aggregate_book_id,
                    canonical_name,
                    canonical_author,
                    payload.get("name", "") or display.get("name", ""),
                    payload.get("author", "") or display.get("author", ""),
                    display.get("coverUrl", ""),
                    display.get("intro", ""),
                    display.get("wordCount", ""),
                    json.dumps(payload, ensure_ascii=False),
                    primary_book_id,
                    primary_source_id,
                    added_by_user_id,
                    max(1, int(start_chapter_index or 1)),
                    1 if auto_archive_on_complete else 0,
                    display.get("status", "") or "unknown",
                    json.dumps(
                        {
                            **settings,
                            "startChapterIndex": max(1, int(start_chapter_index or 1)),
                            "autoArchiveOnComplete": bool(auto_archive_on_complete),
                        },
                        ensure_ascii=False,
                    ),
                    int(settings.get("updateIntervalMinutes", 60) or 60),
                    1 if settings.get("aiAggregateEnabled", True) else 0,
                    now,
                    now,
                ),
            )
            for source in payload.get("sources", []):
                conn.execute(
                    """
                    INSERT INTO aggregate_book_sources (
                        aggregate_book_id, source_id, source_book_id, source_name, source_book_url,
                        role, score, enabled, last_seen_at, last_chapter_title, chapter_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, 0, ?, ?)
                    """,
                    (
                        aggregate_book_id,
                        source.get("sourceId", ""),
                        source.get("bookId", ""),
                        source.get("sourceName", ""),
                        source.get("bookUrl", ""),
                        "primary" if source.get("sourceId", "") == primary_source_id else "candidate",
                        int(source.get("score", 0) or 0),
                        now,
                        source.get("lastChapter", "") or "",
                        now,
                        now,
                    ),
                )
            conn.execute(
                """
                INSERT INTO aggregate_operation_logs (
                    aggregate_book_id, actor_user_id, actor_role, operation_type, before_json, after_json, created_at
                ) VALUES (?, ?, 'user', 'create', '', ?, ?)
                """,
                (
                    aggregate_book_id,
                    added_by_user_id,
                    json.dumps(
                        {
                            "startChapterIndex": max(1, int(start_chapter_index or 1)),
                            "autoArchiveOnComplete": bool(auto_archive_on_complete),
                            "primarySourceId": primary_source_id,
                        },
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
            conn.commit()

        book = self._book_lookup_row(aggregate_book_id)
        return {"created": True, "book": book, "payload": payload}

    def list_books(self, *, added_by_user_id: str | None = None, keyword: str = "", include_hidden: bool = True) -> list[dict[str, Any]]:
        where = []
        params: list[Any] = []
        if added_by_user_id:
            where.append("added_by_user_id = ?")
            params.append(added_by_user_id)
        if keyword:
            where.append("(name LIKE ? OR author LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        if not include_hidden:
            where.append("search_visibility_status = 'visible'")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT aggregate_book_id, canonical_name, canonical_author, name, author,
                       cover_url, intro, word_count, primary_book_id, primary_source_id,
                       added_by_user_id, start_chapter_index, initial_snapshot_last_index,
                       backfill_started, auto_archive_on_complete, search_visibility_status,
                       book_status, total_chapters, processed_chapters, visible_processed_chapters,
                       failed_chapters, status, settings_json, current_policy_version,
                       last_source_chapter_title, '', last_check_time, next_check_time, last_error,
                       archived_at, created_at, updated_at
                FROM aggregate_book_tasks
                {where_sql}
                ORDER BY updated_at DESC, created_at DESC
                """,
                params,
            ).fetchall()
        items = []
        for row in rows:
            if not row:
                continue
            item = self._aggregate_book_row_to_dict(row)
            if item:
                item["addedByUsername"] = self.username_for_user_id(item.get("addedByUserId", ""))
                items.append(item)
        return items

    def search_visible_books(self, keyword: str) -> list[dict[str, Any]]:
        normalized = self._canonical_name(keyword)
        author_norm = self._canonical_author(keyword)
        if not normalized and not author_norm:
            return []
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT aggregate_book_id, canonical_name, canonical_author, name, author,
                       cover_url, intro, word_count, primary_book_id, primary_source_id,
                       added_by_user_id, start_chapter_index, initial_snapshot_last_index,
                       backfill_started, auto_archive_on_complete, search_visibility_status,
                       book_status, total_chapters, processed_chapters, visible_processed_chapters,
                       failed_chapters, status, settings_json, current_policy_version,
                       last_source_chapter_title, '', last_check_time, next_check_time, last_error,
                       archived_at, created_at, updated_at
                FROM aggregate_book_tasks
                WHERE (search_visibility_status = 'visible' OR status = 'archived')
                  AND (
                    canonical_name LIKE '%' || ? || '%'
                    OR canonical_author LIKE '%' || ? || '%'
                  )
                ORDER BY updated_at DESC, created_at DESC
                """,
                (normalized, author_norm or normalized),
            ).fetchall()
        items = []
        for row in rows:
            item = self._aggregate_book_row_to_dict(row)
            if item and self._is_injectable_book(item):
                item["addedByUsername"] = self.username_for_user_id(item.get("addedByUserId", ""))
                items.append(item)
        return items

    def _is_injectable_book(self, book: dict[str, Any]) -> bool:
        status = str(book.get("status", "") or "").strip().lower()
        visibility = str(book.get("searchVisibilityStatus", "") or "").strip().lower()
        return visibility == "visible" or status == "archived"

    def library_match_score(self, book: dict[str, Any], keyword: str, *, bonus: int = 50) -> int:
        kw = normalize_text(keyword or "")
        name = normalize_text(book.get("name", "") or book.get("canonicalName", ""))
        author = normalize_author_key(book.get("author", "") or book.get("canonicalAuthor", ""))
        score = 0
        title_hit = False
        author_hit = False
        if kw:
            if kw == name:
                score += 200
                title_hit = True
            elif kw in name:
                score += 100
                title_hit = True
            if author:
                if kw == author:
                    score += 80
                    author_hit = True
                elif kw in author:
                    score += 40
                    author_hit = True
        if title_hit and author_hit:
            score += 50
        if book.get("author"):
            score += 10
        if book.get("lastSourceChapterTitle") or book.get("lastLocalChapterTitle"):
            score += 5
        if book.get("intro"):
            score += 3
        if book.get("coverUrl"):
            score += 3
        if book.get("wordCount"):
            score += 2
        score += int(bonus or 0)
        return score

    def get_book(self, aggregate_book_id: str) -> dict[str, Any] | None:
        return self._book_lookup_row(aggregate_book_id)

    def match_books_for_candidate_groups(self, groups: list[dict[str, Any]], *, visible_only: bool = True) -> list[dict[str, Any]]:
        matched: list[dict[str, Any]] = []
        seen: set[str] = set()
        for group in groups:
            row = self.find_existing_book(group, visible_only=visible_only)
            if row and row["aggregateBookId"] not in seen:
                seen.add(row["aggregateBookId"])
                matched.append(row)
        return matched

    def build_search_injected_item(self, book: dict[str, Any], *, base_api: str | None = None, score: int = 0) -> dict[str, Any]:
        base_api = base_api or f"http://{HOST}:{PORT}"
        aggregate_book_id = book["aggregateBookId"]
        raw_book_url = make_library_aggregate_book_url(aggregate_book_id)
        book_id = make_library_book_id(aggregate_book_id)
        return {
            "displayType": "aggregate",
            "resultKind": "aggregate",
            "sourceId": VIRTUAL_SOURCE_ID,
            "sourceName": VIRTUAL_SOURCE_NAME,
            "bookId": book_id,
            "rawBookUrl": raw_book_url,
            "bookUrl": f"{base_api}/api/legado/book/{book_id}",
            "name": book.get("name", ""),
            "author": book.get("author", ""),
            "coverUrl": book.get("coverUrl", ""),
            "intro": book.get("intro", ""),
            "lastChapter": book.get("lastSourceChapterTitle", "") or book.get("lastLocalChapterTitle", ""),
            "wordCount": book.get("wordCount", ""),
            "addedByUserId": book.get("addedByUserId", ""),
            "addedByUsername": book.get("addedByUsername", ""),
            "aggregateBookId": aggregate_book_id,
            "searchVisibilityStatus": book.get("searchVisibilityStatus", ""),
            "libraryStatus": book.get("status", ""),
            "processedChapters": book.get("processedChapters", 0),
            "visibleProcessedChapters": book.get("visibleProcessedChapters", 0),
            "totalChapters": book.get("totalChapters", 0),
            "score": int(score or 0),
        }

    def build_search_injected_items_for_groups(
        self,
        groups: list[dict[str, Any]],
        *,
        base_api: str | None = None,
        score_bonus: int = 50,
    ) -> list[dict[str, Any]]:
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for group in groups:
            book = self.find_existing_book(group, visible_only=False)
            if not book or not self._is_injectable_book(book):
                continue
            aggregate_book_id = book["aggregateBookId"]
            if aggregate_book_id in seen:
                continue
            seen.add(aggregate_book_id)
            base_score = int(group.get("score", 0) or 0)
            injected = self.build_search_injected_item(
                book,
                base_api=base_api,
                score=base_score + int(score_bonus or 0),
            )
            injected["candidateId"] = group.get("candidateId", "")
            items.append(injected)
        return items

    def build_search_injected_items_for_keyword(
        self,
        keyword: str,
        *,
        base_api: str | None = None,
        score_bonus: int = 50,
    ) -> list[dict[str, Any]]:
        books = self.search_visible_books(keyword)
        items = []
        for book in books:
            score = self.library_match_score(book, keyword, bonus=score_bonus)
            items.append(self.build_search_injected_item(book, base_api=base_api, score=score))
        return items

    def load_payload(self, aggregate_book_id: str) -> dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT aggregate_payload_json FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
                (aggregate_book_id,),
            ).fetchone()
        if not row:
            return {}
        try:
            return json.loads(row[0] or "{}")
        except Exception:
            return {}

    def username_for_user_id(self, user_id: str) -> str:
        if not user_id:
            return ""
        with self._conn() as conn:
            row = conn.execute("SELECT username FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return row[0] if row and row[0] else ""


library_books_service = LibraryBooksService()
