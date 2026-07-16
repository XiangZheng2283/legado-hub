"""Dedicated shared-subscription search pipeline."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.core.app_config import AppConfig
from app.services.library_books import library_books_service
from app.services.live_acceptance import group_candidates
from app.services.user_subscriptions import user_subscriptions_service
from app.source_plugins.scheduler import get_plugin_scheduler


FINAL_STATUSES = {"completed", "partial", "timed_out", "failed", "cancelled"}


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
    ):
        self.scheduler = scheduler or get_plugin_scheduler()
        self.library_service = library_service or library_books_service
        self.subscription_service = subscription_service or user_subscriptions_service
        self._jobs: dict[str, SubscriptionSearchJob] = {}

    def create_job(self, keyword: str, page: int = 1, *, owner_user_id: str) -> SubscriptionSearchJob:
        job = SubscriptionSearchJob(
            job_id=uuid.uuid4().hex,
            owner_user_id=owner_user_id,
            keyword=keyword,
            page=max(1, int(page or 1)),
        )
        self._jobs[job.job_id] = job
        official_plugins, _ = self._split_plugins()
        job.official_source_count = len(official_plugins)
        if not official_plugins:
            job.status = "completed"
            job.official_status = "completed"
            job.mode = "no-official-source"
            job.message = "未检测到可用官方源，订阅搜索不会生成入库卡片。"
            job.updated_at = time.time()
            return job
        job.status = "running"
        job.official_status = "running"
        asyncio.create_task(self._run_job(job, official_plugins))
        return job

    def get_job(self, job_id: str) -> SubscriptionSearchJob | None:
        return self._jobs.get(job_id)

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

        await asyncio.gather(*(search_plugin(plugin) for plugin in plugins))

    async def _search_one_for_subscription(self, source_id: str, keyword: str, page: int, *, official: bool) -> dict[str, Any]:
        return await asyncio.to_thread(self._search_one_blocking, source_id, keyword, page)

    def _search_one_blocking(self, source_id: str, keyword: str, page: int) -> dict[str, Any]:
        # ponytail: isolate plugin code from FastAPI's event loop; move to a
        # process worker only if source threads become a measured bottleneck.
        return asyncio.run(self.scheduler.search_one(source_id, keyword, page))

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


subscription_search_service = SubscriptionSearchService()
