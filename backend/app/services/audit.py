"""Persistent, privacy-bounded audit events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from app.storage.db import initialize_database


SAFE_SUMMARY_FIELDS = {
    "role",
    "disabled",
    "status",
    "previousStatus",
    "startChapterIndex",
    "autoArchiveOnComplete",
    "subscriptionCreated",
    "sharedBookCreated",
    "updateIntervalMinutes",
    "backlogChapterLimit",
    "currentPolicyVersion",
    "policyChanged",
    "method",
    "authenticated",
    "errorCode",
    "affectedCount",
    "deleted",
}


class AuditService:
    def __init__(self, db_path=None):
        self.db_path = db_path

    def _db_path(self):
        if self.db_path is not None:
            return self.db_path
        from app import config

        return config.DB_PATH

    @staticmethod
    def _safe_summary(summary: dict[str, Any] | None) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, value in (summary or {}).items():
            if key not in SAFE_SUMMARY_FIELDS or value is None:
                continue
            if isinstance(value, (bool, int, float)):
                safe[key] = value
            elif isinstance(value, str):
                safe[key] = value[:120]
        return safe

    def record(
        self,
        *,
        action: str,
        actor_user_id: str = "",
        actor_role: str = "",
        target_type: str = "",
        target_id: str = "",
        source_id: str = "",
        outcome: str = "success",
        summary: dict[str, Any] | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> str:
        event_id = uuid.uuid4().hex
        values = (
            event_id,
            datetime.now(timezone.utc).isoformat(),
            str(actor_user_id or "")[:200],
            str(actor_role or "")[:40],
            str(action or "")[:120],
            str(target_type or "")[:80],
            str(target_id or "")[:200],
            str(source_id or "")[:200],
            str(outcome or "success")[:40],
            json.dumps(self._safe_summary(summary), ensure_ascii=False),
        )
        sql = """
            INSERT INTO audit_events (
                event_id, occurred_at, actor_user_id, actor_role, action,
                target_type, target_id, source_id, outcome, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if conn is not None:
            conn.execute(sql, values)
            return event_id
        db_path = self._db_path()
        initialize_database(db_path)
        with sqlite3.connect(db_path) as audit_conn:
            audit_conn.execute(sql, values)
            audit_conn.commit()
        return event_id

    def list_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        db_path = self._db_path()
        initialize_database(db_path)
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT event_id, occurred_at, actor_user_id, actor_role, action,
                       target_type, target_id, source_id, outcome, summary_json
                FROM audit_events
                ORDER BY occurred_at DESC, event_id DESC
                LIMIT ?
                """,
                (min(1000, max(1, int(limit or 100))),),
            ).fetchall()
        return [
            {
                "eventId": row[0],
                "occurredAt": row[1],
                "actorUserId": row[2],
                "actorRole": row[3],
                "action": row[4],
                "targetType": row[5],
                "targetId": row[6],
                "sourceId": row[7],
                "outcome": row[8],
                "summary": json.loads(row[9] or "{}"),
            }
            for row in rows
        ]


audit_service = AuditService()
