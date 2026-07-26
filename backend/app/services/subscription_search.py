"""Dedicated shared-subscription search pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from app.config import DB_PATH
from app.core.app_config import AppConfig
from app.services.library_books import library_books_service
from app.services.live_acceptance import group_candidates
from app.services.user_subscriptions import user_subscriptions_service
from app.source_plugins.scheduler import get_plugin_scheduler
from app.storage.db import initialize_database


FINAL_STATUSES = {
    "completed", "partial", "timed_out", "failed", "cancelled", "interrupted"
}
ALL_STATUSES = FINAL_STATUSES | {"pending", "running"}
logger = logging.getLogger(__name__)


@dataclass
class SubscriptionSearchJob:
    job_id: str
    owner_user_id: str
    keyword: str
    page: int
    status: str = "pending"
    mode: str = "official-primary"
    official_status: str = "pending"
    message: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    official_source_count: int = 0
    official_completed_count: int = 0
    success_count: int = 0
    error_count: int = 0
    timeout_count: int = 0
    official_items: list[dict[str, Any]] = field(default_factory=list)
    official_groups: list[dict[str, Any]] = field(default_factory=list)
    card_groups: list[dict[str, Any]] = field(default_factory=list)
    cards: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)


class SubscriptionSearchService:
    """Runs official-first subscription discovery independent of console search."""

    def __init__(
        self,
        scheduler: Any | None = None,
        library_service: Any | None = None,
        subscription_service: Any | None = None,
        db_path=DB_PATH,
    ):
        self.scheduler = scheduler or get_plugin_scheduler()
        self.library_service = library_service or library_books_service
        self.subscription_service = subscription_service or user_subscriptions_service
        self.db_path = db_path
        self._jobs: dict[str, SubscriptionSearchJob] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        initialize_database(self.db_path)
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    def _persist_job(self, job: SubscriptionSearchJob) -> bool:
        # ponytail: one bounded snapshot row; split events/cards only when row size
        # or cross-job querying becomes a measured problem.
        job.events = job.events[-50:]
        payload = {
            "mode": job.mode,
            "official_status": job.official_status,
            "message": job.message,
            "official_source_count": job.official_source_count,
            "official_completed_count": job.official_completed_count,
            "success_count": job.success_count,
            "error_count": job.error_count,
            "timeout_count": job.timeout_count,
            "card_groups": job.card_groups,
            "cards": job.cards,
            "events": job.events,
        }
        with self._conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO subscription_search_jobs (
                    job_id, owner_user_id, keyword, page, status, payload_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    status = excluded.status,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                WHERE subscription_search_jobs.owner_user_id = excluded.owner_user_id
                  AND subscription_search_jobs.keyword = excluded.keyword
                  AND subscription_search_jobs.page = excluded.page
                  AND (
                      typeof(subscription_search_jobs.updated_at) NOT IN ('integer', 'real')
                      OR excluded.updated_at >= subscription_search_jobs.updated_at
                  )
                """,
                (
                    job.job_id,
                    job.owner_user_id,
                    job.keyword,
                    job.page,
                    job.status,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    job.created_at,
                    job.updated_at,
                ),
            )
            conn.commit()
        return cursor.rowcount == 1

    def _persist_job_best_effort(
        self,
        job: SubscriptionSearchJob,
        *,
        context: str,
    ) -> bool:
        try:
            persisted = self._persist_job(job)
        except Exception:
            persisted = False
            logger.warning(
                "Failed to persist subscription search job %s during %s",
                job.job_id,
                context,
                exc_info=True,
            )
        if persisted:
            return True
        job.events.append(
            {
                "type": "persistence_error",
                "message": "搜索进度暂未保存，服务重启后可能需要重新搜索。",
                "stage": context,
                "ts": time.time(),
            }
        )
        job.events = job.events[-50:]
        return False

    def _load_job(self, job_id: str) -> SubscriptionSearchJob | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT job_id, owner_user_id, keyword, page, status,
                       payload_json, created_at, updated_at
                FROM subscription_search_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row[5] or "{}")
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None

        def payload_list(key: str) -> list[dict[str, Any]]:
            value = payload.get(key)
            return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []

        status = str(row[4] or "")
        if status not in ALL_STATUSES:
            return None
        now = time.time()
        job = SubscriptionSearchJob(
            job_id=str(row[0]),
            owner_user_id=str(row[1]),
            keyword=str(row[2]),
            page=self._positive_int(row[3], 1),
            status=status,
            mode=str(payload.get("mode", "official-primary") or "official-primary"),
            official_status=str(payload.get("official_status", "pending") or "pending"),
            message=str(payload.get("message", "") or ""),
            created_at=self._timestamp(row[6], now),
            updated_at=self._timestamp(row[7], now),
            official_source_count=self._nonnegative_int(
                payload.get("official_source_count"), 0
            ),
            official_completed_count=self._nonnegative_int(
                payload.get("official_completed_count"), 0
            ),
            success_count=self._nonnegative_int(payload.get("success_count"), 0),
            error_count=self._nonnegative_int(payload.get("error_count"), 0),
            timeout_count=self._nonnegative_int(payload.get("timeout_count"), 0),
            card_groups=payload_list("card_groups"),
            cards=payload_list("cards"),
            events=payload_list("events"),
        )
        self._jobs[job.job_id] = job
        return job

    def recover_interrupted_jobs(self) -> int:
        with self._conn() as conn:
            job_ids = [
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT job_id FROM subscription_search_jobs
                    WHERE status IN ('pending', 'running')
                    """
                ).fetchall()
            ]
        recovered = 0
        for job_id in job_ids:
            self._jobs.pop(job_id, None)
            job = self._load_job(job_id)
            if not job:
                with self._conn() as conn:
                    cursor = conn.execute(
                        """
                        DELETE FROM subscription_search_jobs
                        WHERE job_id = ? AND status IN ('pending', 'running')
                        """,
                        (job_id,),
                    )
                    conn.commit()
                if cursor.rowcount:
                    logger.warning(
                        "Removed unreadable subscription search snapshot %s",
                        job_id,
                    )
                continue
            job.status = "interrupted"
            if job.official_status in {"pending", "running"}:
                job.official_status = "interrupted"
            job.message = "服务重启，搜索任务已中断，请重新搜索。"
            job.events.append(
                {"type": "job_interrupted", "message": job.message, "ts": time.time()}
            )
            job.updated_at = time.time()
            if self._persist_job_best_effort(job, context="startup-recovery"):
                recovered += 1
        return recovered

    def create_job(self, keyword: str, page: int = 1, *, owner_user_id: str) -> SubscriptionSearchJob:
        official_plugins, _ = self._split_plugins()
        job = SubscriptionSearchJob(
            job_id=uuid.uuid4().hex,
            owner_user_id=owner_user_id,
            keyword=keyword,
            page=max(1, int(page or 1)),
        )
        self._jobs[job.job_id] = job
        job.official_source_count = len(official_plugins)
        if not official_plugins:
            job.status = "completed"
            job.official_status = "completed"
            job.mode = "no-official-source"
            job.message = "未检测到可用官方源，订阅搜索不会生成入库卡片。"
            job.updated_at = time.time()
            try:
                if not self._persist_job(job):
                    raise RuntimeError("订阅搜索任务初始快照发生冲突")
            except Exception:
                self._jobs.pop(job.job_id, None)
                raise
            return job
        job.status = "running"
        job.official_status = "running"
        job.updated_at = time.time()
        try:
            if not self._persist_job(job):
                raise RuntimeError("订阅搜索任务初始快照发生冲突")
        except Exception:
            self._jobs.pop(job.job_id, None)
            raise
        task = asyncio.create_task(self._run_job(job, official_plugins))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    def get_job(self, job_id: str) -> SubscriptionSearchJob | None:
        return self._jobs.get(job_id) or self._load_job(job_id)

    def get_job_for_user(self, job_id: str, user_id: str) -> SubscriptionSearchJob | None:
        job = self.get_job(job_id)
        return job if job and job.owner_user_id == user_id else None

    def snapshot(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            return {
                "implemented": True,
                "jobId": job_id,
                "cards": [],
                "status": "unknown",
                "liveSearchPending": False,
                "mode": "unknown",
                "officialStatus": "unknown",
                "progress": self._empty_progress(),
                "message": "搜索任务不存在",
            }
        return self._snapshot(job)

    def find_card_group(self, job_id: str, candidate_id: str) -> dict[str, Any] | None:
        job = self.get_job(job_id)
        if not job:
            return None
        for group in job.card_groups:
            if group.get("candidateId") == candidate_id:
                return group
        return None

    def find_card_group_for_user(
        self, job_id: str, candidate_id: str, user_id: str
    ) -> dict[str, Any] | None:
        job = self.get_job_for_user(job_id, user_id)
        if not job:
            return None
        return next(
            (group for group in job.card_groups if group.get("candidateId") == candidate_id),
            None,
        )

    def _refresh_cards(self, job: SubscriptionSearchJob) -> None:
        """Rebuild the visible card list from the current stage state."""
        if job.official_items:
            job.official_groups = group_candidates(job.official_items, job.keyword)
        else:
            job.official_groups = []

        if job.official_groups:
            job.mode = "official-primary"
            job.card_groups = list(job.official_groups)
        else:
            job.card_groups = []

        self._rebuild_cards(job)

    def _sync_message(self, job: SubscriptionSearchJob) -> None:
        """Keep the user-facing progress message aligned with the active stage."""
        if job.status != "running":
            return
        if job.official_status == "running":
            if job.official_completed_count > 0:
                job.message = "官方源已返回部分结果，继续补充中。"
            else:
                job.message = "正在搜索官方源。"
            return
        if job.official_groups:
            job.message = "官方源已完成，结果已就绪。"
        else:
            job.message = "搜索中。"

    async def _run_job(self, job: SubscriptionSearchJob, official_plugins: list[Any]) -> None:
        try:
            await self._run_stage(job, official_plugins, official=True)
            job.official_status = "completed"
            self._refresh_cards(job)
            self._sync_message(job)
            if not job.official_groups and not job.card_groups:
                job.message = "官方源无命中。"
            job.status = "completed"
        except Exception as exc:
            job.status = "failed"
            job.message = f"订阅搜索失败: {exc}"
            job.events.append({"type": "job_error", "message": str(exc), "ts": time.time()})
        finally:
            if job.official_status == "running":
                job.official_status = "failed" if job.status == "failed" else "completed"
            self._sync_message(job)
            job.updated_at = time.time()
            self._persist_job_best_effort(job, context="job-finalize")

    async def _run_stage(self, job: SubscriptionSearchJob, plugins: list[Any], *, official: bool) -> None:
        if not plugins:
            return
        max_concurrency = self._positive_int(getattr(self.scheduler, "config", {}).get("max_concurrency"), 3)
        semaphore = asyncio.Semaphore(max_concurrency)

        async def search_plugin(plugin: Any) -> None:
            async with semaphore:
                source_id = plugin.metadata.id
                result = await self._search_one_for_subscription(source_id, job.keyword, job.page, official=official)
                items = self._source_result_items(result.get("items") or [])
                if official:
                    job.official_items.extend(items)
                    job.official_completed_count += 1
                if official or job.official_groups:
                    self._refresh_cards(job)
                    self._sync_message(job)
                error = result.get("error")
                if error:
                    code = str(error.get("code", "") if isinstance(error, dict) else "")
                    if "TIMEOUT" in code or code == "BROWSER_REQUIRED":
                        job.timeout_count += 1
                    else:
                        job.error_count += 1
                    event_type = "source_timeout" if "TIMEOUT" in code or code == "BROWSER_REQUIRED" else "source_error"
                    job.events.append({"type": event_type, "sourceId": source_id, "error": error, "official": official, "ts": time.time()})
                elif items:
                    job.success_count += 1
                    job.events.append({"type": "source_complete", "sourceId": source_id, "count": len(items), "official": official, "ts": time.time()})
                else:
                    job.events.append({"type": "source_empty", "sourceId": source_id, "official": official, "ts": time.time()})
                job.updated_at = time.time()
                self._persist_job_best_effort(job, context="source-complete")

        await asyncio.gather(*(search_plugin(plugin) for plugin in plugins))

    async def _search_one_for_subscription(self, source_id: str, keyword: str, page: int, *, official: bool) -> dict[str, Any]:
        # PluginScheduler owns asyncio semaphores, so all calls must stay on the
        # event loop where the scheduler is used.
        return await self.scheduler.search_one(source_id, keyword, page)

    def _split_plugins(self) -> tuple[list[Any], list[Any]]:
        plugins = [
            plugin
            for plugin in self.scheduler._enabled_plugins()
            if "search" in getattr(plugin, "capabilities", [])
        ]
        ordered = self.scheduler._search_priority_plugins(plugins)
        official = [plugin for plugin in ordered if plugin.metadata.is_official_source()]
        preferred_ids = self._official_source_priority_ids()
        official.sort(
            key=lambda plugin: (
                preferred_ids.get(plugin.metadata.id, len(preferred_ids)),
                getattr(plugin.metadata, "priority", 50) or 50,
                plugin.metadata.name or "",
                plugin.metadata.id,
            )
        )
        return official, []

    def _official_source_priority_ids(self) -> dict[str, int]:
        try:
            workflow = AppConfig.get().aggregate.content_workflow
            preferred = workflow.get("primarySourcePriority") or []
        except Exception:
            preferred = []
        order: dict[str, int] = {}
        for index, source_id in enumerate(preferred):
            source_id = str(source_id).strip()
            if source_id and source_id not in order:
                order[source_id] = index
        return order

    def _source_result_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converter = getattr(self.scheduler, "_source_result_items", None)
        if callable(converter):
            return converter(items)
        return [dict(item) for item in items if isinstance(item, dict)]

    def _rebuild_cards(self, job: SubscriptionSearchJob) -> None:
        cards: list[dict[str, Any]] = []
        for group in job.card_groups:
            if not isinstance(group, dict):
                continue
            card = self._public_card(self.library_service.build_subscription_card(group))
            book_id = str(card.get("aggregateBookId", "") or "")
            subscription = (
                self.subscription_service.get(job.owner_user_id, book_id) if book_id else None
            )
            card["alreadySubscribed"] = bool(subscription)
            card["subscriptionStatus"] = subscription.get("status", "") if subscription else ""
            cards.append(card)
        job.cards = cards

    def _public_card(self, card: dict[str, Any]) -> dict[str, Any]:
        public = dict(card)
        public.pop("debug", None)
        public.pop("addedByUserId", None)
        public.pop("addedByUsername", None)
        return public

    def _snapshot(self, job: SubscriptionSearchJob) -> dict[str, Any]:
        return {
            "implemented": True,
            "jobId": job.job_id,
            "keyword": job.keyword,
            "page": job.page,
            "status": job.status,
            "mode": job.mode,
            "officialStatus": job.official_status,
            "cards": list(job.cards),
            "liveSearchPending": job.status not in FINAL_STATUSES,
            "progress": self._progress(job),
            "message": job.message,
            "events": list(job.events[-50:]),
        }

    def _progress(self, job: SubscriptionSearchJob) -> dict[str, Any]:
        return {
            "sourceCount": job.official_source_count,
            "completedCount": job.official_completed_count,
            "foregroundSourceCount": job.official_source_count,
            "foregroundCompletedCount": job.official_completed_count,
            "officialSourceCount": job.official_source_count,
            "officialCompletedCount": job.official_completed_count,
            "successCount": job.success_count,
            "errorCount": job.error_count,
            "timeoutCount": job.timeout_count,
            "officialSourcesDone": job.official_status in FINAL_STATUSES,
        }

    def _empty_progress(self) -> dict[str, Any]:
        return {
            "sourceCount": 0,
            "completedCount": 0,
            "foregroundSourceCount": 0,
            "foregroundCompletedCount": 0,
            "officialSourceCount": 0,
            "officialCompletedCount": 0,
            "successCount": 0,
            "errorCount": 0,
            "timeoutCount": 0,
            "officialSourcesDone": False,
        }

    def _positive_int(self, value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _nonnegative_int(self, value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed >= 0 else default

    def _timestamp(self, value: Any, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 and math.isfinite(parsed) else default


subscription_search_service = SubscriptionSearchService()
