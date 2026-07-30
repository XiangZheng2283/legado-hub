"""Private cookie auth for Qidian (qidian_com_web).

Implements CookieAuthContract:
  - parse_cookie_text(cookie_text)
  - verify_cookies(cookie_jar)
  - normalize_cookies(cookie_jar)
"""

from __future__ import annotations

import re


# Critical login markers for Web login
_LOGIN_MARKERS = {
    "ywguid": "用户 GUID",
    "ywkey": "登录密钥",
    "ywopenid": "阅文 OpenID",
    "_csrfToken": "CSRF Token",
}

_CRITICAL_FIELDS = ("ywguid", "ywkey")


def parse_cookie_text(cookie_text: str) -> dict[str, dict[str, str]]:
    """Parse raw cookie text into domain-keyed jar.

    Supports multiple formats:
    - Semicolon-separated key=value pairs
    - JSON object
    - Netscape cookie format
    """
    jar: dict[str, dict[str, str]] = {}
    cookie_text = cookie_text.strip()

    if not cookie_text:
        return jar

    # Try JSON first
    if cookie_text.startswith("{"):
        import json
        try:
            data = json.loads(cookie_text)
            if isinstance(data, dict):
                # Check if it's already domain-keyed
                first_val = next(iter(data.values())) if data else None
                if isinstance(first_val, dict):
                    return {k: dict(v) for k, v in data.items() if isinstance(v, dict)}
                # Flat format: assume single domain
                jar["qidian.com"] = {k: str(v) for k, v in data.items() if v}
                return jar
        except Exception:
            pass

    # Parse key=value pairs
    pairs = re.findall(r'([^=;\s,]+)\s*=\s*([^;,\n]*)', cookie_text)
    if pairs:
        jar["qidian.com"] = {}
        for key, value in pairs:
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value:
                jar["qidian.com"][key] = value

    # If yuewen.com cookies found separately, normalize
    return normalize_cookies(jar)


def verify_cookies(cookie_jar: dict[str, dict[str, str]]) -> dict:
    """Verify cookies are valid for Qidian login.

    Returns:
        {
            "authenticated": bool,
            "accountName": str,
            "message": str,
        }
    """
    # Flatten all domains
    all_cookies: dict[str, str] = {}
    for domain, cookies in cookie_jar.items():
        if isinstance(cookies, dict):
            all_cookies.update(cookies)

    if not all_cookies:
        return {
            "authenticated": False,
            "accountName": "",
            "message": "未检测到 Cookie",
        }

    # Check critical fields
    found = {k: _LOGIN_MARKERS[k] for k in _LOGIN_MARKERS if all_cookies.get(k)}
    has_critical = all(all_cookies.get(k) for k in _CRITICAL_FIELDS)

    if not has_critical:
        return {
            "authenticated": False,
            "accountName": "",
            "message": "Cookie 不完整，缺少关键登录态字段（ywguid / ywkey）",
        }

    account_name = _explicit_account_name(all_cookies)
    marker_names = ", ".join(found.keys())
    if account_name:
        return {
            "authenticated": True,
            "accountName": account_name,
            "message": f"Cookie 有效（{marker_names}）",
        }

    return {
        "authenticated": False,
        "authStatus": "pending",
        "accountName": "",
        "message": f"Cookie 结构有效（{marker_names}），需账户页确认用户名或手机号",
    }


def _explicit_account_name(all_cookies: dict[str, str]) -> str:
    """Return explicit account identity if the pasted cookie payload carries it."""
    for key in ("nickName", "userName", "accountName"):
        value = str(all_cookies.get(key, "") or "").strip()
        if value:
            return value
    for key in (
        "mobilePhone",
        "mobile",
        "phone",
        "bindPhone",
        "phoneNumber",
        "phoneMasked",
        "mobileMasked",
    ):
        value = str(all_cookies.get(key, "") or "").strip()
        if re.fullmatch(r"1[3-9]\d{9}|1[3-9]\d\*{4}\d{4}", value):
            return value
    return ""


def normalize_cookies(cookie_jar: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """Normalize cookie jar to standard domain-keyed format.

    - Copy qidian.com cookies to yuewen.com and vice versa for shared fields
    - Ensure all critical fields exist in both domains
    """
    normalized: dict[str, dict[str, str]] = {}

    for domain, cookies in cookie_jar.items():
        if isinstance(cookies, dict):
            normalized[domain] = dict(cookies)

    # Shared fields that should exist in both domains
    shared_keys = {"ywguid", "ywkey", "ywopenid", "_csrfToken", "QDInfo", "fu", "alk"}

    # Collect all shared values
    shared_values: dict[str, str] = {}
    for domain, cookies in normalized.items():
        for key in shared_keys:
            if key in cookies:
                shared_values[key] = cookies[key]

    # Ensure both domains have shared fields
    for domain in ("qidian.com", "yuewen.com"):
        if domain not in normalized:
            normalized[domain] = {}
        for key, value in shared_values.items():
            if key not in normalized[domain]:
                normalized[domain][key] = value

    return normalized
