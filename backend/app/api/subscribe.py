"""Subscription/library APIs for shared aggregate books.

Copyright (c) 2026 moo. All rights reserved.
"""

from __future__ import annotations

import asyncio
import sqlite3

from fastapi import APIRouter, HTTPException, Request

from app.config import DB_PATH
from app.services.aggregate_processor import AggregateProcessor
from app.services.library_books import library_books_service
from app.services.search_jobs import SearchJobService
from app.services.user_auth import auth_service
from app.storage.db import initialize_database

router = APIRouter(prefix="/api/subscribe")
_search_service = SearchJobService()


def _build_cards(job_id: str) -> list[dict]:
    session = _search_service.get_session(job_id)
    if not session:
        return []
    groups = session.candidate_groups or []
    return [library_books_service.build_subscription_card(group) for group in groups if isinstance(group, dict)]


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

    job = _search_service.create_job(
        keyword=keyword,
        page=page,
        search_mode="subscription",
    )
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5.0
    while loop.time() < deadline:
        cards = _build_cards(job.job_id)
        session = _search_service.get_session(job.job_id)
        if cards:
            break
        if session and session.status not in {"running", "pending"}:
            break
        await asyncio.sleep(0.2)
    return {
        "implemented": True,
        "jobId": job.job_id,
        "keyword": job.keyword,
        "page": page,
        "cards": _build_cards(job.job_id),
        "status": "running",
        "liveSearchPending": True,
        "viewer": {"userId": user.user_id, "role": user.role},
    }


@router.get("/search/{job_id}")
def get_subscription_search(request: Request, job_id: str):
    auth_service.require_user(request)
    session = _search_service.get_session(job_id)
    if not session:
        return {
            "implemented": True,
            "jobId": job_id,
            "cards": [],
            "status": "unknown",
            "liveSearchPending": False,
        }
    return {
        "implemented": True,
        "jobId": job_id,
        "keyword": session.keyword,
        "page": session.page,
        "cards": _build_cards(job_id),
        "status": session.status,
        "liveSearchPending": session.status in {"running", "pending"},
    }


@router.post("/search/{job_id}/cards/{candidate_id}/subscribe")
async def subscribe_candidate(request: Request, job_id: str, candidate_id: str, payload: dict | None = None):
    user = auth_service.require_user(request)
    group = _search_service.find_candidate_group(job_id, candidate_id)
    if not group:
        raise HTTPException(status_code=404, detail="候选书籍不存在")
    payload = payload or {}
    start_chapter_index = max(1, int(payload.get("startChapterIndex", 1) or 1))
    auto_archive = bool(payload.get("autoArchiveOnComplete", True))
    created = library_books_service.create_or_get_shared_book(
        group,
        added_by_user_id=user.user_id,
        start_chapter_index=start_chapter_index,
        auto_archive_on_complete=auto_archive,
    )
    if not created.get("created"):
        raise HTTPException(status_code=409, detail="该书已入库，不能重复添加")
    book = created["book"]
    processor = AggregateProcessor()
    processor.enqueue_book(book["aggregateBookId"], created["payload"])
    asyncio.create_task(processor.bootstrap_book_until_visible(book["aggregateBookId"]))
    return {
        "ok": True,
        "created": True,
        "book": book,
    }


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
    book = library_books_service.get_book(aggregate_book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    payload = library_books_service.load_payload(aggregate_book_id)
    with sqlite3.connect(DB_PATH) as conn:
        sources = conn.execute(
            """
            SELECT source_id, source_book_id, source_name, source_book_url, role, score, enabled, last_chapter_title, chapter_count
            FROM aggregate_book_sources
            WHERE aggregate_book_id = ?
            ORDER BY CASE role WHEN 'primary' THEN 0 ELSE 1 END, score DESC, source_id ASC
            """,
            (aggregate_book_id,),
        ).fetchall()
    source_items = [
        {
            "sourceId": row[0],
            "sourceBookId": row[1],
            "sourceName": row[2],
            "sourceBookUrl": row[3],
            "role": row[4],
            "score": int(row[5] or 0),
            "enabled": bool(row[6]),
            "lastChapterTitle": row[7] or "",
            "chapterCount": int(row[8] or 0),
        }
        for row in sources
    ]
    return {"book": book, "payload": payload, "sources": source_items}


@router.get("/books/{aggregate_book_id}/chapters")
def list_library_book_chapters(request: Request, aggregate_book_id: str, limit: int = 200):
    auth_service.require_user(request)
    initialize_database(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT chapter_id, source_chapter_id, chapter_index, title, status, placeholder,
                   content_length, content_file_path, processed_content, last_processed_at
            FROM aggregate_chapter_tasks
            WHERE aggregate_book_id = ?
            ORDER BY COALESCE(chapter_index, 999999), created_at
            LIMIT ?
            """,
            (aggregate_book_id, max(1, min(int(limit or 200), 1000))),
        ).fetchall()
    items = [
        {
            "chapterId": row[0],
            "sourceChapterId": row[1],
            "chapterIndex": int(row[2] or 0),
            "title": row[3] or "",
            "status": row[4] or "pending",
            "placeholder": bool(row[5]),
            "contentLength": int(row[6] or 0),
            "contentFilePath": row[7] or "",
            "hasContent": bool(row[8]),
            "processedAt": row[9] or "",
        }
        for row in rows
    ]
    return {"items": items, "total": len(items)}
