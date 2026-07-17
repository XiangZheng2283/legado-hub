"""Subscription/library APIs for shared aggregate books.

Copyright (c) 2026 moo. All rights reserved.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from app.core.legado_source import generate_legado_source
from app.services.aggregate_processor import AggregateProcessor
from app.services.aggregate_virtual_source import VIRTUAL_SOURCE_ID, unpack_aggregate_chapter_url
from app.services.catalog import Catalog
from app.services.library_books import library_books_service
from app.services.shared_book_scheduler import SharedBookScheduler
from app.services.subscription_search import subscription_search_service
from app.services.user_subscriptions import (
    SubscriptionLimitError,
    subscription_rate_limiter,
    user_subscriptions_service,
)
from app.services.user_auth import auth_service
from app.source_plugins.id_codec import decode_chapter_id

router = APIRouter(prefix="/api/subscribe")
_shared_book_creation_lock = threading.Lock()


@asynccontextmanager
async def _shared_book_creation_guard():
    # ponytail: process-wide polling lock; replace with a DB reservation for multi-process deployment.
    while not _shared_book_creation_lock.acquire(blocking=False):
        await asyncio.sleep(0.01)
    try:
        yield
    finally:
        _shared_book_creation_lock.release()

_USER_BOOK_FIELDS = {
    "aggregateBookId",
    "name",
    "author",
    "coverUrl",
    "intro",
    "wordCount",
    "bookStatus",
    "totalChapters",
    "processedChapters",
    "visibleProcessedChapters",
    "failedChapters",
    "status",
    "searchVisibilityStatus",
    "lastSourceChapterTitle",
    "lastLocalChapterTitle",
    "createdAt",
    "updatedAt",
}


def _limit_detail(exc: SubscriptionLimitError) -> dict:
    detail = {"code": exc.code, "message": str(exc), "retryable": exc.retryable}
    if exc.retry_after_seconds is not None:
        detail["retryAfterSeconds"] = exc.retry_after_seconds
    return detail


def _start_chapter_index(payload: dict, default: int = 1) -> int:
    value = payload.get("startChapterIndex", default)
    if isinstance(value, bool):
        raise HTTPException(status_code=422, detail="startChapterIndex 必须是大于等于 1 的整数")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise HTTPException(status_code=422, detail="startChapterIndex 必须是大于等于 1 的整数")
    if parsed < 1:
        raise HTTPException(status_code=422, detail="startChapterIndex 必须是大于等于 1 的整数")
    return parsed


def _auto_archive_on_complete(payload: dict, default: bool = True) -> bool:
    value = payload.get("autoArchiveOnComplete", default)
    if not isinstance(value, bool):
        raise HTTPException(status_code=422, detail="autoArchiveOnComplete 必须是布尔值")
    return value


async def _create_or_get_book_for_subscription(group: dict, user_id: str, existing: dict | None) -> dict:
    current_subscription = (
        user_subscriptions_service.get(user_id, existing["aggregateBookId"])
        if existing else None
    )
    if not current_subscription or current_subscription.get("status") == "archived":
        user_subscriptions_service.check_capacity(
            user_id, creates_shared_book=existing is None
        )
    try:
        return await library_books_service.create_or_get_shared_book(
            group, actor_user_id=user_id
        )
    except sqlite3.IntegrityError:
        raced_book = library_books_service.find_existing_book(group)
        if not raced_book:
            raise
        return {"created": False, "book": raced_book}


def _safe_user_book(book: dict | None) -> dict:
    source = book or {}
    result = {key: source[key] for key in _USER_BOOK_FIELDS if key in source}
    for key in ("subscription", "personalProgress", "bookState"):
        value = source.get(key)
        if isinstance(value, dict):
            result[key] = dict(value)
    return result


def _require_book_access(user, aggregate_book_id: str) -> dict | None:
    if user.role == "admin":
        return user_subscriptions_service.get(user.user_id, aggregate_book_id)
    subscription = user_subscriptions_service.get(user.user_id, aggregate_book_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return subscription


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
    try:
        subscription_rate_limiter.check(user.user_id, "search")
    except SubscriptionLimitError as exc:
        raise HTTPException(status_code=429, detail=_limit_detail(exc)) from exc

    job = subscription_search_service.create_job(
        keyword=keyword, page=page, owner_user_id=user.user_id
    )
    snapshot = subscription_search_service.snapshot(job.job_id)
    snapshot["viewer"] = {"userId": user.user_id, "role": user.role}
    return snapshot


@router.get("/search/{job_id}")
def get_subscription_search(request: Request, job_id: str):
    user = auth_service.require_user(request)
    if not subscription_search_service.get_job_for_user(job_id, user.user_id):
        raise HTTPException(status_code=404, detail="搜索任务不存在")
    return subscription_search_service.snapshot(job_id)


@router.post("/search/{job_id}/cards/{candidate_id}/subscribe")
async def subscribe_candidate(request: Request, job_id: str, candidate_id: str, payload: dict | None = None):
    user = auth_service.require_user(request)
    group = subscription_search_service.find_card_group_for_user(
        job_id, candidate_id, user.user_id
    )
    if not group:
        raise HTTPException(status_code=404, detail="候选书籍不存在")
    payload = payload or {}
    unknown = set(payload) - {"startChapterIndex", "autoArchiveOnComplete"}
    if unknown:
        raise HTTPException(status_code=422, detail=f"不支持的字段: {', '.join(sorted(unknown))}")
    start_chapter_index = _start_chapter_index(payload)
    auto_archive = _auto_archive_on_complete(payload)
    try:
        subscription_rate_limiter.check(user.user_id, "create")
    except SubscriptionLimitError as exc:
        raise HTTPException(status_code=429, detail=_limit_detail(exc)) from exc
    existing = library_books_service.find_existing_book(group)
    try:
        if existing is None:
            async with _shared_book_creation_guard():
                existing = library_books_service.find_existing_book(group)
                created = await _create_or_get_book_for_subscription(
                    group, user.user_id, existing
                )
                subscription, subscription_created = user_subscriptions_service.ensure(
                    user.user_id,
                    created["book"]["aggregateBookId"],
                    start_chapter_index=start_chapter_index,
                    auto_archive_on_complete=auto_archive,
                )
        else:
            created = await _create_or_get_book_for_subscription(
                group, user.user_id, existing
            )
            subscription, subscription_created = user_subscriptions_service.ensure(
                user.user_id,
                created["book"]["aggregateBookId"],
                start_chapter_index=start_chapter_index,
                auto_archive_on_complete=auto_archive,
            )
    except SubscriptionLimitError as exc:
        raise HTTPException(status_code=429, detail=_limit_detail(exc)) from exc
    book = created["book"]
    safe_book = _safe_user_book(book)
    if created.get("created"):
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
        "created": bool(created.get("created")),
        "sharedBookCreated": bool(created.get("created")),
        "subscriptionCreated": subscription_created,
        "book": safe_book,
        "subscription": subscription,
        "subscriptionConfig": {
            "coverUrl": book.get("coverUrl", ""),
            "name": book.get("name", ""),
            "author": book.get("author", ""),
            "intro": book.get("intro", ""),
            "bookStatus": book.get("bookStatus", ""),
            "totalChaptersAtSubscribe": book.get("totalChaptersAtSubscribe", 0),
            "startChapterIndex": subscription["startChapterIndex"],
            "autoArchiveOnComplete": subscription["autoArchiveOnComplete"],
            "primarySourceName": book.get("primarySourceName", ""),
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
    auth_service.require_admin(request)
    items = library_books_service.list_books(keyword=keyword, include_hidden=True)
    return {"items": items, "total": len(items)}


@router.get("/library/mine")
def list_my_library(request: Request, keyword: str = ""):
    user = auth_service.require_user(request)
    items = user_subscriptions_service.list_books(
        user.user_id, library_books_service, keyword=keyword
    )
    return {"items": [_safe_user_book(item) for item in items], "total": len(items)}


@router.get("/books/{aggregate_book_id}")
def get_library_book(request: Request, aggregate_book_id: str):
    user = auth_service.require_user(request)
    subscription = _require_book_access(user, aggregate_book_id)
    detail = library_books_service.get_shared_book_detail(aggregate_book_id)
    if not detail.get("found"):
        raise HTTPException(status_code=404, detail="书籍不存在")
    detail = {
        "bookId": aggregate_book_id,
        "found": True,
        "book": _safe_user_book(detail.get("book")),
        "bookState": dict(detail.get("bookState") or {}),
    }
    detail["subscription"] = subscription
    if subscription:
        detail["personalProgress"] = user_subscriptions_service.progress(
            subscription, library_books_service
        )
    return detail


@router.get("/books/{aggregate_book_id}/chapters")
def list_library_book_chapters(
    request: Request,
    aggregate_book_id: str,
    page: int = 1,
    pageSize: int = 200,
    status: str = "all",
    keyword: str = "",
):
    user = auth_service.require_user(request)
    _require_book_access(user, aggregate_book_id)
    return library_books_service.list_shared_chapters(
        aggregate_book_id,
        page=page,
        pageSize=pageSize,
        status=status,
        keyword=keyword,
    )


@router.get("/books/{aggregate_book_id}/subscription")
def get_subscription(request: Request, aggregate_book_id: str):
    user = auth_service.require_user(request)
    subscription = user_subscriptions_service.get(user.user_id, aggregate_book_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    return {"subscription": subscription}


@router.put("/books/{aggregate_book_id}/subscription")
def put_subscription(request: Request, aggregate_book_id: str, payload: dict | None = None):
    user = auth_service.require_user(request)
    payload = payload or {}
    unknown = set(payload) - {"startChapterIndex", "autoArchiveOnComplete"}
    if unknown:
        raise HTTPException(status_code=422, detail=f"不支持的字段: {', '.join(sorted(unknown))}")
    if not library_books_service.get_book(aggregate_book_id):
        raise HTTPException(status_code=404, detail="书籍不存在")
    start_chapter_index = _start_chapter_index(payload)
    auto_archive = _auto_archive_on_complete(payload)
    try:
        subscription_rate_limiter.check(user.user_id, "create")
    except SubscriptionLimitError as exc:
        raise HTTPException(status_code=429, detail=_limit_detail(exc)) from exc
    try:
        subscription, created = user_subscriptions_service.ensure(
            user.user_id,
            aggregate_book_id,
            start_chapter_index=start_chapter_index,
            auto_archive_on_complete=auto_archive,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="书籍不存在") from exc
    except SubscriptionLimitError as exc:
        raise HTTPException(status_code=429, detail=_limit_detail(exc)) from exc
    return {"created": created, "subscription": subscription}


@router.patch("/books/{aggregate_book_id}/subscription")
def patch_subscription(request: Request, aggregate_book_id: str, payload: dict | None = None):
    user = auth_service.require_user(request)
    payload = payload or {}
    unknown = set(payload) - {"status", "startChapterIndex", "autoArchiveOnComplete"}
    if unknown:
        raise HTTPException(status_code=422, detail=f"不支持的字段: {', '.join(sorted(unknown))}")
    if "startChapterIndex" in payload:
        payload["startChapterIndex"] = _start_chapter_index(payload)
    if "autoArchiveOnComplete" in payload:
        payload["autoArchiveOnComplete"] = _auto_archive_on_complete(payload)
    try:
        subscription = user_subscriptions_service.update(
            user.user_id,
            aggregate_book_id,
            payload,
            before_change=lambda: subscription_rate_limiter.check(user.user_id, "update"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="订阅不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SubscriptionLimitError as exc:
        raise HTTPException(status_code=429, detail=_limit_detail(exc)) from exc
    return {"subscription": subscription}


@router.get("/chapters/{chapter_id}")
async def get_subscribed_chapter(request: Request, chapter_id: str):
    user = auth_service.require_user(request)
    try:
        source_id, chapter_url = decode_chapter_id(chapter_id)
        payload = unpack_aggregate_chapter_url(chapter_url)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="章节不存在") from exc
    if source_id != VIRTUAL_SOURCE_ID:
        raise HTTPException(status_code=404, detail="章节不存在")
    _require_book_access(user, str(payload.get("aggregateBookId", "") or ""))
    result = await Catalog().chapter(chapter_id)
    return {
        "implemented": bool(result.get("implemented", True)),
        "chapterId": str(result.get("chapterId", chapter_id) or chapter_id),
        "title": str(result.get("title", "") or ""),
        "content": str(result.get("content", "") or ""),
        "authRequired": bool(result.get("authRequired", False)),
        "isPaid": bool(result.get("isPaid", False)),
        "isVip": bool(result.get("isVip", False)),
        "previewOnly": bool(result.get("previewOnly", False)),
        "extra": dict(result.get("extra") or {}) if isinstance(result.get("extra"), dict) else {},
    }


# ---- Legado virtual source (migrated from /api/legado) ----

@router.get("/legado/source")
def get_legado_source(request: Request) -> list[dict]:
    base_api = str(request.base_url).rstrip("/")
    return generate_legado_source(base_api)


@router.get("/legado/search")
def legado_search(
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

    base_api = str(request.base_url).rstrip("/")
    books = library_books_service.search_published_books(keyword)
    items = [
        library_books_service.build_search_injected_item(book, base_api=base_api)
        for book in books
    ]
    page = max(1, int(page or 1))
    offset = (page - 1) * 20
    return {
        "implemented": True,
        "keyword": keyword,
        "page": page,
        "items": items[offset : offset + 20],
        "jobId": "",
        "status": "completed",
        "liveSearchPending": False,
        "debug": {"publishedCount": len(items)},
    }


@router.get("/legado/search/{job_id}")
async def get_legado_search_status(request: Request, job_id: str) -> dict:
    return {
        "implemented": True,
        "jobId": job_id,
        "status": "unknown",
        "items": [],
        "liveSearchPending": False,
        "debug": {"message": "任务不存在或已过期"},
    }


@router.post("/legado/search/{job_id}/cancel")
async def cancel_legado_search(request: Request, job_id: str) -> dict:
    auth_service.require_admin(request)
    return {"jobId": job_id, "cancelled": False}


@router.get("/legado/explore")
async def legado_explore(request: Request, sourceId: str = "", groupId: str = "", page: int = 1) -> dict:
    base_api = str(request.base_url).rstrip("/")
    books = library_books_service.list_published_books()
    items = [
        library_books_service.build_search_injected_item(book, base_api=base_api)
        for book in books
    ]
    page = max(1, int(page or 1))
    offset = (page - 1) * 20
    return {
        "implemented": True,
        "groupId": groupId or "published",
        "page": page,
        "items": items[offset : offset + 20],
        "debug": {"publishedCount": len(items)},
    }
