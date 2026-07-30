"""Private phone-login protocol for Qidian (qidian_com_web).

Implements AuthApiContract:
  - request_code(payload)  -> init + send SMS
  - verify_code(payload)   -> complete login with SMS code

The actual qidian-specific state machine lives in qidian_login_service.py,
which is loaded as a sibling module at runtime.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path


# ------------------------------------------------------------------
# Sibling module loader (private packages are loaded as standalone modules)
# ------------------------------------------------------------------

_SERVICE_MODULE_CACHE: str = "_qidian_com_web_private_login_service"


def _service():
    """Return the plugin-internal QidianLoginService singleton."""
    if _SERVICE_MODULE_CACHE in sys.modules:
        return sys.modules[_SERVICE_MODULE_CACHE].qidian_login_service

    module_path = Path(__file__).with_name("qidian_login_service.py")
    spec = importlib.util.spec_from_file_location(_SERVICE_MODULE_CACHE, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载 qidian_login_service.py")

    mod = importlib.util.module_from_spec(spec)
    sys.modules[_SERVICE_MODULE_CACHE] = mod
    spec.loader.exec_module(mod)
    return mod.qidian_login_service


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _mask_phone(phone: str) -> str:
    if len(phone) >= 7:
        return phone[:3] + "****" + phone[-4:]
    return phone


def _is_valid_phone(phone: str) -> bool:
    return bool(re.fullmatch(r"1[3-9]\d{9}", str(phone or "").strip()))


def _login_identity(account_name: str, phone: str) -> str:
    """Return only an explicit username or a valid login phone identity."""
    explicit_name = str(account_name or "").strip()
    if explicit_name:
        return explicit_name
    normalized_phone = str(phone or "").strip()
    return _mask_phone(normalized_phone) if _is_valid_phone(normalized_phone) else ""


def _build_challenge(session) -> dict:
    """Build a frontend-compatible challenge dict from a QidianLoginSession."""
    return {
        "type": "tencent_captcha",
        "appId": session.captcha_app_id or "1600000770",
        "captchaUrl": session.captcha_url,
        "captchaType": session.captcha_type,
        "url": session.captcha_url,
    }


def _map_init_result(session) -> dict:
    if session.status == "failed":
        return {"ok": False, "error": session.message}
    if session.status == "sms_sent":
        return {
            "ok": True,
            "sessionId": session.session_id,
            "nextAction": "verify_code",
        }
    return {
        "ok": False,
        "sessionId": session.session_id,
        "nextAction": "complete_challenge",
        "challenge": _build_challenge(session),
    }


def _map_send_result(session) -> dict:
    if session.status == "sms_sent":
        return {
            "ok": True,
            "sessionId": session.session_id,
            "nextAction": "verify_code",
        }
    return {
        "ok": False,
        "sessionId": session.session_id,
        "nextAction": "complete_challenge",
        "error": session.message,
        "errorCode": session.error_code,
        "challenge": _build_challenge(session),
    }


# ------------------------------------------------------------------
# Public contract methods
# ------------------------------------------------------------------

def request_code(payload: dict) -> dict:
    """Request SMS verification code.

    Returns:
        {
            "ok": bool,
            "sessionId": str,
            "nextAction": "verify_code" | "complete_challenge",
            "challenge": {...}   # only when nextAction == "complete_challenge"
        }
    """
    phone = str(payload.get("phone", "")).strip()
    challenge_token = payload.get("challengeToken", "")
    challenge_randstr = payload.get("challengeRandstr", "")
    existing_session_id = payload.get("sessionId", "")

    if not phone:
        return {"ok": False, "error": "缺少手机号"}
    if not _is_valid_phone(phone):
        return {"ok": False, "error": "手机号格式错误"}

    service = _service()

    # Retry after the user completed the slide captcha.
    if existing_session_id and challenge_token:
        session = service.send_sms(
            existing_session_id,
            phone,
            challenge_token,
            challenge_randstr,
        )
        return _map_send_result(session)

    # Fresh start: page config + getvalidatecodenew + prime sendmsgnew.
    session = service.init(phone)
    return _map_init_result(session)


def verify_code(payload: dict) -> dict:
    """Verify SMS code and complete login.

    Returns:
        {
            "ok": bool,
            "authenticated": bool,
            "accountName": str,
            "cookies": dict,
            "message": str,
        }
    """
    session_id = payload.get("sessionId", "")
    phone = payload.get("phone", "")
    sms_code = payload.get("code", "")

    service = _service()
    session = service.submit(session_id, sms_code)

    if session.status == "failed":
        return {
            "ok": False,
            "authenticated": False,
            "message": session.message,
        }

    cookies = session.cookies or {}
    account_name = _login_identity(session.account_name, phone)
    service.cleanup(session_id)

    if not account_name:
        return {
            "ok": True,
            "authenticated": False,
            "authStatus": "pending",
            "accountName": "",
            "cookies": cookies,
            "message": "登录态已保存，但未返回用户名或登录手机号",
        }

    return {
        "ok": True,
        "authenticated": True,
        "authStatus": "authenticated",
        "accountName": account_name,
        "cookies": cookies,
        "message": "登录成功",
    }
