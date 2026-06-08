"""Persistence for real-source live acceptance checks."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.config import DB_PATH


class LiveCheckRepository:
    """Store and retrieve live source validation runs."""

    def record(self, result: dict[str, Any]) -> dict[str, Any]:
        plugin_id = result.get("pluginId", "")
        keyword = result.get("keyword", "")
        status = result.get("status", "failed")
        search = result.get("search", {}) or {}
        selected = result.get("selectedCandidate", {}) or {}
        toc = result.get("toc", {}) or {}
        chapter = result.get("chapter", {}) or {}
        diagnostics = result.get("diagnostics", []) or []

        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.execute(
                """
                INSERT INTO plugin_live_checks (
                    plugin_id,
                    keyword,
                    status,
                    search_count,
                    selected_name,
                    selected_author,
                    toc_count,
                    chapter_title,
                    content_length,
                    result_json,
                    error_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plugin_id,
                    keyword,
                    status,
                    int(search.get("count", 0) or 0),
                    selected.get("name", ""),
                    selected.get("author", ""),
                    int(toc.get("chapterCount", toc.get("count", 0)) or 0),
                    chapter.get("title", ""),
                    int(chapter.get("contentLength", 0) or 0),
                    json.dumps(result, ensure_ascii=False),
                    json.dumps(diagnostics, ensure_ascii=False),
                ),
            )
            conn.commit()
            result = dict(result)
            result["id"] = cursor.lastrowid
            return result

    def list_by_plugin(self, plugin_id: str, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                """
                SELECT id, plugin_id, keyword, status, search_count, selected_name,
                       selected_author, toc_count, chapter_title, content_length,
                       result_json, error_json, created_at
                FROM plugin_live_checks
                WHERE plugin_id = ?
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (plugin_id, limit, offset),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def latest_by_plugin(self, plugin_id: str) -> dict[str, Any] | None:
        items = self.list_by_plugin(plugin_id, limit=1)
        return items[0] if items else None

    def list_all(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                """
                SELECT id, plugin_id, keyword, status, search_count, selected_name,
                       selected_author, toc_count, chapter_title, content_length,
                       result_json, error_json, created_at
                FROM plugin_live_checks
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def stats(self) -> dict[str, int]:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM plugin_live_checks GROUP BY status"
            ).fetchall()
        stats = {row[0]: row[1] for row in rows}
        stats["total"] = sum(stats.values())
        return stats

    def _row_to_dict(self, row) -> dict[str, Any]:
        result = {}
        errors = []
        try:
            result = json.loads(row[10] or "{}")
        except json.JSONDecodeError:
            result = {}
        try:
            errors = json.loads(row[11] or "[]")
        except json.JSONDecodeError:
            errors = []
        return {
            "id": row[0],
            "pluginId": row[1],
            "keyword": row[2],
            "status": row[3],
            "searchCount": row[4],
            "selectedName": row[5],
            "selectedAuthor": row[6],
            "tocCount": row[7],
            "chapterTitle": row[8],
            "contentLength": row[9],
            "result": result,
            "errors": errors,
            "createdAt": row[12],
        }
