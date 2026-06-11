"""Health and metadata endpoints."""

from fastapi import APIRouter

from app.config import get_app_info

router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/api/info")
def api_info() -> dict:
    return get_app_info()


