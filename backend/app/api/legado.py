"""Legado-facing endpoints for shared library book/toc/chapter access.

The old aggregate search/explore/source endpoints were removed; only the
book reader contract remains, backed by the shared library storage.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.services.catalog import Catalog

router = APIRouter(prefix="/api/legado")


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
