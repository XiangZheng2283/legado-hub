"""Realtime search job management.

This module is a thin compatibility wrapper around SearchCoordinator.
The internal execution logic has moved to app.services.search_coordinator so
that console.py, legado.py and the process worker can keep their existing
import signatures unchanged.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.core.app_config import AppConfig
from app.services.search_coordinator import SearchCoordinator, SearchJob, SearchSession


# Re-export so callers that imported from here keep working.
__all__ = ["SearchJob", "SearchSession", "SearchJobService"]


class SearchJobService:
    def __init__(self):
        self._coordinator = SearchCoordinator()

    @property
    def scheduler(self):
        return self._coordinator.scheduler

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------

    def create_job(
        self,
        keyword: str,
        page: int = 1,
        limit: int | None = None,
        source_ids: list[str] | None = None,
        search_mode: str = "source",
    ) -> SearchJob:
        """Create a search job.  Always starts a live search.

        ``search_mode``: "source" for normal source search,
        "aggregate" for AI aggregate mode.
        """
        return self._coordinator.submit(
            keyword, page, source_ids, limit, search_mode=search_mode
        )

    def schedule_job(self, job_id: str) -> None:
        """Trigger execution if the coordinator has not already started the task."""
        self._coordinator.ensure_running(job_id)

    def persist_job(self, job: SearchJob) -> None:
        self._coordinator._persist_job(job)

    def get_job(self, job_id: str) -> SearchJob | None:
        return self._coordinator.get_job(job_id)

    def refresh_job(self, job_id: str) -> SearchJob | None:
        """Force reload from persistence to see updates from background workers."""
        return self._coordinator._load_job(job_id)

    def refresh_job_snapshot(self, job_id: str) -> SearchJob | None:
        """Return the in-memory job or reload it from persistence."""
        return self._coordinator.get_job(job_id) or self._coordinator._load_job(job_id)

    def list_jobs(self, limit: int = 20) -> list[dict]:
        return self._coordinator.list_jobs(limit)

    def get_events(self, job_id: str, after_index: int = 0) -> list[dict]:
        return self._coordinator.get_events(job_id, after_index)

    def get_candidates(self, job_id: str) -> list[dict]:
        return self._coordinator.get_candidates(job_id)

    def find_candidate(self, job_id: str, candidate_id: str) -> dict | None:
        return self._coordinator.find_candidate(job_id, candidate_id)

    def cancel_job(self, job_id: str) -> bool:
        return self._coordinator.cancel_job(job_id)

    def find_active_job(
        self, keyword: str, page: int = 1, source_ids: list[str] | None = None
    ) -> SearchJob | None:
        return self._coordinator.find_active_job(keyword, page, source_ids)

    # ------------------------------------------------------------------
    # Session access (new model)
    # ------------------------------------------------------------------

    def get_session(self, job_id: str) -> SearchSession | None:
        """Return the in-memory search session for a job."""
        return self._coordinator.get_session(job_id)

    def session_snapshot(
        self,
        job_id: str,
        base_api: str | None = None,
        include_official_sources: bool = True,
    ) -> dict | None:
        """Render a session into the API response shape with merged items."""
        return self._coordinator.session_snapshot(
            job_id, base_api, include_official_sources
        )

    # ------------------------------------------------------------------
    # Score filter utilities (still accessed by console.py)
    # ------------------------------------------------------------------

    def _get_score_filter(self) -> int:
        try:
            val = AppConfig.get().search.score_filter
            if isinstance(val, int) and val >= 0:
                return val
        except Exception:
            pass
        return 100

    def _apply_score_filter(self, items: list[dict]) -> tuple[list[dict], int, int]:
        """Return (filtered_items, threshold, filtered_count)."""
        score_filter = self._get_score_filter()
        filtered_items = [item for item in items if item.get("score", 0) >= score_filter]
        return filtered_items, score_filter, len(items) - len(filtered_items)

    # ------------------------------------------------------------------
    # Backward-compatible execution entry point for process workers
    # ------------------------------------------------------------------

    async def run_job(self, job_id: str) -> None:
        await self._coordinator.run_job(job_id)
