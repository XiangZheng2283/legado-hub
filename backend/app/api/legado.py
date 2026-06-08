"""Legado-facing endpoints for source JSON and API contract."""

import asyncio
import threading

from fastapi import APIRouter, Request

from app.core.source_generator import generate_aggregate_source
from app.services.browser_challenge import BrowserChallengeService
from app.services.browser_helper import BrowserHelperService
from app.services.catalog import Catalog
from app.services.live_acceptance import LiveAcceptanceService
from app.services.search_jobs import SearchJobService

router = APIRouter(prefix="/api/legado")
_search_service: SearchJobService | None = None
_search_service_init_token = None
_browser_challenge_service = BrowserChallengeService()
_browser_helper_service = BrowserHelperService()
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
async def search(keyword: str = "", page: int = 1, waitMs: int = 1200) -> dict:
    if not keyword.strip():
        return {"implemented": True, "keyword": keyword, "page": page, "items": [], "debug": {"sourceCount": 0}}
    search_service = _get_search_service()
    job = search_service.find_active_job(keyword, page)
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
        threading.Thread(target=_run_search_job_blocking, args=(search_service, job.job_id), daemon=True).start()
    deadline = asyncio.get_running_loop().time() + max(0, min(waitMs, 5000)) / 1000
    while asyncio.get_running_loop().time() < deadline:
        if job.candidate_groups or job.status in {"completed", "cancelled"} or job.browser_challenges:
            break
        await asyncio.sleep(0.1)
    return search_service.snapshot(job)


@router.post("/search/{job_id}/cancel")
async def cancel_search(job_id: str) -> dict:
    ok = _get_search_service().cancel_job(job_id)
    return {"jobId": job_id, "cancelled": ok}


@router.get("/explore")
async def explore(sourceId: str = "", groupId: str = "", page: int = 1) -> dict:
    catalog = Catalog()
    return await catalog.explore(source_id=sourceId, group_id=groupId, page=page)


@router.get("/book/{book_id}")
async def get_book(book_id: str) -> dict:
    catalog = Catalog()
    return await catalog.book_detail(book_id)


@router.get("/book/{book_id}/toc")
async def get_toc(book_id: str) -> dict:
    catalog = Catalog()
    return await catalog.toc(book_id)


@router.get("/chapter/{chapter_id}")
async def get_chapter(chapter_id: str) -> dict:
    catalog = Catalog()
    return await catalog.chapter(chapter_id)


@router.get("/browser-challenges")
def list_browser_challenges(sourceId: str = "") -> dict:
    return {"items": _browser_challenge_service.list(source_id=sourceId or None)}


@router.get("/browser-challenges/{session_id}")
def get_browser_challenge(session_id: str) -> dict:
    session = _browser_challenge_service.get(session_id)
    if not session:
        return {"error": "验证会话不存在", "sessionId": session_id}
    return session


@router.post("/browser-challenges/{session_id}/cookies")
def submit_browser_challenge_cookies(session_id: str, payload: dict) -> dict:
    return _browser_challenge_service.submit_cookies(session_id, payload.get("cookies", payload))


@router.post("/browser-challenges/{session_id}/browser/open")
def open_browser_challenge_browser(session_id: str) -> dict:
    session = _browser_challenge_service.get(session_id)
    if not session:
        return {"started": False, "error": "验证会话不存在", "sessionId": session_id}
    result = _browser_helper_service.start(session)
    if result.get("started"):
        _browser_challenge_service.record_browser_helper(session_id, result)
    return result


@router.get("/browser-challenges/{session_id}/browser/status")
def get_browser_challenge_browser_status(session_id: str) -> dict:
    return _browser_helper_service.status(session_id)


@router.post("/browser-challenges/{session_id}/browser/import-cookies")
def import_browser_challenge_browser_cookies(session_id: str) -> dict:
    cookies = _browser_helper_service.cookies(session_id)
    if not cookies:
        return {"saved": False, "error": "未找到浏览器助手 Cookie，请先完成验证或稍后重试", "sessionId": session_id}
    return _browser_challenge_service.submit_cookies(session_id, cookies)


@router.post("/browser-challenges/{session_id}/retry-live-check")
async def retry_browser_challenge_live_check(session_id: str, payload: dict | None = None) -> dict:
    session = _browser_challenge_service.get(session_id)
    if not session:
        return {"error": "验证会话不存在", "sessionId": session_id}
    payload = payload or {}
    result = await _live_acceptance_service.run_plugin_live_check(
        plugin_id=session["sourceId"],
        keyword=payload.get("keyword", "凡人修仙传"),
        candidate_index=int(payload.get("candidateIndex", 0) or 0),
        chapter_index=int(payload.get("chapterIndex", 0) or 0),
        persist=True,
    )
    return _browser_challenge_service.record_retry_result(session_id, result)
