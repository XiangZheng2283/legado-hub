"""Official source login manager.

Routes login requests to private plugin implementations.

Design principles:
- CK login is a PUBLIC capability (always available, no private dependency)
- Phone login is a PRIVATE capability (requires auth_api.py in private package)
- Reviews is a PRIVATE capability (requires reviews.py in private package)
- Private cookie_auth.py is OPTIONAL enhancement for CK login (deep validation)
- Source-specific login implementations (e.g. qidian_com) live inside their
  plugin's private package; the manager remains generic.
- Cookie files are owned by the host, not the plugin directory.
- Auth status is determined by real-time plugin probes, not cached DB state.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.cookie_store import CookieStore
from app.services.official_auth.contracts import PrivatePluginManifest
from app.services.official_auth.loader import private_plugin_loader
from app.services.official_auth.sessions import (
    OfficialLoginSession,
    login_trace_store,
    session_store,
)


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
    """Central manager for official source authentication.

    Cookie persistence is delegated to CookieStore. Auth status is always the
    result of a real-time probe via the plugin's ``auth_status`` method; the
    manager no longer caches status in the database.
    """

    def __init__(self, cookie_store: CookieStore | None = None):
        self._cookie_store = cookie_store or CookieStore()

    def _plugin_declares_cookies(self, plugin_id: str) -> bool:
        from app.source_plugins.scheduler import get_plugin_scheduler

        try:
            scheduler = get_plugin_scheduler()
            plugin = scheduler._plugins.get(plugin_id)
            if plugin:
                return plugin.metadata.declares_cookies
        except Exception:
            pass
        return True

    def capabilities(self, plugin_id: str) -> dict:
        """Return available login capabilities for a plugin.

        Rules:
        - cookie is ALWAYS available (public capability)
        - phone is available only when private auth_api.py exists
        - browser is a fallback when no phone auth exists
        """
        private = private_plugin_loader.load(plugin_id)
        has_private_phone = private.get("authApi") is not None
        has_private_cookie = private.get("cookieAuth") is not None

        methods: list[str] = ["cookie"]  # always available
        if has_private_phone:
            methods.insert(0, "phone")  # phone first if available

        from app.source_plugins.scheduler import get_plugin_scheduler
        scheduler = get_plugin_scheduler()
        plugin = scheduler._plugins.get(plugin_id)
        if plugin:
            auth = plugin.metadata.auth or {}
            if auth.get("loginUrl") and not has_private_phone:
                methods.append("browser")

        manifest: PrivatePluginManifest | None = private.get("manifest")

        return {
            "pluginId": plugin_id,
            "methods": methods,
            "defaultMethod": methods[0] if methods else "",
            "privateFeatures": {
                "phoneAuth": has_private_phone,
                "cookieAuth": has_private_cookie,
                "reviews": manifest.reviews if manifest else False,
            },
            "hasPrivatePackage": private.get("available", False),
        }

    def request_phone_code(self, plugin_id: str, payload: dict) -> dict:
        """Step 1 of phone login: request SMS code."""
        private = private_plugin_loader.load(plugin_id)
        auth_api = private.get("authApi")

        session_id = payload.get("sessionId", "")
        phone = payload.get("phone", "")

        if not phone:
            return {"ok": False, "error": "缺少手机号"}

        if auth_api:
            return self._request_phone_code_private(plugin_id, payload, auth_api, session_id, phone)

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

        return {"ok": False, "error": "手机号登录能力未安装"}

    async def verify_cookie(self, plugin_id: str, cookie_text: str) -> dict:
        """Verify pasted cookies — PUBLIC main path, no private dependency.

        Steps:
        1. Public parse -> normalize
        2. Write to host cookie store
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
            "ok": probe["authenticated"] or probe.get("authStatus") == "pending",
            "authenticated": probe["authenticated"],
            "accountName": probe["accountName"],
            "message": probe["message"],
            "authStatus": probe.get("authStatus", "unknown"),
            "requiredActions": probe.get("requiredActions", []),
            "hasCookies": bool(cookie_jar),
            "cookieDomains": sorted(cookie_jar.keys()),
        }

    def logout(self, plugin_id: str) -> dict:
        """Clear auth state for a plugin."""
        self._cookie_store.clear(plugin_id)
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
        from app.source_plugins.scheduler import get_plugin_scheduler
        scheduler = get_plugin_scheduler()
        plugin = scheduler._plugins.get(plugin_id)
        if not plugin or "auth" not in plugin.capabilities:
            return None

        try:
            ctx = scheduler._make_ctx(plugin_id)
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

    async def save_cookies_and_probe(self, plugin_id: str, cookie_jar: dict) -> dict:
        """Public entry to persist a cookie jar and immediately probe auth status."""
        return await self._save_cookie_jar_and_probe(plugin_id, cookie_jar)

    async def probe_saved_cookie_file(self, plugin_id: str) -> dict:
        """Probe auth state directly from the host cookie store."""
        payload = self._cookie_store.load(plugin_id)
        cookie_jar = self._extract_jar(payload)

        if not cookie_jar:
            return {
                "authenticated": False,
                "accountName": "",
                "message": "未检测到 Cookie",
                "authStatus": "anonymous",
            }

        return await self._probe_cookie_jar(plugin_id, cookie_jar)

    async def _save_cookie_jar_and_probe(self, plugin_id: str, cookie_jar: dict) -> dict:
        """Persist cookie jar to the host store, then run a real auth_status probe."""
        if self._plugin_declares_cookies(plugin_id):
            self._cookie_store.save(plugin_id, {"cookies": cookie_jar})
        return await self._probe_cookie_jar(plugin_id, cookie_jar)

    async def _probe_cookie_jar(self, plugin_id: str, cookie_jar: dict) -> dict:
        """Probe auth status using the provided cookie jar."""
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

        return {
            "authenticated": probe.get("authenticated", False),
            "accountName": probe.get("accountName", ""),
            "message": probe.get("message", ""),
            "authStatus": auth_status,
            "requiredActions": probe.get("requiredActions", []),
        }

    @staticmethod
    def _extract_jar(payload: Any) -> dict[str, dict[str, str]]:
        """Extract a domain-keyed jar from a cookie payload."""
        if not isinstance(payload, dict):
            return {}
        cookies = payload.get("cookies")
        if isinstance(cookies, dict):
            return {
                str(domain): {str(k): str(v) for k, v in jar.items() if v is not None}
                for domain, jar in cookies.items()
                if isinstance(jar, dict)
            }
        return {}

    # ------------------------------------------------------------------
    # Phone auth helpers
    # ------------------------------------------------------------------

    def _request_phone_code_private(
        self,
        plugin_id: str,
        payload: dict,
        auth_api: Any,
        session_id: str,
        phone: str,
    ) -> dict:
        if not session_id:
            session = session_store.create(plugin_id, method="phone")
            session.phone_masked = self._mask_phone(phone)
            session_id = session.session_id
            private_payload = {}
        else:
            session = session_store.get(session_id)
            if not session:
                return {"ok": False, "error": "会话已过期或不存在"}
            private_payload = session.private_payload or {}

        private_session_id = private_payload.get("sessionId", "")
        auth_payload = {**payload, "sessionId": private_session_id}
        try:
            result = auth_api.request_code(auth_payload)
        except Exception as exc:
            session.status = "failed"
            session.last_error = str(exc)
            login_trace_store.record(
                plugin_id=plugin_id,
                step="request_code",
                payload=auth_payload,
                result={},
                session_id=session_id,
                error=str(exc),
            )
            return {
                "ok": False,
                "sessionId": session_id,
                "error": str(exc),
            }

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

        login_trace_store.record(
            plugin_id=plugin_id,
            step="request_code",
            payload=auth_payload,
            result=result,
            session_id=session_id,
        )
        return response

    async def _verify_phone_code_private(
        self,
        plugin_id: str,
        payload: dict,
        session: OfficialLoginSession,
        auth_api: Any,
    ) -> dict:
        auth_payload = {
            **payload,
            **session.private_payload,
        }
        try:
            result = auth_api.verify_code(auth_payload)
        except Exception as exc:
            session.status = "failed"
            session.last_error = str(exc)
            login_trace_store.record(
                plugin_id=plugin_id,
                step="verify_code",
                payload=auth_payload,
                result={},
                session_id=session.session_id,
                error=str(exc),
            )
            return {"ok": False, "error": str(exc)}

        if result.get("ok") and result.get("authenticated"):
            cookie_jar = result.get("cookies", {})
            probe = await self._save_cookie_jar_and_probe(plugin_id, cookie_jar)
            session.status = "success"
            session.cookies = cookie_jar
            session_store.remove(session.session_id)
            response = {
                "ok": True,
                "authenticated": probe["authenticated"],
                "accountName": probe["accountName"],
                "message": probe["message"],
                "authStatus": probe.get("authStatus", "unknown"),
                "requiredActions": probe.get("requiredActions", []),
                "hasCookies": bool(cookie_jar),
            }
            login_trace_store.record(
                plugin_id=plugin_id,
                step="verify_code",
                payload=auth_payload,
                result={"pluginResult": result, "probeResult": probe},
                session_id=session.session_id,
            )
            return response

        session.status = "failed"
        session.last_error = result.get("message", "登录失败")
        failed_response = {
            "ok": False,
            "authenticated": False,
            "accountName": "",
            "message": result.get("message", "登录失败"),
            "hasCookies": bool(session.cookies),
        }
        login_trace_store.record(
            plugin_id=plugin_id,
            step="verify_code",
            payload=auth_payload,
            result=result,
            session_id=session.session_id,
        )
        return failed_response


# Global singleton
official_auth_manager = OfficialAuthManager()
