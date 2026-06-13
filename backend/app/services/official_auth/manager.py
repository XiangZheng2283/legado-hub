"""Official source login manager.

Routes login requests to private plugin implementations or public fallbacks.

Design principles:
- CK login is a PUBLIC capability (always available, no private dependency)
- Phone login is a PRIVATE capability (requires auth_api.py in private package)
- Reviews is a PRIVATE capability (requires reviews.py in private package)
- Private cookie_auth.py is OPTIONAL enhancement for CK login (deep validation)
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.official_auth.contracts import PrivatePluginManifest
from app.services.official_auth.loader import private_plugin_loader
from app.services.official_auth.sessions import OfficialLoginSession, session_store
from app.services.plugin_auth_repository import PluginAuthRepository
from app.services import plugin_cookie_file_store
from app.services.qidian_login_service import QidianLoginSession, qidian_login_service


# ------------------------------------------------------------------
# Public cookie utilities (CK login main path, no private dependency)
# ------------------------------------------------------------------

class PublicCookieTools:
    """Public cookie parsing, normalization, and basic verification.
    These do NOT require any private plugin."""

    @staticmethod
    def parse_cookie_text(cookie_text: str) -> dict[str, dict[str, str]]:
        """Parse raw cookie text into domain-keyed jar."""
        jar: dict[str, dict[str, str]] = {}
        cookie_text = cookie_text.strip()
        if not cookie_text:
            return jar

        # Try JSON first
        if cookie_text.startswith("{"):
            try:
                data = json.loads(cookie_text)
                if isinstance(data, dict):
                    first_val = next(iter(data.values())) if data else None
                    if isinstance(first_val, dict):
                        return {k: dict(v) for k, v in data.items() if isinstance(v, dict)}
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

        return PublicCookieTools.normalize_cookies(jar)

    @staticmethod
    def normalize_cookies(cookie_jar: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        """Normalize: copy shared fields across qidian.com and yuewen.com."""
        normalized: dict[str, dict[str, str]] = {}
        for domain, cookies in cookie_jar.items():
            if isinstance(cookies, dict):
                normalized[domain] = dict(cookies)

        shared_keys = {"ywguid", "ywkey", "ywopenid", "_csrfToken", "QDInfo", "fu", "alk"}
        shared_values: dict[str, str] = {}
        for domain, cookies in normalized.items():
            for key in shared_keys:
                if key in cookies:
                    shared_values[key] = cookies[key]

        for domain in ("qidian.com", "yuewen.com"):
            if domain not in normalized:
                normalized[domain] = {}
            for key, value in shared_values.items():
                if key not in normalized[domain]:
                    normalized[domain][key] = value

        return normalized

    @staticmethod
    def basic_verify(cookie_jar: dict[str, dict[str, str]]) -> dict:
        """Basic cookie verification (public, no network calls)."""
        all_cookies: dict[str, str] = {}
        for domain, cookies in cookie_jar.items():
            if isinstance(cookies, dict):
                all_cookies.update(cookies)

        if not all_cookies:
            return {"authenticated": False, "accountName": "", "message": "未检测到 Cookie"}

        # Check critical fields for Qidian Web login
        login_markers = {
            "ywguid": "用户 GUID",
            "ywkey": "登录密钥",
            "ywopenid": "阅文 OpenID",
            "_csrfToken": "CSRF Token",
        }
        found = {k: login_markers[k] for k in login_markers if all_cookies.get(k)}
        has_critical = bool(all_cookies.get("ywguid") or all_cookies.get("ywkey"))

        if not has_critical:
            return {
                "authenticated": False,
                "accountName": "",
                "message": "Cookie 不完整，缺少关键登录态字段（ywguid / ywkey）",
            }

        marker_names = ", ".join(found.keys())
        return {
            "authenticated": True,
            "accountName": "",
            "message": f"Cookie 格式正确（{marker_names}）",
        }


class OfficialAuthManager:
    """Central manager for official source authentication."""

    def capabilities(self, plugin_id: str) -> dict:
        """Return available login capabilities for a plugin.

        Rules:
        - cookie is ALWAYS available (public capability)
        - phone is available when private auth_api.py exists OR a public
          fallback is implemented for this plugin (e.g. qidian_com)
        - browser is a fallback when no phone auth exists
        """
        private = private_plugin_loader.load(plugin_id)
        has_private_phone = private.get("authApi") is not None
        has_public_phone = self._has_public_phone_fallback(plugin_id)
        has_phone = has_private_phone or has_public_phone
        has_private_cookie = private.get("cookieAuth") is not None

        methods: list[str] = ["cookie"]  # always available
        if has_phone:
            methods.insert(0, "phone")  # phone first if available

        # Browser fallback (legacy, can be removed later)
        from app.source_plugins.scheduler import PluginScheduler
        scheduler = PluginScheduler()
        plugin = scheduler._plugins.get(plugin_id)
        if plugin:
            auth = plugin.metadata.auth or {}
            if auth.get("loginUrl") and not has_phone:
                methods.append("browser")

        manifest: PrivatePluginManifest | None = private.get("manifest")

        return {
            "pluginId": plugin_id,
            "methods": methods,
            "defaultMethod": methods[0] if methods else "",
            "privateFeatures": {
                "phoneAuth": has_private_phone,
                "cookieAuth": has_private_cookie,  # private enhancement only
                "reviews": manifest.reviews if manifest else False,
            },
            "hasPrivatePackage": private.get("available", False),
        }

    def request_phone_code(self, plugin_id: str, payload: dict) -> dict:
        """Step 1 of phone login: request SMS code.

        Full payload is forwarded to private auth_api, including challenge params.
        Payload keys: phone, sessionId, challengeToken, challengeRandstr, ...
        """
        private = private_plugin_loader.load(plugin_id)
        auth_api = private.get("authApi")

        session_id = payload.get("sessionId", "")
        phone = payload.get("phone", "")

        if not phone:
            return {"ok": False, "error": "缺少手机号"}

        if auth_api:
            return self._request_phone_code_private(plugin_id, payload, auth_api, session_id, phone)

        if self._has_public_phone_fallback(plugin_id):
            return self._request_phone_code_qidian_fallback(plugin_id, payload, session_id, phone)

        return {
            "ok": False,
            "error": "手机号登录能力未安装",
            "message": "未检测到私有登录插件，无法使用手机号验证码登录",
        }

    async def verify_phone_code(self, plugin_id: str, payload: dict) -> dict:
        """Step 2 of phone login: verify SMS code."""
        session_id = payload.get("sessionId", "")
        session = session_store.get(session_id)
        if not session:
            return {"ok": False, "error": "会话已过期或不存在"}

        private = private_plugin_loader.load(plugin_id)
        auth_api = private.get("authApi")

        if auth_api:
            return await self._verify_phone_code_private(plugin_id, payload, session, auth_api)

        if self._has_public_phone_fallback(plugin_id):
            return await self._verify_phone_code_qidian_fallback(plugin_id, payload, session)

        return {"ok": False, "error": "手机号登录能力未安装"}

    async def verify_cookie(self, plugin_id: str, cookie_text: str) -> dict:
        """Verify pasted cookies — PUBLIC main path, no private dependency.

        Steps:
        1. Public parse -> normalize
        2. Write Cookie.json
        3. Run real auth_status probe with the saved cookies
        4. Return probe result
        """
        cookie_jar = PublicCookieTools.parse_cookie_text(cookie_text)
        if not cookie_jar:
            return {
                "ok": False,
                "authenticated": False,
                "accountName": "",
                "message": "未检测到 Cookie",
                "hasCookies": False,
                "cookieDomains": [],
            }

        probe = await self._save_cookie_jar_and_probe(plugin_id, cookie_jar)
        return {
            "ok": probe["authenticated"],
            "authenticated": probe["authenticated"],
            "accountName": probe["accountName"],
            "message": probe["message"],
            "hasCookies": bool(cookie_jar),
            "cookieDomains": sorted(cookie_jar.keys()),
        }

    def logout(self, plugin_id: str) -> dict:
        """Clear auth state for a plugin."""
        self._clear_plugin_auth(plugin_id)
        return {"ok": True, "message": "登录状态已清除"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mask_phone(phone: str) -> str:
        if len(phone) >= 7:
            return phone[:3] + "****" + phone[-4:]
        return phone

    @staticmethod
    async def _deep_verify_via_plugin(plugin_id: str, cookie_jar: dict) -> dict | None:
        """Try to call plugin's auth_status for deep validation.
        Returns None if plugin doesn't support it or fails."""
        from app.source_plugins.scheduler import PluginScheduler
        scheduler = PluginScheduler()
        plugin = scheduler._plugins.get(plugin_id)
        if not plugin or "auth" not in plugin.capabilities:
            return None

        try:
            # Build a minimal context with the cookies
            ctx = scheduler._make_ctx(plugin_id)
            # Inject cookies into the fetcher directly so qidian_com does not
            # re-persist Cookie.json-backed cookies into the DB cache.
            for domain, cookies in cookie_jar.items():
                if isinstance(cookies, dict):
                    for name, value in cookies.items():
                        ctx._fetcher.set_cookie(domain, name, value)

            result = await plugin.source.auth_status(ctx)
            return {
                "authenticated": result.get("authenticated", False),
                "accountName": result.get("accountName", ""),
                "message": result.get("message", ""),
                "authStatus": result.get("authStatus", ""),
                "requiredActions": result.get("requiredActions", []),
            }
        except Exception:
            return None

    def _persist_cookies(self, plugin_id: str, session: OfficialLoginSession) -> None:
        if not session.cookies:
            return
        repo = PluginAuthRepository()
        repo.set_cookies(plugin_id, session.cookies)

    def _persist_cookie_jar(self, plugin_id: str, cookie_jar: dict, result: dict) -> None:
        repo = PluginAuthRepository()
        repo.set_cookies(plugin_id, cookie_jar)
        repo.update_status(
            plugin_id,
            {
                "authenticated": result.get("authenticated", False),
                "accountName": result.get("accountName", ""),
                "expiresAt": "",
                "message": result.get("message", "Cookie 已导入"),
                "requiredActions": ["check_auth_status"] if result.get("authenticated") else [],
            },
        )

    async def save_cookies_and_probe(self, plugin_id: str, cookie_jar: dict) -> dict:
        """Public entry to persist a cookie jar and immediately probe auth status."""
        return await self._save_cookie_jar_and_probe(plugin_id, cookie_jar)

    async def probe_saved_cookie_file(self, plugin_id: str) -> dict:
        """Probe auth state directly from Cookie.json without reading DB cookies."""
        repo = PluginAuthRepository()
        cookie_jar = plugin_cookie_file_store.load(plugin_id)
        repo.clear_cookie_cache(plugin_id)

        if not cookie_jar:
            repo.update_status(
                plugin_id,
                {
                    "authenticated": False,
                    "authStatus": "anonymous",
                    "accountName": "",
                    "expiresAt": "",
                    "message": "未检测到 Cookie",
                    "requiredActions": ["manual_login"],
                },
            )
            return {
                "authenticated": False,
                "accountName": "",
                "message": "未检测到 Cookie",
                "authStatus": "anonymous",
            }

        return await self._probe_cookie_jar_and_cache_status(plugin_id, cookie_jar)

    async def _save_cookie_jar_and_probe(self, plugin_id: str, cookie_jar: dict) -> dict:
        """Persist cookie jar to Cookie.json, then run a real auth_status probe.

        Returns the probe result dict with at least:
          { authenticated, accountName, message, authStatus }
        """
        plugin_cookie_file_store.save(plugin_id, cookie_jar)
        return await self._probe_cookie_jar_and_cache_status(plugin_id, cookie_jar)

    async def _probe_cookie_jar_and_cache_status(self, plugin_id: str, cookie_jar: dict) -> dict:
        """Probe auth status using the provided cookie jar and cache only state fields."""
        probe = await self._deep_verify_via_plugin(plugin_id, cookie_jar)
        if probe is None:
            probe = {
                "authenticated": False,
                "accountName": "",
                "message": "插件不支持登录态探测",
            }

        auth_status = "anonymous"
        if probe.get("authenticated"):
            auth_status = "authenticated"
        elif probe.get("authStatus") in ("authenticated", "pending", "anonymous"):
            auth_status = probe.get("authStatus")
        elif cookie_jar:
            auth_status = "pending"

        repo = PluginAuthRepository()
        repo.update_status(
            plugin_id,
            {
                "authenticated": probe.get("authenticated", False),
                "accountName": probe.get("accountName", ""),
                "expiresAt": "",
                "message": probe.get("message", ""),
                "authStatus": auth_status,
                "requiredActions": probe.get("requiredActions", []),
            },
        )
        repo.clear_cookie_cache(plugin_id)

        return {
            "authenticated": probe.get("authenticated", False),
            "accountName": probe.get("accountName", ""),
            "message": probe.get("message", ""),
            "authStatus": auth_status,
        }

    def _clear_plugin_auth(self, plugin_id: str) -> None:
        """Delete Cookie.json and clear DB auth cache."""
        plugin_cookie_file_store.clear(plugin_id)
        repo = PluginAuthRepository()
        repo.clear_cookies(plugin_id)

    # ------------------------------------------------------------------
    # Phone fallback helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _has_public_phone_fallback(plugin_id: str) -> bool:
        """Public phone login fallback is currently implemented for qidian_com."""
        return plugin_id == "qidian_com"

    @staticmethod
    def _build_qidian_challenge(qidian_session: QidianLoginSession) -> dict:
        return {
            "appId": qidian_session.captcha_app_id or "1600000770",
            "type": "tencent_captcha",
            "captchaUrl": qidian_session.captcha_url,
            "captchaType": qidian_session.captcha_type,
        }

    def _request_phone_code_private(
        self,
        plugin_id: str,
        payload: dict,
        auth_api: Any,
        session_id: str,
        phone: str,
    ) -> dict:
        """Private auth_api path for phone code request.

        The private auth_api maintains its own session store, so we must map
        the manager's sessionId to the private plugin's sessionId.
        """
        if not session_id:
            # Fresh attempt: create manager session and let auth_api create its own.
            session = session_store.create(plugin_id, method="phone")
            session.phone_masked = self._mask_phone(phone)
            session_id = session.session_id
            private_payload = {}
        else:
            session = session_store.get(session_id)
            if not session:
                return {"ok": False, "error": "会话已过期或不存在"}
            private_payload = session.private_payload or {}

        # Use the private plugin's session id for auth_api calls.
        private_session_id = private_payload.get("sessionId", "")
        try:
            result = auth_api.request_code({**payload, "sessionId": private_session_id})
        except Exception as exc:
            session.status = "failed"
            session.last_error = str(exc)
            return {
                "ok": False,
                "sessionId": session_id,
                "error": str(exc),
            }

        # Preserve manager-level session id while updating the private payload.
        session.private_payload = {**result, "_managerSessionId": session_id}
        next_action = result.get("nextAction", "verify_code")
        session.status = "challenge" if next_action == "complete_challenge" else "sms_sent"
        session.last_step = "request_code"

        response = {
            "ok": result.get("ok", False),
            "sessionId": session_id,
            "nextAction": next_action,
        }

        if result.get("error"):
            response["error"] = result.get("error")
        if result.get("errorCode") is not None:
            response["errorCode"] = result.get("errorCode")

        if next_action == "complete_challenge":
            response["challenge"] = result.get("challenge", {})

        return response

    def _request_phone_code_qidian_fallback(
        self,
        plugin_id: str,
        payload: dict,
        session_id: str,
        phone: str,
    ) -> dict:
        """Public qidian_login_service path for phone code request."""
        if not session_id:
            # Fresh attempt: initialize qidian session and return captcha challenge
            session = session_store.create(plugin_id, method="phone")
            session.phone_masked = self._mask_phone(phone)
            try:
                qidian_session = qidian_login_service.init(phone)
            except Exception as exc:
                session.status = "failed"
                session.last_error = str(exc)
                return {"ok": False, "error": str(exc)}

            if qidian_session.status == "failed":
                session.status = "failed"
                session.last_error = qidian_session.message
                return {
                    "ok": False,
                    "sessionId": session.session_id,
                    "error": qidian_session.message or "初始化登录失败",
                }

            session.private_payload = {"qidian_session_id": qidian_session.session_id}
            session.status = "challenge"
            session.last_step = "init"
            return {
                "ok": False,
                "sessionId": session.session_id,
                "nextAction": "complete_challenge",
                "challenge": self._build_qidian_challenge(qidian_session),
            }

        # Retry after captcha: send SMS
        session = session_store.get(session_id)
        if not session:
            return {"ok": False, "error": "会话已过期或不存在"}

        qidian_session_id = session.private_payload.get("qidian_session_id")
        if not qidian_session_id:
            return {"ok": False, "error": "会话状态异常"}

        try:
            qidian_session = qidian_login_service.send_sms(
                qidian_session_id,
                phone,
                payload.get("challengeToken", ""),
                payload.get("challengeRandstr", ""),
            )
        except Exception as exc:
            session.status = "failed"
            session.last_error = str(exc)
            return {
                "ok": False,
                "sessionId": session_id,
                "error": str(exc),
            }

        if qidian_session.status == "failed":
            session.status = "challenge"
            session.last_error = qidian_session.message
            response = {
                "ok": False,
                "sessionId": session_id,
                "nextAction": "complete_challenge",
                "challenge": self._build_qidian_challenge(qidian_session),
                "error": qidian_session.message,
            }
            if qidian_session.error_code is not None:
                response["errorCode"] = qidian_session.error_code
            return response

        session.status = "sms_sent"
        session.last_step = "send_sms"
        return {
            "ok": True,
            "sessionId": session_id,
            "nextAction": "verify_code",
        }

    async def _verify_phone_code_private(
        self,
        plugin_id: str,
        payload: dict,
        session: OfficialLoginSession,
        auth_api: Any,
    ) -> dict:
        """Private auth_api path for phone code verification."""
        try:
            result = auth_api.verify_code({
                **payload,
                **session.private_payload,
            })
        except Exception as exc:
            session.status = "failed"
            session.last_error = str(exc)
            return {"ok": False, "error": str(exc)}

        if result.get("ok") and result.get("authenticated"):
            cookie_jar = result.get("cookies", {})
            probe = await self._save_cookie_jar_and_probe(plugin_id, cookie_jar)
            session.status = "success"
            session.cookies = cookie_jar
            session_store.remove(session.session_id)
            return {
                "ok": True,
                "authenticated": probe["authenticated"],
                "accountName": probe["accountName"],
                "message": probe["message"],
                "hasCookies": bool(cookie_jar),
            }

        session.status = "failed"
        session.last_error = result.get("message", "登录失败")
        return {
            "ok": False,
            "authenticated": False,
            "accountName": "",
            "message": result.get("message", "登录失败"),
            "hasCookies": bool(session.cookies),
        }

    async def _verify_phone_code_qidian_fallback(
        self,
        plugin_id: str,
        payload: dict,
        session: OfficialLoginSession,
    ) -> dict:
        """Public qidian_login_service path for phone code verification."""
        qidian_session_id = session.private_payload.get("qidian_session_id")
        if not qidian_session_id:
            return {"ok": False, "error": "会话状态异常"}

        sms_code = payload.get("code", "")
        if not sms_code:
            return {"ok": False, "error": "缺少验证码"}

        try:
            qidian_session = qidian_login_service.submit(qidian_session_id, sms_code)
        except Exception as exc:
            session.status = "failed"
            session.last_error = str(exc)
            return {"ok": False, "error": str(exc)}

        if qidian_session.status == "failed":
            session.status = "failed"
            session.last_error = qidian_session.message
            return {"ok": False, "error": qidian_session.message}

        cookie_jar = qidian_session.cookies or {}
        probe = await self._save_cookie_jar_and_probe(plugin_id, cookie_jar)
        session.status = "success"
        session.cookies = cookie_jar
        session_store.remove(session.session_id)

        return {
            "ok": True,
            "authenticated": probe["authenticated"],
            "accountName": probe["accountName"],
            "message": probe["message"],
            "hasCookies": bool(cookie_jar),
        }


# Global singleton
official_auth_manager = OfficialAuthManager()
