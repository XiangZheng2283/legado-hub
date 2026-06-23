"""User auth APIs for subscription/library/admin pages.

Copyright (c) 2026 moo. All rights reserved.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.services.user_auth import auth_service

router = APIRouter(prefix="/api/auth")


@router.post("/bootstrap")
def bootstrap_admin(payload: dict, response: Response):
    user = auth_service.bootstrap_admin(
        username=str(payload.get("username", "")).strip(),
        password=str(payload.get("password", "")),
    )
    auth_user = auth_service.authenticate(user["username"], str(payload.get("password", "")))
    session_id = auth_service.create_session(auth_user)
    auth_service.set_session_cookie(response, session_id)
    return {"ok": True, "user": user}


@router.post("/login")
def login(payload: dict, response: Response):
    user = auth_service.authenticate(
        username=str(payload.get("username", "")).strip(),
        password=str(payload.get("password", "")),
    )
    session_id = auth_service.create_session(user)
    auth_service.set_session_cookie(response, session_id)
    return {
        "ok": True,
        "user": {
            "userId": user.user_id,
            "username": user.username,
            "role": user.role,
            "disabled": user.disabled,
        },
    }


@router.post("/logout")
def logout(request: Request, response: Response):
    session_id = request.cookies.get("legadohub_session", "")
    auth_service.destroy_session(session_id)
    auth_service.clear_session_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    user = auth_service.current_user(request)
    if not user:
        return {"authenticated": False, "user": None}
    return {
        "authenticated": True,
        "user": {
            "userId": user.user_id,
            "username": user.username,
            "role": user.role,
            "disabled": user.disabled,
        },
    }
