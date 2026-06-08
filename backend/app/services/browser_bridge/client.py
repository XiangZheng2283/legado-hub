"""Browser Bridge client entry point.

This module intentionally keeps the Browserless connection behind an adapter
boundary. Unit tests and non-browser environments can inject a fake adapter,
while the real Browserless Playwright adapter can be added without changing the
source-plugin context contract.
"""

from __future__ import annotations

from typing import Any

from app.services.browser_bridge.config import BrowserBridgeConfig
from app.services.browser_bridge.models import BrowserFetchRequest, BrowserFetchResult
from app.services.browser_bridge.profiles import BrowserProfileStore


class BrowserBridgeUnavailable(RuntimeError):
    """Raised when a browser capability is requested without Browserless."""


class BrowserBridgeClient:
    """Runtime-owned Browser Bridge client."""

    def __init__(
        self,
        config: BrowserBridgeConfig | None = None,
        adapter: Any = None,
    ):
        self.config = config or BrowserBridgeConfig.from_env()
        self.adapter = adapter or (
            BrowserlessPlaywrightAdapter(self.config) if self.config.enabled else None
        )

    async def fetch(self, request: BrowserFetchRequest) -> BrowserFetchResult:
        """Fetch a page through the configured browser bridge adapter."""
        if self.adapter is not None:
            return await self.adapter.fetch(request)
        if not self.config.enabled:
            raise BrowserBridgeUnavailable("Browserless is not configured")
        raise BrowserBridgeUnavailable("Browserless adapter is not implemented")


class BrowserlessPlaywrightAdapter:
    """Playwright adapter for self-hosted Browserless."""

    def __init__(self, config: BrowserBridgeConfig):
        self.config = config
        self.profile_store = BrowserProfileStore(config.profile_root)

    async def fetch(self, request: BrowserFetchRequest) -> BrowserFetchResult:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserBridgeUnavailable("playwright is not installed") from exc

        endpoint = self.config.browserless_endpoint()
        if not endpoint:
            raise BrowserBridgeUnavailable("Browserless WebSocket endpoint is not configured")

        async with async_playwright() as playwright:
            browser = await self._connect(playwright, endpoint)
            context = None
            page = None
            try:
                storage_state = self._read_storage_state(request)
                context = await browser.new_context(
                    storage_state=storage_state,
                    extra_http_headers=request.headers or None,
                )
                page = await context.new_page()
                response = await page.goto(
                    request.url,
                    wait_until="domcontentloaded",
                    timeout=request.timeout_ms,
                )
                if request.wait_ms > 0:
                    await page.wait_for_timeout(request.wait_ms)
                html = await page.content()
                title = await page.title()
                cookies = await context.cookies()
                await self._write_storage_state(request, context)
                return BrowserFetchResult(
                    ok=True,
                    final_url=page.url,
                    title=title,
                    html=html,
                    cookies=cookies,
                    challenge={"detected": False},
                    network=[],
                    proxy_used=bool(request.proxy_profile),
                    profile_id=request.profile_id,
                    elapsed_ms=0,
                    error="" if response is None else "",
                )
            except Exception as exc:
                return BrowserFetchResult(
                    ok=False,
                    final_url=request.url,
                    title="",
                    html="",
                    cookies=[],
                    challenge={"detected": False},
                    profile_id=request.profile_id,
                    error=str(exc),
                )
            finally:
                if page is not None:
                    await page.close()
                if context is not None:
                    await context.close()
                await browser.close()

    async def _connect(self, playwright: Any, endpoint: str):
        if "/playwright" in endpoint:
            return await playwright.chromium.connect(endpoint, timeout=self.config.connect_timeout_ms)
        return await playwright.chromium.connect_over_cdp(endpoint, timeout=self.config.connect_timeout_ms)

    def _read_storage_state(self, request: BrowserFetchRequest) -> dict[str, Any] | None:
        if not request.profile_id:
            return None
        return self.profile_store.read_storage_state_by_id(request.profile_id)

    async def _write_storage_state(self, request: BrowserFetchRequest, context: Any) -> None:
        if not request.profile_id:
            return
        state = await context.storage_state()
        self.profile_store.write_storage_state_by_id(request.profile_id, state)
