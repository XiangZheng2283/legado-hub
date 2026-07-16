"""User-owned subscription relationships for shared aggregate books."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import DB_PATH
from app.core.app_config import AppConfig
from app.storage.db import initialize_database


SUBSCRIPTION_STATUSES = {"active", "paused", "archived"}


class SubscriptionLimitError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class UserSubscriptionsService:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        initialize_database(self.db_path)
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _row_to_dict(row: tuple[Any, ...] | None) -> dict[str, Any] | None:
        if not row:
            return None
        return {
            "userId": row[0],
            "aggregateBookId": row[1],
            "status": row[2],
            "startChapterIndex": int(row[3] or 1),
            "autoArchiveOnComplete": bool(row[4]),
            "createdAt": row[5] or "",
            "updatedAt": row[6] or "",
        }

    def get(self, user_id: str, aggregate_book_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT user_id, aggregate_book_id, status, start_chapter_index,
                       auto_archive_on_complete, created_at, updated_at
                FROM user_book_subscriptions
                WHERE user_id = ? AND aggregate_book_id = ?
                """,
                (user_id, aggregate_book_id),
            ).fetchone()
        return self._row_to_dict(row)

    def require(self, user_id: str, aggregate_book_id: str) -> dict[str, Any]:
        subscription = self.get(user_id, aggregate_book_id)
        if not subscription:
            raise KeyError(aggregate_book_id)
        return subscription

    def check_capacity(self, user_id: str, *, creates_shared_book: bool) -> None:
        limits = AppConfig.get().subscription
        with self._conn() as conn:
            active_count = conn.execute(
                """
                SELECT COUNT(*) FROM user_book_subscriptions
                WHERE user_id = ? AND status IN ('active', 'paused')
                """,
                (user_id,),
            ).fetchone()[0]
            if int(active_count or 0) >= limits.max_active_per_user:
                raise SubscriptionLimitError("subscription_limit_reached", "已达到当前订阅上限")

            if not creates_shared_book:
                return
            cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            created_count = conn.execute(
                """
                SELECT COUNT(*) FROM aggregate_operation_logs
                WHERE actor_user_id = ? AND operation_type = 'create'
                  AND created_at >= ?
                """,
                (user_id, cutoff),
            ).fetchone()[0]
            if int(created_count or 0) >= limits.max_new_shared_books_per_day:
                raise SubscriptionLimitError("shared_book_daily_limit_reached", "今日新建共享书数量已达上限")

            provisioning_count = conn.execute(
                """
                SELECT COUNT(*) FROM aggregate_book_tasks
                WHERE status IN ('active', 'error')
                  AND search_visibility_status = 'hidden'
                  AND processed_chapters = 0
                """
            ).fetchone()[0]
            if int(provisioning_count or 0) >= limits.max_global_provisioning_books:
                raise SubscriptionLimitError("provisioning_capacity_reached", "当前共享处理队列已满")

    def ensure(
        self,
        user_id: str,
        aggregate_book_id: str,
        *,
        start_chapter_index: int = 1,
        auto_archive_on_complete: bool = True,
    ) -> tuple[dict[str, Any], bool]:
        start_index = max(1, int(start_chapter_index or 1))
        before = self.get(user_id, aggregate_book_id)
        if not before or before["status"] == "archived":
            self.check_capacity(user_id, creates_shared_book=False)
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            if not conn.execute(
                "SELECT 1 FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
                (aggregate_book_id,),
            ).fetchone():
                raise KeyError(aggregate_book_id)
            conn.execute(
                """
                INSERT INTO user_book_subscriptions (
                    user_id, aggregate_book_id, status, start_chapter_index,
                    auto_archive_on_complete, created_at, updated_at
                ) VALUES (?, ?, 'active', ?, ?, ?, ?)
                ON CONFLICT(user_id, aggregate_book_id) DO UPDATE SET
                    status = 'active',
                    start_chapter_index = excluded.start_chapter_index,
                    auto_archive_on_complete = excluded.auto_archive_on_complete,
                    updated_at = excluded.updated_at
                """,
                (user_id, aggregate_book_id, start_index, int(auto_archive_on_complete), now, now),
            )
            after = conn.execute(
                """
                SELECT user_id, aggregate_book_id, status, start_chapter_index,
                       auto_archive_on_complete, created_at, updated_at
                FROM user_book_subscriptions
                WHERE user_id = ? AND aggregate_book_id = ?
                """,
                (user_id, aggregate_book_id),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO aggregate_operation_logs (
                    aggregate_book_id, actor_user_id, actor_role, operation_type,
                    before_json, after_json, created_at
                ) VALUES (?, ?, 'user', ?, ?, ?, ?)
                """,
                (
                    aggregate_book_id,
                    user_id,
                    "subscription.create" if before is None else "subscription.update",
                    json.dumps(before or {}, ensure_ascii=False),
                    json.dumps(self._row_to_dict(after), ensure_ascii=False),
                    now,
                ),
            )
            conn.commit()
        return self._row_to_dict(after) or {}, before is None

    def update(self, user_id: str, aggregate_book_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        before = self.require(user_id, aggregate_book_id)
        allowed = {"status", "startChapterIndex", "autoArchiveOnComplete"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported fields: {', '.join(sorted(unknown))}")

        status = str(changes.get("status", before["status"]) or "").strip().lower()
        if status not in SUBSCRIPTION_STATUSES:
            raise ValueError("invalid subscription status")
        start_index = max(1, int(changes.get("startChapterIndex", before["startChapterIndex"]) or 1))
        auto_archive = bool(changes.get("autoArchiveOnComplete", before["autoArchiveOnComplete"]))
        if before["status"] == "archived" and status in {"active", "paused"}:
            self.check_capacity(user_id, creates_shared_book=False)

        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE user_book_subscriptions
                SET status = ?, start_chapter_index = ?, auto_archive_on_complete = ?, updated_at = ?
                WHERE user_id = ? AND aggregate_book_id = ?
                """,
                (status, start_index, int(auto_archive), now, user_id, aggregate_book_id),
            )
            after = conn.execute(
                """
                SELECT user_id, aggregate_book_id, status, start_chapter_index,
                       auto_archive_on_complete, created_at, updated_at
                FROM user_book_subscriptions
                WHERE user_id = ? AND aggregate_book_id = ?
                """,
                (user_id, aggregate_book_id),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO aggregate_operation_logs (
                    aggregate_book_id, actor_user_id, actor_role, operation_type,
                    before_json, after_json, created_at
                ) VALUES (?, ?, 'user', 'subscription.update', ?, ?, ?)
                """,
                (
                    aggregate_book_id,
                    user_id,
                    json.dumps(before, ensure_ascii=False),
                    json.dumps(self._row_to_dict(after), ensure_ascii=False),
                    now,
                ),
            )
            conn.commit()
        return self._row_to_dict(after) or {}

    def list_books(self, user_id: str, library_service: Any, *, keyword: str = "") -> list[dict[str, Any]]:
        params: list[Any] = [user_id]
        keyword_clause = ""
        if keyword:
            keyword_clause = "AND (books.name LIKE ? OR books.author LIKE ?)"
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT subscriptions.aggregate_book_id
                FROM user_book_subscriptions AS subscriptions
                JOIN aggregate_book_tasks AS books
                  ON books.aggregate_book_id = subscriptions.aggregate_book_id
                WHERE subscriptions.user_id = ? {keyword_clause}
                ORDER BY subscriptions.updated_at DESC
                """,
                params,
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            book = library_service.get_book(row[0])
            subscription = self.get(user_id, row[0])
            if not book or not subscription:
                continue
            library_service._attach_book_state_summary(book)
            book["subscription"] = subscription
            book["personalProgress"] = self.progress(subscription, library_service)
            items.append(book)
        return items

    def progress(self, subscription: dict[str, Any], library_service: Any) -> dict[str, Any]:
        book_id = subscription["aggregateBookId"]
        start = max(1, int(subscription.get("startChapterIndex", 1) or 1))
        page = 1
        chapters: list[dict[str, Any]] = []
        while True:
            result = library_service.list_shared_chapters(book_id, page=page, pageSize=200)
            batch = result.get("items") or []
            chapters.extend(item for item in batch if int(item.get("chapterIndex", 0) or 0) >= start)
            if page * 200 >= int(result.get("total", 0) or 0):
                break
            page += 1

        full = preview = failed = pending = 0
        continuous = start - 1
        blocked = False
        for chapter in sorted(chapters, key=lambda item: int(item.get("chapterIndex", 0) or 0)):
            has_content = bool(chapter.get("hasContent"))
            is_preview = bool(chapter.get("previewOnly"))
            status = str(chapter.get("status", "") or "").lower()
            if has_content and is_preview:
                preview += 1
            elif has_content:
                full += 1
            elif status in {"error", "failed", "rejected"}:
                failed += 1
            else:
                pending += 1
            if not blocked and has_content:
                continuous = int(chapter.get("chapterIndex", continuous) or continuous)
            else:
                blocked = True

        book = library_service.get_book(book_id) or {}
        range_end = max(
            [int(item.get("chapterIndex", 0) or 0) for item in chapters]
            + [int(book.get("totalChapters", 0) or 0), start - 1]
        )
        total = max(0, range_end - start + 1)
        known = full + preview + failed + pending
        pending += max(0, total - known)
        available = full + preview
        return {
            "rangeStartIndex": start,
            "rangeEndIndex": range_end,
            "fullCount": full,
            "previewCount": preview,
            "failedCount": failed,
            "pendingCount": pending,
            "continuousReadableThroughIndex": continuous,
            "coverageRatio": round(available / total, 4) if total else 0.0,
        }

    def archive_completed_for_book(self, aggregate_book_id: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT user_id, aggregate_book_id, status, start_chapter_index,
                       auto_archive_on_complete, created_at, updated_at
                FROM user_book_subscriptions
                WHERE aggregate_book_id = ? AND status = 'active'
                  AND auto_archive_on_complete = 1
                """,
                (aggregate_book_id,),
            ).fetchall()
            conn.execute(
                """
                UPDATE user_book_subscriptions
                SET status = 'archived', updated_at = ?
                WHERE aggregate_book_id = ? AND status = 'active'
                  AND auto_archive_on_complete = 1
                """,
                (now, aggregate_book_id),
            )
            for row in rows:
                before = self._row_to_dict(row) or {}
                after = {**before, "status": "archived", "updatedAt": now}
                conn.execute(
                    """
                    INSERT INTO aggregate_operation_logs (
                        aggregate_book_id, actor_user_id, actor_role, operation_type,
                        before_json, after_json, created_at
                    ) VALUES (?, '', 'system', 'subscription.auto_archive', ?, ?, ?)
                    """,
                    (
                        aggregate_book_id,
                        json.dumps(before, ensure_ascii=False),
                        json.dumps(after, ensure_ascii=False),
                        now,
                    ),
                )
            conn.commit()
            return len(rows)


user_subscriptions_service = UserSubscriptionsService()
