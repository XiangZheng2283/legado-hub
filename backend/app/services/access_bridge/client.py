"""Source Access Bridge client entry point.

This module intentionally keeps the browser runtime behind an adapter boundary.
Unit tests and non-browser environments can inject a fake adapter, while the
runtime can use either bundled Chromium or a remote Browserless endpoint without
changing the source-plugin context contract.
"""

from __future__ import annotations

import json
import time
from typing import Any

from app.services.access_bridge.config import AccessBridgeConfig
from app.services.access_bridge.dom import normalize_network_entries, snapshot_from_html
from app.services.access_bridge.models import AccessFetchRequest, AccessFetchResult
from app.services.access_bridge.profiles import BrowserProfileStore
from app.source_plugins.challenges import (
    looks_like_browser_challenge,
    looks_like_cloudflare_challenge,
)


class AccessBridgeUnavailable(RuntimeError):
    """Raised when a browser capability is requested without a browser runtime."""


class AccessBridgeClient:
    """Runtime-owned Source Access Bridge client."""

    def __init__(
        self,
        config: AccessBridgeConfig | None = None,
        adapter: Any = None,
    ):
        self.config = config or AccessBridgeConfig.from_env()
        self._adapter = adapter

    @property
    def adapter(self) -> Any:
        if self._adapter is None:
            self._adapter = self._make_adapter(self.config)
        return self._adapter

    async def fetch(self, request: AccessFetchRequest) -> AccessFetchResult:
        """Fetch a page through the configured Source Access Bridge adapter."""
        if self.adapter is not None:
            return await self.adapter.fetch(request)
        if not self.config.enabled:
            raise AccessBridgeUnavailable("Source Access Bridge is disabled")
        raise AccessBridgeUnavailable(f"Browser provider is not supported: {self.config.provider}")

    def _make_adapter(self, config: AccessBridgeConfig) -> Any:
        if not config.enabled:
            return None
        if config.provider == "browserless":
            return BrowserlessPlaywrightAdapter(config)
        if config.provider in {"chromium", "playwright"}:
            return LocalChromiumPlaywrightAdapter(config)
        return None


class PlaywrightAdapterBase:
    """Shared Playwright page loading and result normalization."""

    def __init__(self, config: AccessBridgeConfig):
        self.config = config
        self.profile_store = BrowserProfileStore(config.profile_root)

    async def fetch(self, request: AccessFetchRequest) -> AccessFetchResult:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise AccessBridgeUnavailable("playwright is not installed") from exc

        async with async_playwright() as playwright:
            started = time.perf_counter()
            browser = await self._connect(playwright)
            context = None
            page = None
            network_events: list[dict[str, Any]] = []
            try:
                storage_state = self._read_storage_state(request)
                context_kwargs: dict[str, Any] = {
                    "storage_state": storage_state,
                    "extra_http_headers": request.headers or None,
                }
                if request.use_proxy and request.proxy_url:
                    context_kwargs["proxy"] = {"server": request.proxy_url}
                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()
                if request.capture_network:
                    self._attach_network_capture(page, network_events)
                response, final_url_override = await self._load_page(
                    page,
                    context,
                    request,
                    network_events,
                )
                if request.wait_ms > 0:
                    await page.wait_for_timeout(request.wait_ms)
                html = await page.content()
                title = await page.title()
                cookies = await context.cookies()
                await self._write_storage_state(request, context)
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                final_url = final_url_override or page.url
                return AccessFetchResult(
                    ok=self._response_ok(response),
                    final_url=final_url,
                    title=title,
                    html=html,
                    cookies=cookies,
                    challenge=self._detect_challenge(html, final_url),
                    network=normalize_network_entries(network_events),
                    dom_snapshot=(
                        snapshot_from_html(html, url=final_url) if request.dom_snapshot else None
                    ),
                    proxy_used=request.use_proxy and bool(request.proxy_url),
                    profile_id=request.profile_id,
                    elapsed_ms=elapsed_ms,
                    error="" if response is None else "",
                )
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                return AccessFetchResult(
                    ok=False,
                    final_url=request.url,
                    title="",
                    html="",
                    cookies=[],
                    challenge={"detected": False},
                    network=normalize_network_entries(network_events),
                    profile_id=request.profile_id,
                    elapsed_ms=elapsed_ms,
                    error=str(exc),
                )
            finally:
                if page is not None:
                    await page.close()
                if context is not None:
                    await context.close()
                await browser.close()

    async def _connect(self, playwright: Any):
        raise NotImplementedError


