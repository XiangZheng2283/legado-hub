"""Health and metadata endpoints."""

from fastapi import APIRouter, Request

from app.config import get_app_info
from app.services.user_auth import auth_service

router = APIRouter()
public_router = APIRouter()


@router.get("/health")
@public_router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/api/info")
def api_info(request: Request) -> dict:
    auth_service.require_admin(request)
    info = get_app_info()
    return {key: info[key] for key in ("name", "version", "phase")}
