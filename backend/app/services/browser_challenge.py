"""Browser verification sessions for Cloudflare/manual challenges.

The runtime creates these sessions when a plugin fetch hits a challenge page.
The console or Reading-compatible client can open ``openUrl`` in a real browser,
then submit browser cookies back to the plugin auth repository before retrying.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from app.services.plugin_auth_repository import PluginAuthRepository
from app.source_plugins.models import LoadedPlugin


_SESSIONS: dict[str, dict] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BrowserChallengeService:
    """Manage manual browser challenge sessions."""

    def __init__(self, auth_repository: PluginAuthRepository | None = None):
        self.auth_repository = auth_repository or PluginAuthRepository()

    def create_for_plugin(
        self,
        plugin: LoadedPlugin,
        *,
        stage: str,
        url: str = "",
        reason: str = "CLOUDFLARE_REQUIRED",
        message: str = "",
    ) -> dict:
        challenge_url = url or self._default_url(plugin)
        session_id = str(uuid.uuid4())
        domains = self._cookie_domains(plugin, challenge_url)
        session = {
            "sessionId": session_id,
            "sourceId": plugin.metadata.id,
            "sourceName": plugin.metadata.name,
            "type": "cloudflare" if reason == "CLOUDFLARE_REQUIRED" else "browser",
            "reason": reason,
            "stage": stage,
            "status": "pending",
            "openUrl": challenge_url,
            "cookieDomains": domains,
            "message": message or "该书源需要在真实浏览器中完成验证，保存 Cookie 后重试当前操作。",
            "createdAt": _now(),
            "updatedAt": _now(),
            "actions": {
                "open": f"/api/browser/challenges/{session_id}/open",
                "callback": f"/api/browser/challenges/{session_id}/callback",
                "status": f"/api/browser/challenges/{session_id}",
                "submitCookies": f"/api/browser/challenges/{session_id}/cookies",
                "consoleOpen": f"/api/browser/challenges/{session_id}/open",
                "legadoOpen": f"/api/browser/challenges/{session_id}/open",
                "consoleSubmitCookies": f"/api/console/browser-challenges/{session_id}/cookies",
                "consoleStatus": f"/api/console/browser-challenges/{session_id}",
                "retryLiveCheck": f"/api/console/browser-challenges/{session_id}/retry-live-check",
                "openBrowser": f"/api/console/browser-challenges/{session_id}/browser/open",
                "browserStatus": f"/api/console/browser-challenges/{session_id}/browser/status",
                "importBrowserCookies": f"/api/console/browser-challenges/{session_id}/browser/import-cookies",
                "legadoSubmitCookies": f"/api/legado/browser-challenges/{session_id}/cookies",
                "legadoStatus": f"/api/legado/browser-challenges/{session_id}",
                "legadoRetryLiveCheck": f"/api/legado/browser-challenges/{session_id}/retry-live-check",
                "legadoOpenBrowser": f"/api/legado/browser-challenges/{session_id}/browser/open",
                "legadoBrowserStatus": f"/api/legado/browser-challenges/{session_id}/browser/status",
                "legadoImportBrowserCookies": f"/api/legado/browser-challenges/{session_id}/browser/import-cookies",
                "retryHint": "完成验证并提交 Cookie 后，重新发起搜索、详情、目录或正文请求。",
            },
        }
        _SESSIONS[session_id] = session
        return dict(session)

    def get(self, session_id: str) -> dict | None:
        session = _SESSIONS.get(session_id)
        return dict(session) if session else None

    def list(self, source_id: str | None = None) -> list[dict]:
        items = list(_SESSIONS.values())
        if source_id:
            items = [item for item in items if item.get("sourceId") == source_id]
        return [dict(item) for item in sorted(items, key=lambda x: x.get("createdAt", ""), reverse=True)]

    def submit_cookies(self, session_id: str, cookies: Any) -> dict:
        session = _SESSIONS.get(session_id)
        if not session:
            return {"saved": False, "error": "验证会话不存在", "sessionId": session_id}
        normalized = self.normalize_cookies(cookies)
        if not normalized:
            normalized = self._normalize_cookie_header_for_session(session, cookies)
        if not normalized:
            return {"saved": False, "error": "未提交有效 Cookie", "sessionId": session_id}
        source_id = session["sourceId"]
        current = self.auth_repository.get_cookies(source_id)
        for domain, jar in normalized.items():
            current.setdefault(domain, {}).update(jar)
        self.auth_repository.set_cookies(source_id, current)
        session["status"] = "cookies_saved"
        session["updatedAt"] = _now()
        session["savedCookieDomains"] = sorted(normalized.keys())
        clearance_domains = sorted(
            domain for domain, jar in current.items()
            if isinstance(jar, dict) and "cf_clearance" in jar
        )
        missing_clearance_domains = [
            domain for domain in session.get("cookieDomains", [])
            if not any(self._domain_matches(clearance_domain, domain) for clearance_domain in clearance_domains)
        ]
        session["clearanceDomains"] = clearance_domains
        return {
            "saved": True,
            "sessionId": session_id,
            "sourceId": source_id,
            "cookieDomains": sorted(current.keys()),
            "clearanceDomains": clearance_domains,
            "missingClearanceDomains": missing_clearance_domains,
            "status": session["status"],
        }

    def record_retry_result(self, session_id: str, result: dict) -> dict:
        session = _SESSIONS.get(session_id)
        if not session:
            return {"saved": False, "error": "验证会话不存在", "sessionId": session_id}
        session["status"] = "retry_passed" if result.get("passed") else "retry_failed"
        session["updatedAt"] = _now()
        session["retryResult"] = result
        return dict(session)

    def mark_verified(self, session_id: str, payload: dict | None = None) -> dict:
        session = _SESSIONS.get(session_id)
        if not session:
            return {"verified": False, "error": "验证会话不存在", "sessionId": session_id}
        session["status"] = "verified"
        session["updatedAt"] = _now()
        if payload:
            session["callbackResult"] = payload
        return dict(session)

    def record_browser_helper(self, session_id: str, helper_result: dict) -> dict:
        session = _SESSIONS.get(session_id)
        if not session:
            return {"saved": False, "error": "验证会话不存在", "sessionId": session_id}
        session["status"] = "browser_opened"
        session["updatedAt"] = _now()
        session["browserHelper"] = {k: v for k, v in helper_result.items() if k != "started"}
        return dict(session)

    def normalize_cookies(self, cookies: Any) -> dict[str, dict[str, str]]:
        """Accept Playwright-style lists or domain-keyed cookie maps."""
        if isinstance(cookies, dict) and "cookies" in cookies:
            cookies = cookies["cookies"]
        if isinstance(cookies, dict):
            normalized: dict[str, dict[str, str]] = {}
            for domain, jar in cookies.items():
                if not isinstance(jar, dict):
                    continue
                clean_domain = str(domain).lstrip(".")
                normalized[clean_domain] = {str(k): str(v) for k, v in jar.items()}
            return normalized
        if isinstance(cookies, list):
            normalized = {}
            for item in cookies:
                if not isinstance(item, dict):
                    continue
                domain = str(item.get("domain", "")).lstrip(".")
                name = str(item.get("name", ""))
                value = str(item.get("value", ""))
                if not domain or not name:
                    continue
                normalized.setdefault(domain, {})[name] = value
            return normalized
        return {}

    def _normalize_cookie_header_for_session(self, session: dict, cookies: Any) -> dict[str, dict[str, str]]:
        header = ""
        domain = ""
        if isinstance(cookies, str):
            header = cookies
        elif isinstance(cookies, dict):
            header = str(cookies.get("cookieHeader", "") or cookies.get("cookie", "") or "")
            domain = str(cookies.get("domain", "") or "")
        if not header.strip():
            return {}
        header = self._extract_cookie_header_value(header)
        domain = domain.strip().lstrip(".") or (session.get("cookieDomains") or [""])[0]
        if not domain:
            return {}
        jar: dict[str, str] = {}
        for part in header.replace("\r\n", "\n").split(";"):
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            name = name.strip()
            value = value.strip()
            if name:
                jar[name] = value
        return {domain: jar} if jar else {}

    def _extract_cookie_header_value(self, value: str) -> str:
        """Accept raw Cookie or Set-Cookie header lines copied from DevTools."""
        lines = [line.strip() for line in str(value or "").replace("\r\n", "\n").split("\n") if line.strip()]
        if not lines:
            return ""
        cookie_lines: list[str] = []
        for line in lines:
            lower = line.lower()
            if lower.startswith("cookie:"):
                cookie_lines.append(line.split(":", 1)[1].strip())
            elif lower.startswith("set-cookie:"):
                payload = line.split(":", 1)[1].strip()
                first_pair = payload.split(";", 1)[0].strip()
                if first_pair:
                    cookie_lines.append(first_pair)
        if cookie_lines:
            return "; ".join(cookie_lines)
        return lines[0]

    def _default_url(self, plugin: LoadedPlugin) -> str:
        browser = plugin.metadata.browser or {}
        if browser.get("verificationUrl"):
            return browser["verificationUrl"]
        if plugin.metadata.base_urls:
            return plugin.metadata.base_urls[0]
        return ""

    def _cookie_domains(self, plugin: LoadedPlugin, url: str) -> list[str]:
        from urllib.parse import urlparse

        domains = set(plugin.metadata.auth.get("cookieDomains", []) or [])
        domains.update(plugin.metadata.domains or [])
        parsed = urlparse(url)
        if parsed.netloc:
            domains.add(parsed.netloc)
        for profile in plugin.metadata.domain_profiles:
            domains.update(profile.get("domains", []) or [])
        return sorted(domain.lstrip(".") for domain in domains if domain)

    def _domain_matches(self, cookie_domain: str, target_domain: str) -> bool:
        cookie_domain = str(cookie_domain or "").strip().lstrip(".").lower()
        target_domain = str(target_domain or "").strip().lstrip(".").lower()
        return target_domain == cookie_domain or target_domain.endswith(f".{cookie_domain}")
