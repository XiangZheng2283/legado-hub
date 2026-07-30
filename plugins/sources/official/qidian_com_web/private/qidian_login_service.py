"""Qidian phone-login service (internal to the qidian_com_web plugin).

Backend handles API calls; frontend renders Tencent captcha slide.
Flow:
  1. init    -> GET passport.qidian.com, getvalidatecodenew
  2. sendSms -> POST with ticket from frontend captcha
  3. submit  -> POST with SMS code, get cookies

This module is intentionally qidian-specific and lives inside the plugin's
private package. The generic legado-hub auth manager only sees the
AuthApiContract implemented by auth_api.py.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

import requests


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 26_4_2 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "FxiOS/121.0 Mobile/15E148 Safari/605.1.15"
)

PASSPORT_URL = "https://passport.qidian.com/"
BASE_API_URL = "https://ptlogin.yuewen.com"


def _default_user_agent() -> str:
    """Read default UA from scheduler config; fall back to built-in default.

    The plugin is loaded at:
        plugins/sources/official/qidian_com_web/private/qidian_login_service.py
    Project root is five levels above this file.
    """
    try:
        project_root = Path(__file__).resolve().parents[5]
        pool_path = project_root / "backend" / "config" / "source_pool.json"
        if pool_path.exists():
            data = json.loads(pool_path.read_text(encoding="utf-8"))
            ua = data.get("default_user_agent", "")
            if isinstance(ua, str) and ua.strip():
                return ua.strip()
    except Exception:
        pass
    return DEFAULT_USER_AGENT


class QidianLoginSession:
    """One login session for qidian_com_web (phone + captcha + SMS)."""

    def __init__(self):
        self.session_id = uuid.uuid4().hex[:16]
        self.created_at = time.time()
        self.http = self._new_http_session()
        self.config: dict[str, Any] = {}
        self.base_data: dict[str, Any] = {}
        self.code_key = ""          # from getvalidatecodenew
        self.session_key = ""       # from sendmsgnew (for login)
        self.captcha_app_id = "1600000770"
        self.captcha_type = 0       # 0=old, 1=new TencentCaptcha
        self.captcha_url = ""       # full URL for captcha JS/iframe
        self.phone = ""
        self.status = "init"        # init | captcha | sms_sent | success | failed
        self.message = ""
        self.error_code: int | None = None
        self.account_name = ""      # populated on successful submit
        self.cookies: dict[str, dict[str, str]] = {}

    @staticmethod
    def _new_http_session() -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": _default_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://passport.qidian.com/",
        })
        return s

    def expired(self) -> bool:
        return time.time() - self.created_at > 600  # 10 min


class QidianLoginService:
    """Plugin-internal service managing qidian phone-login sessions."""

    def __init__(self):
        self._sessions: dict[str, QidianLoginSession] = {}

    # ------------------------------------------------------------------
    # Public flow
    # ------------------------------------------------------------------

    def init(self, phone: str = "") -> QidianLoginSession:
        """Step 1: fetch page params + getvalidatecodenew + prime sendmsgnew.

        We must call sendmsgnew once without a ticket to exchange the temporary
        codeKey for the real sessionKey and confirm the actual server-required
        flow before sending the SMS code.

        If the server returns `needValidateCode=false`, we still do NOT return
        early. We must prime `sendmsgnew` once and inspect `nextAction`:
        - `0`  -> SMS already sent, no slide captcha required
        - `11` -> Tencent slide captcha still required
        """
        session = QidianLoginSession()

        # 1a. Load passport page to extract init params
        page_cfg = self._fetch_page_config(session.http)
        session.config = page_cfg
        session.base_data = self._build_base_data(page_cfg)

        # 1b. Call getvalidatecodenew to get codeKey & captcha info
        result = self._api_getvalidatecodenew(session.http, session.base_data)
        data = result.get("data", {})
        session.code_key = data.get("sessionKey", "")

        if result.get("code") != 0:
            session.status = "failed"
            session.message = result.get("message", "初始化登录失败")
            return session

        img_src = data.get("imgSrc", "")
        if img_src.startswith("tencentCode;"):
            session.captcha_url = img_src[12:]
            session.captcha_type = 1 if "TCaptcha.js" in session.captcha_url else 0
        elif img_src:
            session.captcha_url = img_src
            session.captcha_type = 0

        # 1c. Prime sendmsgnew to obtain the real sessionKey and determine
        # whether the server will allow SMS directly or still requires the
        # Tencent slide captcha challenge.
        # The frontend phone number may not be known yet; use a placeholder if needed.
        prime_phone = phone or "13800138000"
        prime_result = self._api_sendmsgnew(
            session.http, session.base_data, session.code_key, prime_phone, "", ""
        )
        prime_data = prime_result.get("data", {})
        if prime_result.get("code") != 0:
            session.status = "failed"
            session.message = prime_result.get("message", "请求验证码失败")
            return session

        next_action = prime_data.get("nextAction")
        real_session_key = prime_data.get("sessionKey", "")
        # If the server explicitly allows direct SMS sending, transition
        # straight to sms_sent. This keeps the no-slide path available without
        # assuming it before sendmsgnew confirms it.
        if next_action == 0 and real_session_key:
            session.session_key = real_session_key
            session.status = "sms_sent"
            session.message = "短信验证码已发送"
            self._sessions[session.session_id] = session
            return session

        # Otherwise store the real sessionKey to be used after the user
        # completes the slide challenge.
        session.session_key = real_session_key
        session.status = "captcha"
        session.message = "需要完成滑块验证"

        self._sessions[session.session_id] = session
        return session

    def send_sms(
        self,
        session_id: str,
        phone: str,
        ticket: str,
        randstr: str,
    ) -> QidianLoginSession:
        """Step 2: call sendmsgnew with captcha ticket using the real sessionKey."""
        session = self._get_session(session_id)
        session.phone = phone

        if not session.session_key:
            session.status = "failed"
            session.message = "会话未准备好，请重新获取验证码"
            return session

        result = self._api_sendmsgnew(
            session.http,
            session.base_data,
            session.session_key,
            phone,
            ticket=ticket,
            randstr=randstr,
        )
        data = result.get("data") or {}
        next_action = data.get("nextAction", 0)
        real_session_key = data.get("sessionKey", "")

        # Qidian sometimes returns a non-zero code while still sending the SMS.
        # Treat it as success if we got a real sessionKey and the server is no
        # longer asking for a captcha (nextAction != 11).
        if real_session_key and next_action != 11:
            session.session_key = real_session_key
            session.status = "sms_sent"
            session.message = "短信验证码已发送"
            return session

        if next_action == 11:
            # Still asking for slide captcha -> ticket invalid / not provided
            session.status = "failed"
            session.message = "滑块验证未通过，请重新完成滑块"
            session.error_code = result.get("code")
            return session

        session.status = "failed"
        session.message = result.get("message") or "发送短信失败"
        session.error_code = result.get("code")
        return session

    def submit(self, session_id: str, sms_code: str) -> QidianLoginSession:
        """Step 3: call phonecodelogin and extract cookies."""
        session = self._get_session(session_id)

        result = self._api_phonecodelogin(
            session.http,
            session.base_data,
            session.session_key,
            session.phone,
            sms_code,
        )
        data = result.get("data", {})

        if result.get("code") != 0:
            session.status = "failed"
            session.message = result.get("message", "登录失败")
            return session

        # Extract cookies from response body and from the session cookie jar
        # (login markers may be returned via Set-Cookie headers).
        session.cookies = self._extract_cookies_from_response(result, session.http)
        session.status = "success"
        session.message = "登录成功"

        user_info = data.get("userInfo") if isinstance(data.get("userInfo"), dict) else {}
        session.account_name = (
            user_info.get("nickName")
            or user_info.get("userName")
            or ""
        )

        return session

    def get_session(self, session_id: str) -> QidianLoginSession | None:
        return self._sessions.get(session_id)

    def cleanup(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_session(self, session_id: str) -> QidianLoginSession:
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        if session.expired():
            self._sessions.pop(session_id, None)
            raise ValueError(f"Session {session_id} expired")
        return session

    # -- HTTP helpers --

    def _jsonp_parse(self, text: str) -> dict:
        m = re.search(r"\((.*)\)\s*$", text, re.S)
        if not m:
            try:
                return json.loads(text)
            except Exception:
                return {"raw": text[:500]}
        try:
            return json.loads(m.group(1))
        except Exception:
            return {"raw": text[:500]}

    # -- Step 1a: page config --

    def _fetch_page_config(self, http: requests.Session) -> dict:
        r = http.get(PASSPORT_URL, timeout=15)
        html = r.text

        m = re.search(r"LoginV1\.init\s*\(\s*(\{[\s\S]*?\})\s*\)", html)
        if not m:
            return {}

        params_str = m.group(1)
        params_str = re.sub(r",\s*\}", "}", params_str)
        params_str = re.sub(r",\s*\]", "]", params_str)
        params_str = params_str.replace("'", '"')
        try:
            return json.loads(params_str)
        except Exception:
            return {}

    def _build_base_data(self, cfg: dict) -> dict:
        return {
            "appId": cfg.get("appId", 10),
            "areaId": cfg.get("areaId", 1),
            "source": cfg.get("source", ""),
            "returnurl": cfg.get("returnUrl", "http://www.qidian.com"),
            "version": cfg.get("version", ""),
            "imei": cfg.get("imei", ""),
            "qimei": cfg.get("qimei", ""),
            "target": cfg.get("target", "top"),
            "ticket": cfg.get("ticket", 0),
            "autotime": cfg.get("autoTime", 14),
            "jumpdm": cfg.get("jumpdm", "qidian"),
            "ajaxdm": cfg.get("ajaxdm", ""),
            "auto": cfg.get("autoLoginFlag", 0),
            "sdkversion": cfg.get("sdkversion", ""),
        }

    # -- Step 1b: getvalidatecodenew --

    def _api_getvalidatecodenew(self, http: requests.Session, base_data: dict) -> dict:
        params = {
            **base_data,
            "force": 1,
            "method": "LoginV1.getCaptchaCallback",
            "format": "jsonp",
        }
        r = http.get(f"{BASE_API_URL}/userSdk/getvalidatecodenew", params=params, timeout=15)
        return self._jsonp_parse(r.text)

    # -- Step 2: sendmsgnew --

    def _api_sendmsgnew(
        self,
        http: requests.Session,
        base_data: dict,
        code_key: str,
        phone: str,
        ticket: str = "",
        randstr: str = "",
    ) -> dict:
        # Tencent slide-captcha flow: combine randstr + ticket into validateCode
        # and use the slide-specific callback, matching Qidian's login.js.
        if ticket and randstr:
            params = {
                **base_data,
                "phoneIsAbroad": 0,
                "inputUserId": f"+86{phone}",
                "mobilePhone": phone,
                "sessionKey": code_key,
                "type": 1,
                "validateCode": f"{randstr};{ticket}",
                "needRegister": 0,
                "method": "LoginV1.slidePhoneSendMsgByCodeLoginCallback",
                "format": "jsonp",
            }
        else:
            # First attempt without captcha ticket; server replies with nextAction=11
            params = {
                **base_data,
                "phoneIsAbroad": 0,
                "inputUserId": f"+86{phone}",
                "mobilePhone": phone,
                "sessionKey": code_key,
                "type": 1,
                "validateCode": "",
                "needRegister": 0,
                "method": "LoginV1.phoneSendMsgCallback",
                "format": "jsonp",
            }

        r = http.get(f"{BASE_API_URL}/userSdk/sendmsgnew", params=params, timeout=15)
        return self._jsonp_parse(r.text)

    # -- Step 3: phonecodelogin --

    def _api_phonecodelogin(
        self,
        http: requests.Session,
        base_data: dict,
        session_key: str,
        phone: str,
        sms_code: str,
    ) -> dict:
        params = {
            **base_data,
            "inputUserId": phone,
            "sessionKey": session_key,
            "validateCode": sms_code,
            "method": "LoginV1.phoneCodeLoginCallback",
            "format": "jsonp",
        }
        r = http.get(f"{BASE_API_URL}/userSdk/phonecodelogin", params=params, timeout=15)
        return self._jsonp_parse(r.text)

    # -- Cookie extraction --

    def _extract_cookies_from_response(
        self, result: dict, http: requests.Session | None = None
    ) -> dict[str, dict[str, str]]:
        """Login API returns cookie-like fields in data; we normalize them.

        Also copies login markers from the session cookie jar, because some
        responses set ywguid/ywkey via Set-Cookie headers rather than the JSON body.
        """
        data = result.get("data", {})
        cookies: dict[str, dict[str, str]] = {}

        # Common login-state fields returned by Yuewen login APIs
        fields = {
            "ywGuid": "ywguid",
            "ywKey": "ywkey",
            "ywOpenId": "ywopenid",
            "ticket": "ticket",
            "autoLoginSessionKey": "autoLoginSessionKey",
            "contextId": "contextId",
            # Some responses use lower-cased field names.
            "ywguid": "ywguid",
            "ywkey": "ywkey",
            "ywopenid": "ywopenid",
        }

        for api_name, cookie_name in fields.items():
            value = data.get(api_name)
            if value:
                # Store under both qidian.com and yuewen.com domains
                for domain in ("qidian.com", "yuewen.com"):
                    cookies.setdefault(domain, {})[cookie_name] = str(value)

        # Copy all cookies from the requests session jar so we don't miss any
        # login markers Qidian may set under different names or domains.
        if http is not None:
            target_domains = (
                "qidian.com",
                "m.qidian.com",
                "www.qidian.com",
                "yuewen.com",
                "ptlogin.yuewen.com",
                "ptlogin.qidian.com",
            )
            for cookie in http.cookies:
                domain = cookie.domain.lstrip(".") if cookie.domain else ""
                matched_domain = next(
                    (d for d in target_domains if domain == d or domain.endswith("." + d)), ""
                )
                if matched_domain:
                    cookies.setdefault(matched_domain, {})[cookie.name] = cookie.value
                # Also normalize shared login markers under the canonical domains.
                if cookie.name in ("ywguid", "ywkey", "ywopenid", "_csrfToken"):
                    for canonical in ("qidian.com", "yuewen.com"):
                        cookies.setdefault(canonical, {})[cookie.name] = cookie.value

        return cookies


# Global singleton
qidian_login_service = QidianLoginService()
