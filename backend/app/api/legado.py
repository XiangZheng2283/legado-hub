"""Legado-facing endpoints for shared library book/toc/chapter access.

The old aggregate search/explore/source endpoints were removed; only the
book reader contract remains, backed by the shared library storage.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.services.catalog import Catalog
from app.services.library_books import library_books_service
from app.services.aggregate_virtual_source import VIRTUAL_SOURCE_ID
from app.source_plugins.id_codec import decode_chapter_id
from app.services.reading_reviews import (
    chapter_review_cache,
    render_chapter_reviews_html,
)
from app.services.user_auth import auth_service
from app.core.public_security import get_public_base_url
from app.services.reading_limits import reading_access_limiter

router = APIRouter(prefix="/api/legado")
_EXTERNAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+:[A-Za-z0-9_-]+$")
_MAX_EXTERNAL_ID_LENGTH = 8192
_MAX_NUMERIC_ID = 2**63 - 1


def _validated_external_id(value: str, *, label: str) -> str:
    normalized = str(value or "")
    if (
        not normalized
        or len(normalized) > _MAX_EXTERNAL_ID_LENGTH
        or not _EXTERNAL_ID_PATTERN.fullmatch(normalized)
    ):
        raise HTTPException(status_code=404, detail=f"{label}不存在")
    return normalized


def _reject_query_anomalies(request: Request, allowed: set[str]) -> None:
    unknown = set(request.query_params.keys()) - allowed
    repeated = {key for key in allowed if len(request.query_params.getlist(key)) > 1}
    if unknown or repeated:
        raise HTTPException(status_code=422, detail="查询参数无效")


def _query_int(
    value: str | None,
    *,
    field: str,
    minimum: int,
    maximum: int,
    default: int | None = None,
) -> int | None:
    if value is None or value == "":
        return default
    if not value.isascii() or not value.isdigit():
        if not (minimum < 0 and value.startswith("-") and value[1:].isascii() and value[1:].isdigit()):
            raise HTTPException(status_code=422, detail=f"{field} 必须是整数")
    parsed = int(value)
    if not minimum <= parsed <= maximum:
        raise HTTPException(status_code=422, detail=f"{field} 超出允许范围")
    return parsed


def _require_virtual_chapter(chapter_id: str) -> None:
    try:
        source_id, _ = decode_chapter_id(chapter_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="章节不存在") from exc
    if source_id != VIRTUAL_SOURCE_ID:
        raise HTTPException(status_code=404, detail="章节不存在")


async def _chapter_reviews(chapter_id: str) -> dict:
    cached = chapter_review_cache.get(chapter_id)
    if cached is not None:
        return cached
    reviews = await Catalog().chapter_reviews(chapter_id)
    chapter_review_cache.set(chapter_id, reviews)
    return reviews


@router.get("/book/{book_id}")
async def get_book(request: Request, book_id: str) -> dict:
    user = auth_service.require_user(request, touch=False)
    _reject_query_anomalies(request, set())
    book_id = _validated_external_id(book_id, label="书籍")
    if not library_books_service.is_virtual_book_id(book_id):
        raise HTTPException(status_code=404, detail="书籍不存在")
    with reading_access_limiter.guard(user.user_id, "metadata"):
        base_api = get_public_base_url(request)
        shared = library_books_service.legado_book_detail(book_id, base_api=base_api)
        if shared is not None:
            return shared
    raise HTTPException(status_code=404, detail="书籍尚未发布")


@router.get("/book/{book_id}/toc")
async def get_toc(request: Request, book_id: str) -> dict:
    user = auth_service.require_user(request, touch=False)
    _reject_query_anomalies(request, set())
    book_id = _validated_external_id(book_id, label="书籍")
    if not library_books_service.is_virtual_book_id(book_id):
        raise HTTPException(status_code=404, detail="书籍不存在")
    with reading_access_limiter.guard(user.user_id, "metadata"):
        base_api = get_public_base_url(request)
        shared = library_books_service.legado_toc(book_id, base_api=base_api)
        if shared is not None:
            return shared
    raise HTTPException(status_code=404, detail="书籍尚未发布")


@router.get("/chapter/{chapter_id}")
async def get_chapter(request: Request, chapter_id: str) -> dict:
    user = auth_service.require_user(request, touch=False)
    _reject_query_anomalies(request, set())
    chapter_id = _validated_external_id(chapter_id, label="章节")
    _require_virtual_chapter(chapter_id)
    with reading_access_limiter.guard(user.user_id, "chapter"):
        shared = library_books_service.legado_chapter(chapter_id)
        if shared is None:
            raise HTTPException(status_code=404, detail="章节尚未发布")
        return shared


@router.get("/chapter/{chapter_id}/reviews")
async def get_chapter_reviews(request: Request, chapter_id: str) -> dict:
    user = auth_service.require_user(request, touch=False)
    _reject_query_anomalies(request, set())
    chapter_id = _validated_external_id(chapter_id, label="章节")
    _require_virtual_chapter(chapter_id)
    with reading_access_limiter.guard(user.user_id, "reviews"):
        if library_books_service.legado_chapter(chapter_id) is None:
            raise HTTPException(status_code=404, detail="章节尚未发布")
        return await _chapter_reviews(chapter_id)


@router.get("/chapter/{chapter_id}/reviews/view", response_class=HTMLResponse)
async def get_chapter_review_view(
    request: Request,
    chapter_id: str,
    tab: str = "chapter",
    paragraphId: str | None = None,
    paragraphIds: str | None = None,
    rootReviewId: str | None = None,
    page: str = "1",
    pageSize: str = "10",
    cursorId: str = "0",
) -> HTMLResponse:
    user = auth_service.require_user(request, touch=False)
    _reject_query_anomalies(
        request,
        {"tab", "paragraphId", "paragraphIds", "rootReviewId", "page", "pageSize", "cursorId"},
    )
    chapter_id = _validated_external_id(chapter_id, label="章节")
    _require_virtual_chapter(chapter_id)
    if tab not in {"author", "chapter", "paragraph"}:
        raise HTTPException(status_code=422, detail="tab 无效")
    parsed_paragraph_id = _query_int(
        paragraphId, field="paragraphId", minimum=-1, maximum=_MAX_NUMERIC_ID
    )
    parsed_root_review_id = _query_int(
        rootReviewId, field="rootReviewId", minimum=1, maximum=_MAX_NUMERIC_ID
    )
    parsed_page = _query_int(page, field="page", minimum=1, maximum=1000, default=1) or 1
    page_size = _query_int(pageSize, field="pageSize", minimum=1, maximum=50, default=10) or 10
    cursor_id = _query_int(cursorId, field="cursorId", minimum=0, maximum=_MAX_NUMERIC_ID, default=0) or 0
    if paragraphIds is not None and (len(paragraphIds) > 1024 or any(ord(char) < 32 for char in paragraphIds)):
        raise HTTPException(status_code=422, detail="paragraphIds 无效")

    with reading_access_limiter.guard(user.user_id, "reviews"):
        chapter = library_books_service.legado_chapter(chapter_id)
        if chapter is None:
            raise HTTPException(status_code=404, detail="章节尚未发布")
        reviews = await _chapter_reviews(chapter_id)
        paragraph_detail = None
        page_hot_detail = None
        chapter_detail = None
        reply_detail = None
        catalog = Catalog()
        if parsed_root_review_id is not None:
            reply_detail = await catalog.review_replies(
                chapter_id,
                parsed_root_review_id,
                page=parsed_page,
                page_size=page_size,
                cursor_id=cursor_id,
            )
            tab = "paragraph"
        elif paragraphIds:
            try:
                parsed_ids = list(dict.fromkeys(
                    int(value.strip())
                    for value in paragraphIds.split(",")
                    if value.strip()
                ))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="paragraphIds 必须是逗号分隔的非负整数") from exc
            if (
                not parsed_ids
                or len(parsed_ids) > 50
                or any(value < 0 or value > _MAX_NUMERIC_ID for value in parsed_ids)
            ):
                raise HTTPException(status_code=422, detail="paragraphIds 数量或取值无效")
            page_hot_detail = await catalog.page_hot_reviews(
                chapter_id,
                parsed_ids,
                page=parsed_page,
                page_size=page_size,
            )
            tab = "paragraph"
        elif parsed_paragraph_id is not None:
            paragraph_detail = await catalog.paragraph_reviews(
                chapter_id,
                parsed_paragraph_id,
                page=parsed_page,
                page_size=page_size,
            )
            tab = "paragraph"
        elif tab == "chapter" and parsed_page > 1:
            chapter_detail = await catalog.chapter_say(
                chapter_id,
                page=parsed_page,
                page_size=page_size,
            )
        base_api = get_public_base_url(request)
        review_view_url = f"{base_api}/api/legado/chapter/{chapter_id}/reviews/view"
        return HTMLResponse(
            render_chapter_reviews_html(
                chapter_title=str(chapter.get("title") or "本章评论"),
                reviews=reviews,
                review_view_url=review_view_url,
                active_tab=tab,
                selected_paragraph_id=parsed_paragraph_id,
                paragraph_detail=paragraph_detail,
                page_hot_detail=page_hot_detail,
                chapter_detail=chapter_detail,
                reply_detail=reply_detail,
            ),
            headers={
                "X-Frame-Options": "SAMEORIGIN",
                "Content-Security-Policy": "frame-ancestors 'self'; base-uri 'self'; object-src 'none'",
            },
        )
