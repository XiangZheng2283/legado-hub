"""Unified Browser Bridge API endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.services.browser_challenge import BrowserChallengeService
from app.services.browser_helper import BrowserHelperService

router = APIRouter(prefix="/api/browser")

_browser_challenge_service = BrowserChallengeService()
_browser_helper_service = BrowserHelperService()


@router.get("/challenges")
def list_browser_challenges(sourceId: str = "") -> dict:
    return {"items": _browser_challenge_service.list(source_id=sourceId or None)}


@router.get("/challenges/{session_id}")
def get_browser_challenge(session_id: str) -> dict:
    session = _browser_challenge_service.get(session_id)
    if not session:
        return {"error": "验证会话不存在", "sessionId": session_id}
    return session


@router.get("/challenges/{session_id}/open", response_class=HTMLResponse)
def open_browser_challenge(session_id: str, mode: str = "auto") -> str:
    session = _browser_challenge_service.get(session_id)
    if not session:
        return _html_page("Browser Challenge", f"验证会话不存在：{session_id}")
    result = _browser_helper_service.start(session)
    if result.get("started"):
        _browser_challenge_service.record_browser_helper(session_id, result)
        message = "已启动浏览器验证窗口。完成验证后可回到控制台导入 Cookie，或等待后续 Browserless callback。"
    else:
        message = (
            "无法自动启动浏览器验证窗口。请打开真实验证地址完成验证后提交 Cookie。"
            f"<pre>{result.get('error', '')}</pre>"
        )
    return _html_page(
        "Browser Challenge",
        (
            f"<p>Session: <code>{session_id}</code></p>"
            f"<p>Mode: <code>{mode}</code></p>"
            f"<p>Source: <code>{session.get('sourceId', '')}</code></p>"
            f"<p>Open URL: <a href=\"{session.get('openUrl', '')}\">{session.get('openUrl', '')}</a></p>"
            f"<p>{message}</p>"
        ),
    )


@router.post("/challenges/{session_id}/callback")
def browser_challenge_callback(session_id: str, payload: dict) -> dict:
    status = str(payload.get("status", "") or "")
    cookies = payload.get("cookies", [])
    if cookies:
        saved = _browser_challenge_service.submit_cookies(session_id, cookies)
    else:
        saved = {"saved": False, "sessionId": session_id, "status": status}
    if status == "verified":
        session = _browser_challenge_service.mark_verified(session_id, saved)
        saved["status"] = session.get("status", "verified")
    return saved


@router.post("/challenges/{session_id}/cookies")
def submit_browser_challenge_cookies(session_id: str, payload: dict) -> dict:
    return _browser_challenge_service.submit_cookies(session_id, payload.get("cookies", payload))


def _html_page(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head>"
        "<meta charset=\"utf-8\">"
        f"<title>{title}</title>"
        "</head><body>"
        f"<h1>{title}</h1>"
        f"{body}"
        "</body></html>"
    )
