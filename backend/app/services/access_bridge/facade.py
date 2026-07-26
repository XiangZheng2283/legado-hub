"""Access Bridge facade exposed to source plugins.

All network access goes through one of the explicit sub-facades:
- ``ctx.access.http``     → direct HTTP (httpx / curl_cffi)
- ``ctx.access.stealth``  → HTTP with browser fingerprint / TLS impersonation
- ``ctx.access.browser``  → Playwright-backed browser rendering
- ``ctx.access.search_provider`` → search-provider (DDGS / Bing / Google)

The only host-level fallback is a single browser session refresh after an
explicit Cloudflare challenge, followed by one retry of the original HTTP call.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from app.services.access_bridge.models import AccessFetchRequest
from app.services.access_bridge.profiles import make_profile_id
from app.services.access_bridge.search_provider import DEFAULT_HEADERS, search_site
from app.source_plugins.errors import CloudflareRequired


_CF_REFRESH_LOCKS: dict[int, asyncio.Lock] = {}


def _cf_refresh_lock() -> asyncio.Lock:
    """Return one refresh lock per event loop."""
    loop_id = id(asyncio.get_running_loop())
    # ponytail: one lock serializes all CF refreshes per loop; split by domain if this becomes a bottleneck.
    return _CF_REFRESH_LOCKS.setdefault(loop_id, asyncio.Lock())


class _HttpAccessBridge:
    """Direct HTTP access through the core runtime (httpx / curl_cffi)."""

    def __init__(self, ctx: Any):
        self._ctx = ctx

    async def _with_cf_session(
        self,
        url: str,
        headers: dict | None,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Refresh a CF browser session once, then retry the HTTP request."""
        try:
            return await operation()
        except CloudflareRequired as original_error:
            async with _cf_refresh_lock():
                try:
                    return await operation()
                except CloudflareRequired:
                    pass
                try:
                    result = await self._ctx.access.browser.fetch(
                        url,
                        headers=headers,
                        stage="cloudflare_refresh",
                        wait_ms=5000,
                    )
                except Exception:
                    raise original_error
                challenge = result.challenge
                detected = (
                    bool(challenge.get("detected"))
                    if isinstance(challenge, dict)
                    else bool(getattr(challenge, "detected", False))
                )
                if result.error or detected:
                    raise original_error
            return await operation()

    async def fetch_text(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict | None = None,
        data: dict | None = None,
        json: dict | None = None,
        headers: dict | None = None,
        timeout: float | None = None,
        impersonate: str | None = None,
        proxy: bool = True,
    ) -> str:
        async def request() -> str:
            return await self._ctx._fetcher.fetch_text(
                url,
                method=method,
                params=params,
                data=data,
                json=json,
                headers=headers,
                timeout=timeout,
                impersonate=impersonate,
                proxy=proxy,
            )

        text = await self._with_cf_session(url, headers, request)
        self._ctx.cookies._persist()
        self._ctx.trace("access_http", url=url, message=f"{method} {len(text)} chars")
        return text

    async def fetch_json(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict | None = None,
        data: dict | None = None,
        json: dict | None = None,
        headers: dict | None = None,
        timeout: float | None = None,
        impersonate: str | None = None,
        proxy: bool = True,
    ) -> Any:
        async def request() -> Any:
            return await self._ctx._fetcher.fetch_json(
                url,
                method=method,
                params=params,
                data=data,
                json=json,
                headers=headers,
                timeout=timeout,
                impersonate=impersonate,
                proxy=proxy,
            )

        data_out = await self._with_cf_session(url, headers, request)
        self._ctx.cookies._persist()
        self._ctx.trace("access_http_json", url=url, message=f"{method} json")
        return data_out

    async def fetch_bytes(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict | None = None,
        data: dict | None = None,
        json: dict | None = None,
        headers: dict | None = None,
        timeout: float | None = None,
        impersonate: str | None = None,
        proxy: bool = True,
    ) -> bytes:
        async def request() -> bytes:
            return await self._ctx._fetcher.fetch_bytes(
                url,
                method=method,
                params=params,
                data=data,
                json=json,
                headers=headers,
                timeout=timeout,
                impersonate=impersonate,
                proxy=proxy,
            )

        bs = await self._with_cf_session(url, headers, request)
        self._ctx.cookies._persist()
        self._ctx.trace("access_http_bytes", url=url, message=f"{method} {len(bs)} bytes")
        return bs


class _StealthAccessBridge:
    """HTTP with browser-like headers and TLS impersonation."""

    def __init__(self, ctx: Any):
        self._ctx = ctx

    async def fetch_text(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict | None = None,
        data: dict | None = None,
        json: dict | None = None,
        headers: dict | None = None,
        timeout: float | None = None,
        impersonate: str | None = None,
        proxy: bool = True,
    ) -> str:
        merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
        return await self._ctx.access.http.fetch_text(
            url,
            method=method,
            params=params,
            data=data,
            json=json,
            headers=merged_headers,
            timeout=timeout,
            impersonate=impersonate or "chrome120",
            proxy=proxy,
        )

    async def fetch_json(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict | None = None,
        data: dict | None = None,
        json: dict | None = None,
        headers: dict | None = None,
        timeout: float | None = None,
        impersonate: str | None = None,
        proxy: bool = True,
    ) -> Any:
        merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
        return await self._ctx.access.http.fetch_json(
            url,
            method=method,
            params=params,
            data=data,
            json=json,
            headers=merged_headers,
            timeout=timeout,
            impersonate=impersonate or "chrome120",
            proxy=proxy,
        )

    async def fetch_bytes(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict | None = None,
        data: dict | None = None,
        json: dict | None = None,
        headers: dict | None = None,
        timeout: float | None = None,
        impersonate: str | None = None,
        proxy: bool = True,
    ) -> bytes:
        merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
        return await self._ctx.access.http.fetch_bytes(
            url,
            method=method,
            params=params,
            data=data,
            json=json,
            headers=merged_headers,
            timeout=timeout,
            impersonate=impersonate or "chrome120",
            proxy=proxy,
        )


