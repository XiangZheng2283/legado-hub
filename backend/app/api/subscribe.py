"""Subscription/library APIs for shared aggregate books.

Copyright (c) 2026 moo. All rights reserved.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from app.core.app_config import AppConfig
from app.core.legado_source import generate_legado_source
from app.services.aggregate_processor import AggregateProcessor
from app.services.library_books import library_books_service
from app.services.search_jobs import SearchJobService
from app.services.shared_book_scheduler import SharedBookScheduler
from app.services.subscription_search import subscription_search_service
from app.services.user_auth import auth_service

router = APIRouter(prefix="/api/subscribe")

_TERMINAL_STATUSES = {"completed", "partial", "timed_out", "failed", "cancelled"}
_legado_search_service: SearchJobService | None = None


def _get_legado_search_service() -> SearchJobService:
    global _legado_search_service
    if _legado_search_service is None:
        _legado_search_service = SearchJobService()
    return _legado_search_service


@router.post("/search")
async def subscription_search(request: Request, payload: dict):
    user = auth_service.require_user(request)
    keyword = str(payload.get("keyword", "")).strip()
    page = int(payload.get("page", 1) or 1)
    if not keyword:
        return {
            "implemented": True,
            "jobId": "",
            "keyword": keyword,
            "page": page,
            "cards": [],
            "status": "completed",
            "liveSearchPending": False,
        }

    job = subscription_search_service.create_job(keyword=keyword, page=page)
    snapshot = subscription_search_service.snapshot(job.job_id)
    snapshot["viewer"] = {"userId": user.user_id, "role": user.role}
    return snapshot


@router.get("/search/{job_id}")
def get_subscription_search(request: Request, job_id: str):
    auth_service.require_user(request)
    return subscription_search_service.snapshot(job_id)


@router.post("/search/{job_id}/cards/{candidate_id}/subscribe")
async def subscribe_candidate(request: Request, job_id: str, candidate_id: str, payload: dict | None = None):
    user = auth_service.require_user(request)
    group = subscription_search_service.find_card_group(job_id, candidate_id)
    if not group:
        raise HTTPException(status_code=404, detail="候选书籍不存在")
    payload = payload or {}
    start_chapter_index = max(1, int(payload.get("startChapterIndex", 1) or 1))
    auto_archive = bool(payload.get("autoArchiveOnComplete", True))
    created = await library_books_service.create_or_get_shared_book(
        group,
        added_by_user_id=user.user_id,
        start_chapter_index=start_chapter_index,
        auto_archive_on_complete=auto_archive,
    )
    if not created.get("created"):
        raise HTTPException(status_code=409, detail="该书已入库，不能重复添加")
    book = created["book"]
    processor = AggregateProcessor()
    initial_next_check = (
        datetime.now(timezone.utc)
        + timedelta(minutes=processor.check_interval_minutes(book["aggregateBookId"]))
    ).isoformat()
    processor.enqueue_book(
        book["aggregateBookId"],
        created["payload"],
        next_check_time=initial_next_check,
    )
    scheduler = SharedBookScheduler(processor=processor)
    scheduler.enqueue_initial_subscription(
        book["aggregateBookId"],
        payload=created["payload"],
        book_name=book.get("name", ""),
        author=book.get("author", ""),
    )
    asyncio.create_task(scheduler.run_periodic_once(wait_for_recovery=False, include_due_books=False))
    return {
        "ok": True,
        "created": True,
        "book": book,
        "subscriptionConfig": {
            "coverUrl": book.get("coverUrl", ""),
            "name": book.get("name", ""),
            "author": book.get("author", ""),
            "intro": book.get("intro", ""),
            "bookStatus": book.get("bookStatus", ""),
            "totalChaptersAtSubscribe": book.get("totalChaptersAtSubscribe", 0),
            "startChapterIndex": book.get("startChapterIndex", 1),
            "autoArchiveOnComplete": book.get("autoArchiveOnComplete", True),
            "primarySourceId": book.get("primarySourceId", ""),
            "primarySourceName": book.get("primarySourceName", ""),
            "primaryBookId": book.get("primaryBookId", ""),
            "supplementSourceConfig": (
                __import__("json").loads(book.get("settingsJson", "") or "{}").get("supplementSourceConfig", {})
                if book.get("settingsJson", "")
                else {}
            ),
        },
    }


@router.post("/books/{aggregate_book_id}/source-map/refresh")
async def refresh_library_book_source_map(request: Request, aggregate_book_id: str, payload: dict | None = None):
    auth_service.require_admin(request)
    from app.api.console import _manual_source_map_refresh

    result = _manual_source_map_refresh(aggregate_book_id, payload=payload)
    if asyncio.iscoroutine(result):
        result = await result
    if not result.get("ok") and result.get("error") == "书籍不存在":
        raise HTTPException(status_code=404, detail="书籍不存在")
    return result


@router.get("/library")
def list_library(request: Request, keyword: str = ""):
    auth_service.require_user(request)
    items = library_books_service.list_books(keyword=keyword, include_hidden=True)
    return {"items": items, "total": len(items)}


@router.get("/library/mine")
def list_my_library(request: Request, keyword: str = ""):
    user = auth_service.require_user(request)
    items = library_books_service.list_books(
        added_by_user_id=user.user_id, keyword=keyword, include_hidden=True
    )
    return {"items": items, "total": len(items)}


@router.get("/books/{aggregate_book_id}")
def get_library_book(request: Request, aggregate_book_id: str):
    auth_service.require_user(request)
    detail = library_books_service.get_shared_book_detail(aggregate_book_id)
    if not detail.get("found"):
        raise HTTPException(status_code=404, detail="书籍不存在")
    return detail


@router.get("/books/{aggregate_book_id}/chapters")
def list_library_book_chapters(
    request: Request,
    aggregate_book_id: str,
    page: int = 1,
    pageSize: int = 200,
    status: str = "all",
):
    auth_service.require_user(request)
    return library_books_service.list_shared_chapters(
        aggregate_book_id,
        page=page,
        pageSize=pageSize,
        status=status,
    )


# ---- Legado virtual source (migrated from /api/legado) ----

@router.get("/legado/source")
def get_legado_source(request: Request) -> list[dict]:
    base_api = str(request.base_url).rstrip("/")
    return generate_legado_source(base_api)


@router.get("/legado/search")
async def legado_search(
    request: Request,
    keyword: str = "",
    page: int = 1,
    waitMs: int = 120000,
) -> dict:
    if not keyword.strip():
        return {
            "implemented": True,
            "keyword": keyword,
            "page": page,
            "items": [],
            "jobId": "",
            "status": "completed",
            "liveSearchPending": False,
            "debug": {"sourceCount": 0},
        }

    search_service = _get_legado_search_service()
    base_api = str(request.base_url).rstrip("/")
    wait_seconds = max(0, min(waitMs, 180000)) / 1000

    job = search_service.create_job(keyword=keyword, page=page, search_mode="source")

    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    next_poll = loop.time() + 0.5
    while loop.time() < deadline:
        session = search_service.get_session(job.job_id)
        if session and session.status in _TERMINAL_STATUSES:
            break
        if loop.time() >= next_poll:
            next_poll = loop.time() + 0.5
        await asyncio.sleep(0.1)

    include_official = AppConfig.get().search.official_source_in_normal_search
    result = search_service.session_snapshot(
        job.job_id, base_api=base_api, include_official_sources=include_official
    )
    if result:
        result["debug"] = {
            **(result.get("debug") or {}),
            "timeoutSeconds": int(wait_seconds),
        }
        return result

    return {
        "implemented": True,
        "keyword": keyword,
        "page": page,
        "items": [],
        "jobId": job.job_id,
        "status": "failed",
        "liveSearchPending": False,
        "debug": {"timeoutSeconds": int(wait_seconds)},
    }


@router.get("/legado/search/{job_id}")
async def get_legado_search_status(request: Request, job_id: str) -> dict:
    search_service = _get_legado_search_service()
    base_api = str(request.base_url).rstrip("/")
    include_official = AppConfig.get().search.official_source_in_normal_search
    result = search_service.session_snapshot(
        job_id, base_api=base_api, include_official_sources=include_official
    )
    if result:
        return result
    return {
        "implemented": True,
        "jobId": job_id,
        "status": "unknown",
        "items": [],
        "liveSearchPending": False,
        "debug": {"message": "任务不存在或已过期"},
    }


@router.post("/legado/search/{job_id}/cancel")
async def cancel_legado_search(job_id: str) -> dict:
    ok = _get_legado_search_service().cancel_job(job_id)
    return {"jobId": job_id, "cancelled": ok}


@router.get("/legado/explore")
async def legado_explore(request: Request, sourceId: str = "", groupId: str = "", page: int = 1) -> dict:
    from app.services.catalog import Catalog
    catalog = Catalog(base_api=str(request.base_url).rstrip("/"))
    return await catalog.explore(source_id=sourceId, group_id=groupId, page=page)
