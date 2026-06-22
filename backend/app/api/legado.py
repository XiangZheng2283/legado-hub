"""Legado-facing endpoints for source JSON and API contract."""

import asyncio

from fastapi import APIRouter, Request

from app.core.app_config import AppConfig
from app.core.source_generator import generate_aggregate_source
from app.services.catalog import Catalog
from app.services.live_acceptance import LiveAcceptanceService
from app.services.search_jobs import SearchJobService

router = APIRouter(prefix="/api/legado")
_search_service: SearchJobService | None = None
_search_service_init_token = None
_live_acceptance_service = LiveAcceptanceService()

_TERMINAL_STATUSES = {"completed", "partial", "timed_out", "failed", "cancelled"}


def _get_search_service() -> SearchJobService:
    global _search_service, _search_service_init_token
    init_token = SearchJobService.__init__
    if _search_service is None or _search_service_init_token is not init_token:
        _search_service = SearchJobService()
        _search_service_init_token = init_token
    return _search_service


@router.get("/source")
def get_source(request: Request) -> list[dict]:
    base_api = str(request.base_url).rstrip("/")
    return generate_aggregate_source(base_api)


@router.get("/search")
async def search(
    request: Request,
    keyword: str = "",
    page: int = 1,
    waitMs: int = 120000,
) -> dict:
    """Legado reading client source search endpoint.

    Always starts a live search. Blocks up to waitMs for results.
    """
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

    search_service = _get_search_service()
    base_api = str(request.base_url).rstrip("/")
    wait_seconds = max(0, min(waitMs, 180000)) / 1000

    # Submit: always starts a live search.
    job = search_service.create_job(
        keyword=keyword, page=page, search_mode="source"
    )

    # Block-wait for results.
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

    # Render final snapshot.  Respect global official source setting.
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


@router.get("/search/{job_id}")
async def get_search_status(request: Request, job_id: str) -> dict:
    """Poll endpoint for reading client to get search job status and results."""
    search_service = _get_search_service()
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


@router.post("/search/{job_id}/cancel")
async def cancel_search(job_id: str) -> dict:
    ok = _get_search_service().cancel_job(job_id)
    return {"jobId": job_id, "cancelled": ok}


@router.get("/explore")
async def explore(request: Request, sourceId: str = "", groupId: str = "", page: int = 1) -> dict:
    catalog = Catalog(base_api=str(request.base_url).rstrip("/"))
    return await catalog.explore(source_id=sourceId, group_id=groupId, page=page)


@router.get("/book/{book_id}")
async def get_book(request: Request, book_id: str) -> dict:
    catalog = Catalog(base_api=str(request.base_url).rstrip("/"))
    return await catalog.book_detail(book_id)


@router.get("/book/{book_id}/toc")
async def get_toc(request: Request, book_id: str) -> dict:
    catalog = Catalog(base_api=str(request.base_url).rstrip("/"))
    return await catalog.toc(book_id)


@router.get("/chapter/{chapter_id}")
async def get_chapter(chapter_id: str) -> dict:
    catalog = Catalog()
    return await catalog.chapter(chapter_id)


@router.get("/chapter/{chapter_id}/reviews")
async def get_chapter_reviews(chapter_id: str) -> dict:
    catalog = Catalog()
    return await catalog.chapter_reviews(chapter_id)
