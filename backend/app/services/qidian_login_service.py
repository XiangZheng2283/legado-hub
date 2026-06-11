"""Qidian phone-login service (方案B: 前端辅助滑块).

Backend handles API calls; frontend renders Tencent captcha slide.
Flow:
  1. init    -> GET passport.qidian.com, getvalidatecodenew
  2. sendSms -> POST with ticket from frontend captcha
  3. submit  -> POST with SMS code, get cookies
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

import requests


class QidianLoginSession:
    """One login session for qidian_com (phone + captcha + SMS)."""

    def __init__(self):
        self.session_id = uuid.uuid4().hex[:16]
        self.created_at = time.time()
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
        self.cookies: dict[str, dict[str, str]] = {}

    def expired(self) -> bool:
        return time.time() - self.created_at > 600  # 10 min


class QidianLoginService:
    """Global service managing qidian phone-login sessions."""

    PASSPORT_URL = "https://passport.qidian.com/"
    BASE_API_URL = "https://ptlogin.yuewen.com"

    def __init__(self):
        self._sessions: dict[str, QidianLoginSession] = {}

    # ------------------------------------------------------------------
    # Public flow
    # ------------------------------------------------------------------

    def init(self) -> QidianLoginSession:
        """Step 1: fetch page params + getvalidatecodenew."""
        session = QidianLoginSession()

        # 1a. Load passport page to extract init params
        page_cfg = self._fetch_page_config()
        session.config = page_cfg
        session.base_data = self._build_base_data(page_cfg)

        # 1b. Call getvalidatecodenew to get codeKey & captcha info
        result = self._api_getvalidatecodenew(session.base_data)
        data = result.get("data", {})
        session.code_key = data.get("sessionKey", "")

        img_src = data.get("imgSrc", "")
        if img_src.startswith("tencentCode;"):
            session.captcha_url = img_src[12:]
            session.captcha_type = 1 if "TCaptcha.js" in session.captcha_url else 0
        elif img_src:
            session.captcha_url = img_src
            session.captcha_type = 0

        need_validate = data.get("needValidateCode", True)
        if not need_validate and not img_src:
            # Rare: no captcha needed
            session.status = "captcha"
            session.message = "无需滑块验证，可直接发送短信"
        else:
            session.status = "captcha"
            session.message = "需要完成滑块验证"

        self._sessions[session.session_id] = session
        return session

    def send_sms(self, session_id: str, phone: str, ticket: str, randstr: str) -> QidianLoginSession:
        """Step 2: call sendmsgnew with captcha ticket."""
        session = self._get_session(session_id)
        session.phone = phone

        result = self._api_sendmsgnew(
            session.base_data,
            session.code_key,
            phone,
            ticket=ticket,
            randstr=randstr,
        )
        data = result.get("data", {})
        next_action = data.get("nextAction", 0)

        if next_action == 11:
            # Still asking for slide captcha -> ticket invalid / not provided
            session.status = "failed"
            session.message = "滑块验证未通过，请重新完成滑块"
            return session

        if result.get("code") != 0:
            session.status = "failed"
            session.message = result.get("message", "发送短信失败")
            return session

        session.session_key = data.get("sessionKey", "")
        session.status = "sms_sent"
        session.message = "短信验证码已发送"
        return session

    def submit(self, session_id: str, sms_code: str) -> QidianLoginSession:
        """Step 3: call phonecodelogin and extract cookies."""
        session = self._get_session(session_id)

        result = self._api_phonecodelogin(
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

        # Extract cookies from response headers
        session.cookies = self._extract_cookies_from_response(result)
        session.status = "success"
        session.message = "登录成功"
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

    def _http(self) -> requests.Session:
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        return s

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

    def _fetch_page_config(self) -> dict:
        s = self._http()
        r = s.get(self.PASSPORT_URL, timeout=15)
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

    def _api_getvalidatecodenew(self, base_data: dict) -> dict:
        s = self._http()
        params = {
            **base_data,
            "force": 1,
            "method": "LoginV1.getCaptchaCallback",
            "format": "jsonp",
        }
        r = s.get(f"{self.BASE_API_URL}/userSdk/getvalidatecodenew", params=params, timeout=15)
        return self._jsonp_parse(r.text)

    # -- Step 2: sendmsgnew --

    def _api_sendmsgnew(
        self,
        base_data: dict,
        code_key: str,
        phone: str,
        ticket: str = "",
        randstr: str = "",
    ) -> dict:
        s = self._http()
        params = {
            **base_data,
            "phoneIsAbroad": 0,
            "inputUserId": f"+86{phone}",
            "sessionKey": code_key,
            "type": 1,
            "validateCode": "",
            "needRegister": 0,
            "method": "LoginV1.phoneSendMsgCallback",
            "format": "jsonp",
        }
        if ticket:
            params["sig"] = ticket
        if randstr:
            params["code"] = randstr

        r = s.get(f"{self.BASE_API_URL}/userSdk/sendmsgnew", params=params, timeout=15)
        return self._jsonp_parse(r.text)

    # -- Step 3: phonecodelogin --

    def _api_phonecodelogin(
        self,
        base_data: dict,
        session_key: str,
        phone: str,
        sms_code: str,
    ) -> dict:
        s = self._http()
        params = {
            **base_data,
            "inputUserId": phone,
            "sessionKey": session_key,
            "validateCode": sms_code,
            "method": "LoginV1.phoneCodeLoginCallback",
            "format": "jsonp",
        }
        r = s.get(f"{self.BASE_API_URL}/userSdk/phonecodelogin", params=params, timeout=15)
        return self._jsonp_parse(r.text)

    # -- Cookie extraction --

    def _extract_cookies_from_response(self, result: dict) -> dict:
        """Login API returns cookie-like fields in data; we normalize them."""
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
        }

        for api_name, cookie_name in fields.items():
            value = data.get(api_name)
            if value:
                # Store under both qidian.com and yuewen.com domains
                for domain in ("qidian.com", "yuewen.com"):
                    cookies.setdefault(domain, {})[cookie_name] = str(value)

        # Also try to extract from the HTTP response if available
        # (JSONP doesn't expose Set-Cookie headers, so we rely on data fields)
        return cookies


# Global singleton
qidian_login_service = QidianLoginService()
