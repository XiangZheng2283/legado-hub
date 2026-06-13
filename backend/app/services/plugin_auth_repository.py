"""Persistent auth and cookie state for source plugins."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class PluginAuthRepository:
    """Store plugin auth status and cookie jars."""

    def __init__(self, db_path: Path | None = None):
        from app import config as app_config
        from app.storage.db import initialize_database

        self.db_path = db_path or app_config.DB_PATH
        initialize_database(self.db_path)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def ensure_plugin(self, plugin_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO plugin_auth_state (plugin_id, updated_at)
                VALUES (?, datetime('now'))
                ON CONFLICT(plugin_id) DO NOTHING
                """,
                (plugin_id,),
            )
            conn.commit()

    def set_cookies(self, plugin_id: str, cookies: dict) -> None:
        self.ensure_plugin(plugin_id)
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE plugin_auth_state
                SET cookie_json = ?, updated_at = datetime('now')
                WHERE plugin_id = ?
                """,
                (json.dumps(cookies, ensure_ascii=False), plugin_id),
            )
            conn.commit()

    def get_cookies(self, plugin_id: str) -> dict:
        self.ensure_plugin(plugin_id)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT cookie_json FROM plugin_auth_state WHERE plugin_id = ?",
                (plugin_id,),
            ).fetchone()
        if not row or not row[0]:
            return {}
        try:
            data = json.loads(row[0])
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def clear_cookie_cache(self, plugin_id: str) -> None:
        """Clear only persisted cookie_json while leaving status fields intact."""
        self.ensure_plugin(plugin_id)
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE plugin_auth_state
                SET cookie_json = NULL, updated_at = datetime('now')
                WHERE plugin_id = ?
                """,
                (plugin_id,),
            )
            conn.commit()

    def clear_cookies(self, plugin_id: str) -> None:
        self.ensure_plugin(plugin_id)
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE plugin_auth_state
                SET cookie_json = NULL,
                    auth_status = 'unknown',
                    account_name = '',
                    expires_at = '',
                    last_error = '',
                    updated_at = datetime('now')
                WHERE plugin_id = ?
                """,
                (plugin_id,),
            )
            conn.commit()

    def update_status(self, plugin_id: str, status: dict) -> None:
        self.ensure_plugin(plugin_id)
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE plugin_auth_state
                SET auth_status = ?,
                    account_name = ?,
                    expires_at = ?,
                    last_checked_at = datetime('now'),
                    last_error = ?,
                    updated_at = datetime('now')
                WHERE plugin_id = ?
                """,
                (
                    "authenticated" if status.get("authenticated") else status.get("authStatus", "anonymous"),
                    status.get("accountName", ""),
                    status.get("expiresAt", ""),
                    status.get("lastError", "") or status.get("message", ""),
                    plugin_id,
                ),
            )
            conn.commit()

    def get_status(self, plugin_id: str) -> dict:
        from app.services import plugin_cookie_file_store

        self.ensure_plugin(plugin_id)
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT auth_status, account_name, expires_at, last_checked_at, last_error, cookie_json
                FROM plugin_auth_state
                WHERE plugin_id = ?
                """,
                (plugin_id,),
            ).fetchone()
        if plugin_id == "qidian_com":
            cookies = plugin_cookie_file_store.load(plugin_id)
        else:
            cookies = self.get_cookies(plugin_id)
        auth_status = row[0] if row else "unknown"
        return {
            "sourceId": plugin_id,
            "authStatus": auth_status or "unknown",
            "authenticated": auth_status == "authenticated",
            "accountName": (row[1] if row else "") or "",
            "expiresAt": (row[2] if row else "") or "",
            "lastCheckedAt": (row[3] if row else "") or "",
            "lastError": (row[4] if row else "") or "",
            "hasCookies": bool(cookies),
            "cookieDomains": sorted(cookies.keys()),
        }


