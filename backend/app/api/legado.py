"""Legado-facing endpoints for shared library book/toc/chapter access.

The old aggregate search/explore/source endpoints were removed; only the
book reader contract remains, backed by the shared library storage.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.services.catalog import Catalog
from app.services.library_books import library_books_service
from app.services.aggregate_virtual_source import VIRTUAL_SOURCE_ID
from app.source_plugins.id_codec import decode_chapter_id

router = APIRouter(prefix="/api/legado")


@router.get("/book/{book_id}")
async def get_book(request: Request, book_id: str) -> dict:
    base_api = str(request.base_url).rstrip("/")
    shared = library_books_service.legado_book_detail(book_id, base_api=base_api)
    if shared is not None:
        return shared
    if library_books_service.is_virtual_book_id(book_id):
        raise HTTPException(status_code=404, detail="书籍尚未发布")
    catalog = Catalog(base_api=str(request.base_url).rstrip("/"))
    return await catalog.book_detail(book_id)


@router.get("/book/{book_id}/toc")
async def get_toc(request: Request, book_id: str) -> dict:
    base_api = str(request.base_url).rstrip("/")
    shared = library_books_service.legado_toc(book_id, base_api=base_api)
    if shared is not None:
        return shared
    if library_books_service.is_virtual_book_id(book_id):
        raise HTTPException(status_code=404, detail="书籍尚未发布")
    catalog = Catalog(base_api=str(request.base_url).rstrip("/"))
    return await catalog.toc(book_id)


@router.get("/chapter/{chapter_id}")
async def get_chapter(chapter_id: str) -> dict:
    try:
        source_id, _ = decode_chapter_id(chapter_id)
    except Exception:
        source_id = ""
    if source_id == VIRTUAL_SOURCE_ID:
        shared = library_books_service.legado_chapter(chapter_id)
        if shared is None:
            raise HTTPException(status_code=404, detail="章节尚未发布")
        return shared
    catalog = Catalog()
    return await catalog.chapter(chapter_id)


@router.get("/chapter/{chapter_id}/reviews")
async def get_chapter_reviews(chapter_id: str) -> dict:
    try:
        source_id, _ = decode_chapter_id(chapter_id)
    except Exception:
        source_id = ""
    if source_id == VIRTUAL_SOURCE_ID:
        return {
            "paragraphs": {},
            "chapterEnd": [],
            "summary": {"totalParagraphs": 0, "totalReviews": 0, "chapterEndCount": 0},
        }
    catalog = Catalog()
    return await catalog.chapter_reviews(chapter_id)
