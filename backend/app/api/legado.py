"""Legado-facing endpoints for source JSON and API contract."""

import asyncio
import threading

from fastapi import APIRouter, Request

from app.core.source_generator import generate_aggregate_source
from app.services.catalog import Catalog
from app.services.live_acceptance import LiveAcceptanceService
from app.services.search_jobs import SearchJobService

router = APIRouter(prefix="/api/legado")
_search_service: SearchJobService | None = None
_search_service_init_token = None
_live_acceptance_service = LiveAcceptanceService()


def _get_search_service() -> SearchJobService:
    global _search_service, _search_service_init_token
    init_token = SearchJobService.__init__
    if _search_service is None or _search_service_init_token is not init_token:
        _search_service = SearchJobService()
        _search_service_init_token = init_token
    return _search_service


def _run_search_job_blocking(service: SearchJobService, job_id: str) -> None:
    asyncio.run(service.run_job(job_id))


@router.get("/source")
def get_source(request: Request) -> list[dict]:
    base_api = str(request.base_url).rstrip("/")
    return generate_aggregate_source(base_api)


@router.get("/search")
async def search(request: Request, keyword: str = "", page: int = 1, waitMs: int = 180000) -> dict:
    if not keyword.strip():
        return {"implemented": True, "keyword": keyword, "page": page, "items": [], "debug": {"sourceCount": 0}}
    search_service = _get_search_service()
    base_api = str(request.base_url).rstrip("/")
    cached_snapshot = getattr(search_service, "cached_snapshot", None)
    cached = (
        cached_snapshot(keyword, page, base_api=base_api, include_official_sources=False)
        if callable(cached_snapshot)
        else None
    )
    job = search_service.find_active_job(keyword, page)
    if cached is not None:
        if job is None:
            job = search_service.create_job(keyword=keyword, page=page)
            job.status = "running"
            job.events.append({
                "type": "queued",
                "keyword": keyword,
                "page": page,
                "sourceCount": len(job.sources),
                "completedCount": 0,
                "message": "缓存命中，后台刷新搜索结果",
            })
            search_service.persist_job(job)
            threading.Thread(
                target=_run_search_job_blocking,
                args=(search_service, job.job_id),
                daemon=True,
            ).start()
        cached["jobId"] = job.job_id if job is not None else ""
        cached_debug = dict(cached.get("debug") or {})
        cached_debug["backgroundRefresh"] = True
        cached["debug"] = cached_debug
        return cached
    if job is None:
        job = search_service.create_job(keyword=keyword, page=page)
        job.status = "running"
        job.events.append({
            "type": "queued",
            "keyword": keyword,
            "page": page,
            "sourceCount": len(job.sources),
            "completedCount": 0,
        })
        search_service.persist_job(job)
        threading.Thread(target=_run_search_job_blocking, args=(search_service, job.job_id), daemon=True).start()
    deadline = asyncio.get_running_loop().time() + max(0, min(waitMs, 180000)) / 1000
    while asyncio.get_running_loop().time() < deadline:
        if job.status in {"completed", "cancelled"}:
            break
        await asyncio.sleep(0.1)
    return search_service.snapshot(job, base_api=base_api, include_official_sources=False)


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
