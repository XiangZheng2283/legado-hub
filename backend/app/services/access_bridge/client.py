"""Source Access Bridge client entry point.

This module intentionally keeps the browser runtime behind an adapter boundary.
Unit tests and non-browser environments can inject a fake adapter, while the
runtime can use either bundled Chromium or a remote Browserless endpoint without
changing the source-plugin context contract.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.services.access_bridge.config import AccessBridgeConfig, default_browser_user_agent
from app.services.access_bridge.dom import normalize_network_entries, snapshot_from_html
from app.services.access_bridge.models import AccessFetchRequest, AccessFetchResult
from app.services.access_bridge.profiles import BrowserProfileStore
from app.source_plugins.challenges import (
    looks_like_browser_challenge,
    looks_like_cloudflare_challenge,
)


class AccessBridgeUnavailable(RuntimeError):
    """Raised when a browser capability is requested without a browser runtime."""


@dataclass
class _BrowserRuntime:
    loop: asyncio.AbstractEventLoop
    lock: asyncio.Lock
    slots: asyncio.Semaphore
    playwright: Any = None
    browser: Any = None


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
            result = await self.adapter.fetch(request)
            challenge = result.challenge if isinstance(result.challenge, dict) else {}
            reset_profile = getattr(self.adapter, "reset_profile", None)
            if challenge.get("detected") and request.profile_id and callable(reset_profile):
                reset_profile(request.profile_id)
                result = await self.adapter.fetch(request)
                retry_challenge = result.challenge if isinstance(result.challenge, dict) else {}
                if retry_challenge.get("detected"):
                    reset_profile(request.profile_id)
            return result
        if not self.config.enabled:
            raise AccessBridgeUnavailable("Source Access Bridge is disabled")
        raise AccessBridgeUnavailable(f"Browser provider is not supported: {self.config.provider}")

    async def close(self) -> None:
        """Release the current event loop's browser resources."""
        closer = getattr(self._adapter, "close", None)
        if closer is not None:
            result = closer()
            if inspect.isawaitable(result):
                await result

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
        self._runtime_lock = threading.Lock()
        self._runtimes: dict[int, _BrowserRuntime] = {}

    def reset_profile(self, profile_id: str) -> None:
        self.profile_store.clear_by_id(profile_id)

    async def fetch(self, request: AccessFetchRequest) -> AccessFetchResult:
        started = time.perf_counter()
        context = None
        page = None
        network_events: list[dict[str, Any]] = []
        try:
            runtime = self._runtime_for_current_loop()
            async with runtime.slots:
                browser = await self._browser_for_runtime(runtime)
                user_agent = next(
                    (
                        value
                        for key, value in request.headers.items()
                        if key.lower() == "user-agent" and value
                    ),
                    self._browser_user_agent(browser),
                )
                storage_state = self._read_storage_state(request, user_agent)
                context_kwargs: dict[str, Any] = {
                    "storage_state": storage_state,
                    "extra_http_headers": request.headers or None,
                    "user_agent": user_agent,
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
                    await asyncio.sleep(request.wait_ms / 1000)
                html = await page.content()
                title = await page.title()
                cookies = await context.cookies()
                await self._write_storage_state(request, context, user_agent)
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

    def _runtime_for_current_loop(self) -> _BrowserRuntime:
        loop = asyncio.get_running_loop()
        key = id(loop)
        with self._runtime_lock:
            runtime = self._runtimes.get(key)
            if runtime is None:
                runtime = _BrowserRuntime(
                    loop=loop,
                    lock=asyncio.Lock(),
                    slots=asyncio.Semaphore(self.config.pool_size),
                )
                self._runtimes[key] = runtime
            return runtime

    async def _browser_for_current_loop(self) -> Any:
        return await self._browser_for_runtime(self._runtime_for_current_loop())

    async def _browser_for_runtime(self, runtime: _BrowserRuntime) -> Any:
        async with runtime.lock:
            if self._browser_is_connected(runtime.browser):
                return runtime.browser
            await self._close_runtime(runtime)
            runtime.playwright = await self._start_playwright()
            try:
                runtime.browser = await self._connect(runtime.playwright)
            except Exception:
                await self._close_runtime(runtime)
                raise
            return runtime.browser

    async def _start_playwright(self) -> Any:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise AccessBridgeUnavailable("playwright is not installed") from exc
        return await async_playwright().start()

    def _browser_is_connected(self, browser: Any) -> bool:
        if browser is None:
            return False
        checker = getattr(browser, "is_connected", None)
        if not callable(checker):
            return True
        try:
            return bool(checker())
        except Exception:
            return False

    def _browser_user_agent(self, browser: Any) -> str:
        return default_browser_user_agent()

    async def _close_runtime(self, runtime: _BrowserRuntime) -> None:
        browser, playwright = runtime.browser, runtime.playwright
        runtime.browser = None
        runtime.playwright = None
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                pass

    async def close(self) -> None:
        """Close the browser owned by the current application event loop."""
        loop = asyncio.get_running_loop()
        with self._runtime_lock:
            runtime = self._runtimes.pop(id(loop), None)
        if runtime is not None:
            async with runtime.lock:
                await self._close_runtime(runtime)

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

        if isinstance(request.data, dict):
            parsed = urlsplit(request.url)
            origin = f"{parsed.scheme}://{parsed.netloc}/"
            await page.goto(
                origin,
                wait_until="domcontentloaded",
                timeout=request.timeout_ms,
            )
            if request.wait_ms > 0:
                await asyncio.sleep(request.wait_ms / 1000)
            response = await self._submit_form(page, request)
            return response, ""

        response = await context.request.fetch(
            request.url,
            method=method,
            headers=request.headers or None,
            timeout=request.timeout_ms,
            **self._request_payload(request.data),
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

    async def _submit_form(self, page: Any, request: AccessFetchRequest) -> Any:
        navigation = page.expect_navigation(
            wait_until="domcontentloaded",
            timeout=request.timeout_ms,
        )
        async with navigation as navigation_info:
            await page.evaluate(
                """
                ({url, fields}) => {
                    const form = document.createElement('form');
                    form.method = 'POST';
                    form.action = url;
                    for (const [name, value] of Object.entries(fields)) {
                        const input = document.createElement('input');
                        input.type = 'hidden';
                        input.name = name;
                        input.value = String(value ?? '');
                        form.appendChild(input);
                    }
                    document.body.appendChild(form);
                    HTMLFormElement.prototype.submit.call(form);
                }
                """,
                {"url": request.url, "fields": request.data},
            )
        return await navigation_info.value

    def _request_payload(self, data: Any) -> dict[str, Any]:
        if data is None:
            return {}
        if isinstance(data, dict):
            return {"form": data}
        if isinstance(data, (str, bytes)):
            return {"data": data}
        return {"data": json.dumps(data, ensure_ascii=False)}

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

    def _read_storage_state(
        self,
        request: AccessFetchRequest,
        user_agent: str,
    ) -> dict[str, Any] | None:
        if not request.profile_id:
            return None
        if self.profile_store.read_user_agent_by_id(request.profile_id) != user_agent:
            return None
        return self.profile_store.read_storage_state_by_id(request.profile_id)

    async def _write_storage_state(
        self,
        request: AccessFetchRequest,
        context: Any,
        user_agent: str,
    ) -> None:
        if not request.profile_id:
            return
        state = await context.storage_state()
        self.profile_store.write_storage_state_by_id(request.profile_id, state)
        self.profile_store.write_user_agent_by_id(request.profile_id, user_agent)


class BrowserlessPlaywrightAdapter(LocalChromiumPlaywrightAdapter):
    """Playwright adapter for self-hosted Browserless."""

    async def _connect(self, playwright: Any):
        endpoint = self.config.browserless_endpoint()
        if not endpoint:
            raise AccessBridgeUnavailable("Browserless WebSocket endpoint is not configured")
        if "/playwright" in endpoint:
            return await playwright.chromium.connect(endpoint, timeout=self.config.connect_timeout_ms)
        return await playwright.chromium.connect_over_cdp(endpoint, timeout=self.config.connect_timeout_ms)
