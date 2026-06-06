"""Legado-facing endpoints for source JSON and API contract."""

from fastapi import APIRouter, Request

from app.core.source_generator import generate_aggregate_source
from app.services.catalog import Catalog

router = APIRouter(prefix="/api/legado")


@router.get("/source")
def get_source(request: Request) -> list[dict]:
    base_api = str(request.base_url).rstrip("/")
    return generate_aggregate_source(base_api)


@router.get("/search")
async def search(keyword: str = "", page: int = 1) -> dict:
    catalog = Catalog()
    return await catalog.search(keyword, page)


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