class _BrowserAccessBridge:
    """Playwright-backed browser rendering access."""

    def __init__(self, ctx: Any):
        self._ctx = ctx

    async def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict | None = None,
        data: dict | None = None,
        stage: str = "",
        profile_id: str = "",
        proxy_profile: str = "",
        use_proxy: bool | None = None,
        proxy_url: str = "",
        wait_ms: int = 2500,
        timeout_ms: int = 90000,
        capture_network: bool = False,
        dom_snapshot: bool = False,
    ) -> Any:
        if self._ctx._access_bridge is None:
            from app.source_plugins.errors import BrowserRequired

            raise BrowserRequired("source access bridge browser runtime is not configured", url=url)

        # Honour plugin proxy.mode when the caller does not explicitly override
        if use_proxy is None:
            mode = self._ctx.proxy_mode
            if mode == "always":
                use_proxy = True
            elif mode == "never":
                use_proxy = False
            else:
                use_proxy = False
        if use_proxy and not proxy_url:
            proxy_url = self._ctx.proxy_url
        if not profile_id:
            domain_profile = urlparse(url).hostname or "default"
            proxy_identity = proxy_profile or "direct"
            if use_proxy and proxy_url and not proxy_profile:
                digest = hashlib.sha256(proxy_url.encode("utf-8")).hexdigest()[:8]
                proxy_identity = f"proxy-{digest}"
            profile_id = make_profile_id(
                self._ctx.plugin_id,
                domain_profile,
                proxy_identity,
            )

        request = AccessFetchRequest(
            plugin_id=self._ctx.plugin_id,
            url=url,
            stage=stage,
            method=method.upper(),
            headers=headers or {},
            data=data,
            profile_id=profile_id,
            proxy_profile=proxy_profile,
            proxy_url=proxy_url,
            use_proxy=use_proxy,
            wait_ms=wait_ms,
            timeout_ms=timeout_ms,
            capture_network=capture_network,
            dom_snapshot=dom_snapshot,
        )
        result = await self._ctx._access_bridge.fetch(request)
        self._ctx.cookies.set_browser_cookies(self._normalize_cookies(result.cookies))
        self._ctx.trace(
            "access_browser",
            url=url,
            message=f"{request.method} {len(result.html or '')} chars",
            data={"profileId": result.profile_id},
        )
        return result

    def _browser_fetch_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Filter and convert kwargs for the browser fetch method."""
        out = dict(kwargs)
        if "timeout" in out and "timeout_ms" not in out:
            out["timeout_ms"] = int(out.pop("timeout") * 1000)
        allowed = {
            "method", "headers", "data", "stage", "profile_id",
            "proxy_profile", "use_proxy", "proxy_url",
            "wait_ms", "timeout_ms", "capture_network", "dom_snapshot",
        }
        return {k: v for k, v in out.items() if k in allowed}

    async def fetch_text(
        self,
        url: str,
        **kwargs: Any,
    ) -> str:
        result = await self.fetch(url, **self._browser_fetch_kwargs(kwargs))
        return result.html or ""

    async def fetch_json(
        self,
        url: str,
        **kwargs: Any,
    ) -> Any:
        text = await self.fetch_text(url, **kwargs)
        return json.loads(text)

    async def fetch_bytes(
        self,
        url: str,
        **kwargs: Any,
    ) -> bytes:
        result = await self.fetch(url, **self._browser_fetch_kwargs(kwargs))
        return (result.html or "").encode("utf-8")

    def _normalize_cookies(self, cookies: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for cookie in cookies:
            if isinstance(cookie, dict):
                normalized.append(cookie)
                continue
            domain = getattr(cookie, "domain", "")
            name = getattr(cookie, "name", "")
            value = getattr(cookie, "value", "")
            if domain and name:
                normalized.append({"domain": domain, "name": name, "value": value})
        return normalized


class SourceAccessBridge:
    """Controlled source access facade exposed to source plugins."""

    def __init__(self, ctx: Any):
        self.http = _HttpAccessBridge(ctx)
        self.stealth = _StealthAccessBridge(ctx)
        self.browser = _BrowserAccessBridge(ctx)
        self._ctx = ctx

    async def search_provider(
        self,
        keyword: str,
        *,
        target_domain: str,
        url_patterns: list[str],
        provider_order: list[str],
        query_site_path: str = "",
        timeout: float = 5.0,
        proxy: bool | None = None,
        limit: int = 10,
    ):
        # Derive default from plugin proxy.mode; caller may still override
        if proxy is None:
            mode = self._ctx.proxy_mode
            proxy = mode == "always"

        async def _fetch_provider_page(provider_url: str) -> str:
            return await self._ctx.access.http.fetch_text(
                provider_url,
                headers=DEFAULT_HEADERS,
                timeout=timeout,
                proxy=proxy,
            )

        hits = await search_site(
            keyword,
            target_domain=target_domain,
            url_patterns=url_patterns,
            provider_order=provider_order,
            fetch_text=_fetch_provider_page,
            query_site_path=query_site_path,
            limit=limit,
        )
        self._ctx.trace(
            "access_search_provider",
            message=f"{target_domain} {len(hits)} hits",
            data={"targetDomain": target_domain, "providerOrder": provider_order},
        )
        return hits