class LocalChromiumPlaywrightAdapter(PlaywrightAdapterBase):
    """Playwright adapter for the bundled Chromium browser."""

    async def _connect(self, playwright: Any):
        try:
            launch_args = ["--disable-dev-shm-usage"]
            if self.config.disable_sandbox:
                launch_args.append("--no-sandbox")
            return await playwright.chromium.launch(
                headless=True,
                timeout=self.config.connect_timeout_ms,
                args=launch_args,
            )
        except Exception as exc:
            raise AccessBridgeUnavailable(
                "Playwright Chromium is not installed; run `python -m playwright install chromium`"
            ) from exc

    async def _load_page(
        self,
        page: Any,
        context: Any,
        request: AccessFetchRequest,
        network_events: list[dict[str, Any]],
    ) -> tuple[Any, str]:
        method = (request.method or "GET").upper()
        if method == "GET":
            response = await page.goto(
                request.url,
                wait_until="domcontentloaded",
                timeout=request.timeout_ms,
            )
            return response, ""

        response = await context.request.fetch(
            request.url,
            method=method,
            headers=request.headers or None,
            data=self._request_body(request.data),
            timeout=request.timeout_ms,
        )
        if request.capture_network:
            network_events.append({
                "url": getattr(response, "url", request.url),
                "method": method,
                "status": int(getattr(response, "status", 0) or 0),
                "resourceType": "document",
                "requestHeaders": request.headers or {},
                "responseHeaders": self._maybe_headers(response),
            })
        html = await response.text()
        await page.goto("about:blank", wait_until="domcontentloaded", timeout=request.timeout_ms)
        await page.set_content(html, wait_until="domcontentloaded", timeout=request.timeout_ms)
        return response, str(getattr(response, "url", request.url) or request.url)

    def _request_body(self, data: Any) -> Any:
        if data is None:
            return None
        if isinstance(data, (str, bytes)):
            return data
        return json.dumps(data, ensure_ascii=False)

    def _response_ok(self, response: Any) -> bool:
        if response is None:
            return True
        ok = getattr(response, "ok", None)
        if isinstance(ok, bool):
            return ok
        status = int(getattr(response, "status", 0) or 0)
        return status == 0 or 200 <= status < 400

    def _attach_network_capture(self, page: Any, entries: list[dict[str, Any]]) -> None:
        request_index: dict[Any, dict[str, Any]] = {}

        def on_request(playwright_request: Any) -> None:
            entry = {
                "url": getattr(playwright_request, "url", ""),
                "method": getattr(playwright_request, "method", "GET"),
                "resourceType": getattr(playwright_request, "resource_type", ""),
                "requestHeaders": self._maybe_headers(playwright_request),
                "responseHeaders": {},
                "status": 0,
            }
            request_index[playwright_request] = entry
            entries.append(entry)

        def on_response(playwright_response: Any) -> None:
            playwright_request = getattr(playwright_response, "request", None)
            entry = request_index.get(playwright_request)
            if entry is None:
                entry = {
                    "url": getattr(playwright_response, "url", ""),
                    "method": "GET",
                    "resourceType": "",
                    "requestHeaders": {},
                    "responseHeaders": {},
                    "status": 0,
                }
                entries.append(entry)
            entry["status"] = int(getattr(playwright_response, "status", 0) or 0)
            entry["responseHeaders"] = self._maybe_headers(playwright_response)

        page.on("request", on_request)
        page.on("response", on_response)

    def _maybe_headers(self, owner: Any) -> dict[str, str]:
        headers = getattr(owner, "headers", {})
        if callable(headers):
            try:
                headers = headers()
            except TypeError:
                headers = {}
        if not isinstance(headers, dict):
            return {}
        return {str(key): str(value) for key, value in headers.items()}

    def _detect_challenge(self, html: str, url: str) -> dict[str, Any]:
        if looks_like_cloudflare_challenge(html):
            return {
                "detected": True,
                "kind": "cloudflare",
                "message": "Cloudflare or Turnstile challenge detected",
                "url": url,
            }
        if looks_like_browser_challenge(html):
            return {
                "detected": True,
                "kind": "browser",
                "message": "Browser challenge detected",
                "url": url,
            }
        return {"detected": False, "kind": "", "message": "", "url": url}

    def _read_storage_state(self, request: AccessFetchRequest) -> dict[str, Any] | None:
        if not request.profile_id:
            return None
        return self.profile_store.read_storage_state_by_id(request.profile_id)

    async def _write_storage_state(self, request: AccessFetchRequest, context: Any) -> None:
        if not request.profile_id:
            return
        state = await context.storage_state()
        self.profile_store.write_storage_state_by_id(request.profile_id, state)


class BrowserlessPlaywrightAdapter(LocalChromiumPlaywrightAdapter):
    """Playwright adapter for self-hosted Browserless."""

    async def _connect(self, playwright: Any):
        endpoint = self.config.browserless_endpoint()
        if not endpoint:
            raise AccessBridgeUnavailable("Browserless WebSocket endpoint is not configured")
        if "/playwright" in endpoint:
            return await playwright.chromium.connect(endpoint, timeout=self.config.connect_timeout_ms)
        return await playwright.chromium.connect_over_cdp(endpoint, timeout=self.config.connect_timeout_ms)




