"""Runtime health repository for source plugins."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class PluginHealthRepository:
    """Store source-plugin health, attempts, and test results."""

    def __init__(self, db_path: Path | None = None):
        from app import config as app_config
        from app.storage.db import initialize_database

        self.db_path = db_path or app_config.DB_PATH
        initialize_database(self.db_path)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def ensure_plugin(
        self,
        plugin_id: str,
        name: str = "",
        enabled: bool = True,
        health_status: str = "unknown",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO plugin_health (
                    plugin_id, plugin_name, enabled, health_status, updated_at
                ) VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(plugin_id) DO UPDATE SET
                    plugin_name = COALESCE(NULLIF(excluded.plugin_name, ''), plugin_health.plugin_name),
                    enabled = excluded.enabled,
                    updated_at = datetime('now')
                """,
                (plugin_id, name, 1 if enabled else 0, health_status),
            )
            conn.commit()

    def get_plugin(self, plugin_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT plugin_id, plugin_name, enabled, health_status, failure_reason,
                       proxy_mode, proxy_status, last_error, last_test_result_json,
                       success_count, failure_count
                FROM plugin_health
                WHERE plugin_id = ?
                """,
                (plugin_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_plugin(row)

    def get_plugins(
        self,
        enabled_only: bool = False,
        health_status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        query = """
            SELECT plugin_id, plugin_name, enabled, health_status, failure_reason,
                   proxy_mode, proxy_status, last_error, last_test_result_json,
                   success_count, failure_count
            FROM plugin_health
            WHERE 1=1
        """
        params: list = []
        if enabled_only:
            query += " AND enabled = 1"
        if health_status:
            query += " AND health_status = ?"
            params.append(health_status)
        query += " ORDER BY plugin_name, plugin_id LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_plugin(row) for row in rows]

    def _row_to_plugin(self, row) -> dict:
        return {
            "pluginId": row[0],
            "sourceId": row[0],
            "pluginName": row[1] or row[0],
            "bookSourceName": row[1] or row[0],
            "enabled": bool(row[2]),
            "healthStatus": row[3] or "unknown",
            "failureReason": row[4] or "",
            "proxyMode": row[5] or "auto",
            "proxyStatus": row[6] or "unknown",
            "lastError": row[7] or "",
            "lastTestResult": json.loads(row[8]) if row[8] else None,
            "successCount": row[9] or 0,
            "failureCount": row[10] or 0,
        }

    def set_enabled(self, plugin_id: str, enabled: bool) -> None:
        self.ensure_plugin(plugin_id, enabled=enabled)
        with self._conn() as conn:
            conn.execute(
                "UPDATE plugin_health SET enabled = ?, updated_at = datetime('now') WHERE plugin_id = ?",
                (1 if enabled else 0, plugin_id),
            )
            conn.commit()

    def set_proxy_mode(self, plugin_id: str, proxy_mode: str) -> None:
        self.ensure_plugin(plugin_id)
        with self._conn() as conn:
            conn.execute(
                "UPDATE plugin_health SET proxy_mode = ?, updated_at = datetime('now') WHERE plugin_id = ?",
                (proxy_mode, plugin_id),
            )
            conn.commit()

    def record_attempt(
        self,
        source_id: str,
        stage: str,
        url: str,
        direct_status: str,
        proxy_status: str,
        proxy_used: bool,
        latency_ms: int,
        error: str = "",
    ) -> None:
        self.ensure_plugin(source_id)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO plugin_attempts
                (plugin_id, stage, url, direct_status, proxy_status, proxy_used, latency_ms, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source_id, stage, url, direct_status, proxy_status, 1 if proxy_used else 0, latency_ms, error),
            )
            conn.commit()

    def record_failure(
        self,
        source_id: str,
        stage: str,
        error: str,
        is_hard_failure: bool = False,
    ) -> None:
        self.ensure_plugin(source_id)
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE plugin_health
                SET failure_count = failure_count + 1,
                    last_error = ?,
                    updated_at = datetime('now')
                WHERE plugin_id = ?
                """,
                (error, source_id),
            )
            if is_hard_failure:
                conn.execute(
                    """
                    UPDATE plugin_health
                    SET enabled = 0,
                        health_status = 'disabled',
                        failure_reason = ?,
                        updated_at = datetime('now')
                    WHERE plugin_id = ?
                    """,
                    (f"[{stage}] {error}", source_id),
                )
            conn.commit()

    def record_success(self, source_id: str, latency_ms: int) -> None:
        self.ensure_plugin(source_id)
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE plugin_health
                SET success_count = success_count + 1,
                    last_success_at = datetime('now'),
                    health_status = CASE WHEN health_status IN ('unknown', 'disabled') THEN 'healthy' ELSE health_status END,
                    updated_at = datetime('now')
                WHERE plugin_id = ?
                """,
                (source_id,),
            )
            conn.commit()

    def get_attempts(self, source_id: str, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT stage, url, direct_status, proxy_status, proxy_used, latency_ms, error, created_at
                FROM plugin_attempts
                WHERE plugin_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (source_id, limit),
            ).fetchall()
        return [
            {
                "stage": row[0],
                "url": row[1],
                "directStatus": row[2],
                "proxyStatus": row[3],
                "proxyUsed": bool(row[4]),
                "latencyMs": row[5],
                "error": row[6] or "",
                "createdAt": row[7],
            }
            for row in rows
        ]

    def get_stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM plugin_health").fetchone()[0]
            enabled = conn.execute("SELECT COUNT(*) FROM plugin_health WHERE enabled = 1").fetchone()[0]
            healthy = conn.execute(
                "SELECT COUNT(*) FROM plugin_health WHERE enabled = 1 AND health_status = 'healthy'"
            ).fetchone()[0]
            proxy_needed = conn.execute(
                "SELECT COUNT(*) FROM plugin_health WHERE proxy_status IN ('proxy_succeeded', 'proxy_needed', 'forced_proxy')"
            ).fetchone()[0]
            disabled = conn.execute("SELECT COUNT(*) FROM plugin_health WHERE enabled = 0").fetchone()[0]
            unsupported = conn.execute("SELECT COUNT(*) FROM plugin_health WHERE health_status = 'unsupported'").fetchone()[0]
        return {
            "total": total,
            "enabled": enabled,
            "healthy": healthy,
            "proxyNeeded": proxy_needed,
            "disabled": disabled,
            "unsupported": unsupported,
        }

    def update_test_result(self, source_id: str, result: dict) -> None:
        self.ensure_plugin(source_id)
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE plugin_health
                SET last_test_result_json = ?,
                    updated_at = datetime('now')
                WHERE plugin_id = ?
                """,
                (json.dumps(result, ensure_ascii=False), source_id),
            )
            conn.commit()
