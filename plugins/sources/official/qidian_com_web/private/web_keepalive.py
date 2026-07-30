"""Web-session keepalive for Qidian (qidian_com_web).

Refreshes the short-lived Web login credentials (``ywguid`` / ``ywkey`` /
``ticket``) from the long-lived ``alk`` cookie via ``ptlogin.yuewen.com``:

    alk (15d) ──checkStatus──► new ywguid / ywkey / ticket

This is a **pure Web protocol** module.  It does NOT touch the App layer
(QDSign, device fingerprint, cmfuToken, web→app exchange).  Those concerns
belong to the App plugin.

Design decisions (see ``reverse-engineering/docs/qidian-web-login-keepalive-flow.md``
§6 for the full rationale):

* **No sublogin step.**  The browser only loads the ``302url`` /
  ``returnUrl`` (sublogin) to materialise cookies in its own jar.  In the
  plugin we control the cookie jar directly, and the ``checkStatus`` JSON
  ``data`` block already carries ``ywGuid`` / ``ywKey`` / ``ticket`` /
  ``autoLoginSessionKey`` / ``ywOpenId``.  This was verified by
  ``reverse-engineering/scripts/qidian_qdsign/web_to_app_poc.py``, which
  skips sublogin entirely and yet obtains ``ywguid``/``ywkey`` good enough
  to exchange for an App ``cmfuToken``.
* **Lazy, event-driven.**  There is no scheduler.  ``refresh_web_session``
  is meant to be called from ``Source.auth_status`` whenever short-lived
  credentials look stale.
* ``alk`` lasts ~15 days and is NOT extended by checkStatus.  When the
  server reports ``code=10521`` (alk rejected) the session is unrecoverable
  without a fresh phone-code login.
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests


PTLOGIN_CHECKSTATUS = "https://ptlogin.yuewen.com/login/checkStatus"
PASSPORT_REFERER = "https://passport.qidian.com/"

# Domains that share the Qidian login markers.
_SHARED_DOMAINS = ("qidian.com", "yuewen.com")

# Fields written back into the cookie jar after a successful refresh.
_REFRESH_FIELDS = ("ywguid", "ywkey", "ywopenid", "ticket")

# Server result codes we recognise.
_CODE_OK = 0
_CODE_ALK_EXPIRED = 10521  # "登录失败，请稍后重试" — alk missing/expired/untrusted


def _flatten(cookie_jar: dict[str, dict[str, str]]) -> dict[str, str]:
    """Merge all domains into a single flat cookie dict (last write wins)."""
    flat: dict[str, str] = {}
    for cookies in (cookie_jar or {}).values():
        if isinstance(cookies, dict):
            for k, v in cookies.items():
                if v is not None and v != "":
                    flat[str(k)] = str(v)
    return flat


def _jsonp_parse(text: str) -> dict:
    """Parse a JSONP envelope ``cb({...})`` or plain JSON into a dict."""
    text = (text or "").strip()
    if not text:
        return {}
    m = re.search(r"\((.*)\)\s*$", text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            return {"raw": text[:500]}
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text[:500]}


def _build_checkstatus_params() -> dict[str, str]:
    """Fixed query parameters for the checkStatus endpoint."""
    return {
        "callback": "LoginV1.checkStatusCallback",
        "appId": "10",
        "areaId": "1",
        "source": "",
        "returnurl": "http://www.qidian.com",
        "version": "",
        "imei": "",
        "qimei": "",
        "target": "top",
        "ticket": "0",
        "autotime": "14",
        "jumpdm": "qidian",
        "ajaxdm": "",
        "auto": "0",
        "sdkversion": "",
        "method": "LoginV1.checkStatusCallback",
        "format": "jsonp",
        "_": "1",
    }


def refresh_web_session(
    cookie_jar: dict[str, dict[str, str]],
    *,
    timeout: int = 15,
) -> dict[str, Any]:
    """Refresh short-lived Web login credentials from the ``alk`` cookie.

    Args:
        cookie_jar: Domain-keyed cookie jar (same shape used by
            ``cookie_auth`` / ``cookie_store``).  **Mutated in place** when
            the refresh succeeds: the refreshed ``ywguid`` / ``ywkey`` /
            ``ticket`` / ``ywopenid`` are written to both ``qidian.com``
            and ``yuewen.com``.
        timeout: HTTP timeout in seconds.

    Returns:
        A result dict:

        * ``{"ok": True, "refreshed": True, "account": {...}}`` — success.
        * ``{"ok": False, "reason": "no_alk"}`` — nothing to refresh;
          the caller should keep using whatever short-lived creds it has.
        * ``{"ok": False, "reason": "alk_expired", "code": 10521,
          "message": ...}`` — ``alk`` is gone; the user must re-login.
        * ``{"ok": False, "reason": "network", "message": ...}`` —
          transport error; the caller should fall back to existing creds.
    """
    flat = _flatten(cookie_jar)
    alk = flat.get("alk")
    if not alk:
        return {"ok": False, "reason": "no_alk"}

    # Send whatever login markers we already have alongside alk.  The server
    # mainly relies on alk, but including ywguid/ywkey matches real traffic.
    send_cookies = {"alk": alk}
    for name in ("ywguid", "ywkey", "ywopenid", "ticket"):
        val = flat.get(name)
        if val:
            send_cookies[name] = val

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 26_4_2 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "FxiOS/121.0 Mobile/15E148 Safari/605.1.15"
        ),
        "Referer": PASSPORT_REFERER,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }

    try:
        resp = requests.get(
            PTLOGIN_CHECKSTATUS,
            params=_build_checkstatus_params(),
            cookies=send_cookies,
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        return {"ok": False, "reason": "network", "message": str(exc)}

    payload = _jsonp_parse(resp.text)
    code = payload.get("code")

    if code != _CODE_OK:
        # 10521 (and similar non-zero codes) mean alk was rejected.
        if code == _CODE_ALK_EXPIRED:
            return {
                "ok": False,
                "reason": "alk_expired",
                "code": code,
                "message": payload.get("message", "alk 已失效，需重新登录"),
            }
        # Unknown non-zero code — treat defensively as a soft failure so the
        # caller does not flip an authenticated session offline on a hiccup.
        return {
            "ok": False,
            "reason": "server",
            "code": code,
            "message": payload.get("message", f"checkStatus code={code}"),
        }

    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return {"ok": False, "reason": "server", "message": "checkStatus data empty"}

    # Extract refreshed credentials straight from the JSON data block.
    refreshed = {
        "ywguid": str(data.get("ywGuid") or data.get("ywguid") or ""),
        "ywkey": data.get("ywKey") or data.get("ywkey") or "",
        "ticket": data.get("ticket") or "",
        "ywopenid": data.get("ywOpenId") or data.get("ywopenid") or flat.get("ywopenid", ""),
        "alk": data.get("autoLoginSessionKey") or "",
    }
    # If the server returned a composite alk (autoLoginSessionKey|ywguid),
    # prefer it; otherwise rebuild it from the parts.
    if refreshed["alk"] and refreshed["ywguid"] and "|" not in refreshed["alk"]:
        refreshed["alk"] = f"{refreshed['alk']}|{refreshed['ywguid']}"

    # Write the refreshed markers back into the jar for both shared domains.
    # Preserve any pre-existing alk when the server did not return one.
    for domain in _SHARED_DOMAINS:
        bucket = cookie_jar.setdefault(domain, {})
        for name in _REFRESH_FIELDS:
            val = refreshed.get(name)
            if val:
                bucket[name] = val
        if refreshed["alk"]:
            bucket["alk"] = refreshed["alk"]
        elif "alk" not in bucket and alk:
            bucket["alk"] = alk

    return {
        "ok": True,
        "refreshed": True,
        "account": {
            "ywguid": refreshed["ywguid"],
            "ywkey": refreshed["ywkey"],
            "ticket": refreshed["ticket"],
        },
    }
