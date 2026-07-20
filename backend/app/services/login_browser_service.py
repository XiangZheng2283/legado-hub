"""Login browser session service for official source manual login.

Opens a headed Playwright browser window so the user can complete
mobile-sms / captcha login manually. Detects login success by watching
URL navigation and login-state cookies, then extracts and persists cookies.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any


class LoginBrowserSession:
    """A single headed-browser login session for a source plugin."""

    STATUSES = ("pending", "running", "success", "failed", "timeout", "cancelled")

    def __init__(
        self,
        plugin_id: str,
        login_url: str,
        cookie_domains: list[str],
        timeout_seconds: int = 300,
    ):
        self.plugin_id = plugin_id
        self.login_url = login_url
        self.cookie_domains = cookie_domains
        self.timeout_seconds = timeout_seconds
        self.status = "pending"
        self.message = ""
        self.cookies: dict[str, dict[str, str]] = {}
        self._cancelled = False
        self._start_time = 0.0
        self._task: asyncio.Task | None = None

    async def run(self) -> dict:
        """Launch headed browser, wait for login, extract cookies."""
        self.status = "running"
        self._start_time = time.time()
        self.message = "正在启动浏览器..."

        try:
            from playwright.async_api import async_playwright
            from app.services.access_bridge.config import AccessBridgeConfig

            async with async_playwright() as playwright:
                launch_args = [
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ]
                if AccessBridgeConfig.from_env().disable_sandbox:
                    launch_args.append("--no-sandbox")
                browser = await playwright.chromium.launch(
                    headless=False,
                    args=launch_args,
                )

                from app.config import get_default_user_agent

                context = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=get_default_user_agent(),
                )

                page = await context.new_page()
                self.message = "浏览器已启动，请在窗口中完成登录"

                await page.goto(
                    self.login_url,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )

                logged_in = await self._wait_for_login(context, page)

                if self._cancelled:
                    self.status = "cancelled"
                    self.message = "登录已取消"
                elif logged_in:
                    self.status = "success"
                    self.message = "登录成功，Cookie 已提取"
                    raw_cookies = await context.cookies()
                    self.cookies = self._normalize_cookies(raw_cookies)
                else:
                    self.status = "timeout"
                    self.message = f"登录超时（{self.timeout_seconds}秒），请重试"

                try:
                    await page.close()
                except Exception:
                    pass
                try:
                    await context.close()
                except Exception:
                    pass
                try:
                    await browser.close()
                except Exception:
                    pass

        except Exception as exc:
            self.status = "failed"
            self.message = f"浏览器异常: {exc}"

        return self._result()

    async def _wait_for_login(self, context, page) -> bool:
        """Poll until login success indicators are detected."""
        check_interval = 2.0
        # Web login markers (passport.qidian.com redirects to passport.yuewen.com)
        login_markers = {"ywguid", "ywkey", "ywopenid", "_csrfToken", "QDInfo"}

        while True:
            if self._cancelled:
                return False

            elapsed = time.time() - self._start_time
            if elapsed >= self.timeout_seconds:
                return False

            await asyncio.sleep(check_interval)

            try:
                # Check 1: URL has left the passport page
                current_url = page.url
                left_passport = (
                    "passport.qidian.com" not in current_url
                    and "passport.yuewen.com" not in current_url
                )

                # Check 2: Login-state cookies are present
                raw_cookies = await context.cookies()
                names = {c.get("name", "") for c in raw_cookies}
                has_login_cookie = bool(login_markers & names)

                # Check 3: Domain covers qidian.com or yuewen.com
                qidian_domains = {
                    c.get("domain", "").lstrip(".")
                    for c in raw_cookies
                    if "qidian.com" in c.get("domain", "") or "yuewen.com" in c.get("domain", "")
                }
                has_qidian_cookie = bool(qidian_domains)

                if has_login_cookie and has_qidian_cookie and left_passport:
                    return True

                # Also accept: if we already have login cookies but URL still shows
                # passport (rare race), keep waiting a bit more.
            except Exception:
                pass  # Page may be navigating

    def _normalize_cookies(self, raw_cookies: list[dict]) -> dict[str, dict[str, str]]:
        result: dict[str, dict[str, str]] = {}
        for c in raw_cookies:
            domain = str(c.get("domain", "")).lstrip(".")
            name = str(c.get("name", ""))
            value = str(c.get("value", ""))
            if not domain or not name:
                continue
            result.setdefault(domain, {})[name] = value
        return result

    def _result(self) -> dict:
        return {
            "pluginId": self.plugin_id,
            "status": self.status,
            "message": self.message,
            "cookies": self.cookies,
            "hasCookies": bool(self.cookies),
            "cookieDomains": list(self.cookies.keys()),
        }

    def cancel(self) -> None:
        self._cancelled = True


class LoginBrowserService:
    """Global service managing active login-browser sessions."""

    def __init__(self):
        self._sessions: dict[str, LoginBrowserSession] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        plugin_id: str,
        login_url: str,
        cookie_domains: list[str],
    ) -> LoginBrowserSession:
        async with self._lock:
            old = self._sessions.get(plugin_id)
            if old:
                old.cancel()
                if old._task and not old._task.done():
                    try:
                        await asyncio.wait_for(old._task, timeout=5.0)
                    except asyncio.TimeoutError:
                        pass
                del self._sessions[plugin_id]

            session = LoginBrowserSession(
                plugin_id=plugin_id,
                login_url=login_url,
                cookie_domains=cookie_domains,
            )
            self._sessions[plugin_id] = session
            session._task = asyncio.create_task(self._run_and_cleanup(session))
            return session

    async def _run_and_cleanup(self, session: LoginBrowserSession) -> None:
        """Run session and auto-cleanup when done."""
        try:
            await session.run()
        finally:
            async with self._lock:
                if self._sessions.get(session.plugin_id) is session:
                    # Keep the completed session for a while so status queries work
                    pass

    async def get(self, plugin_id: str) -> LoginBrowserSession | None:
        return self._sessions.get(plugin_id)

    async def cancel(self, plugin_id: str) -> bool:
        async with self._lock:
            session = self._sessions.get(plugin_id)
            if session:
                session.cancel()
                return True
            return False

    async def cleanup(self, plugin_id: str) -> None:
        async with self._lock:
            self._sessions.pop(plugin_id, None)


# Global singleton
login_browser_service = LoginBrowserService()
