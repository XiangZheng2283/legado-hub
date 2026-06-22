"""Source ping service: check if source websites are reachable."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.config import get_default_user_agent
from app.source_plugins.scheduler import PluginScheduler, get_plugin_scheduler


from app.services.plugin_runtime_state import get_runtime_state


class _RuntimeHealthRepo:
    """Stores ping results in lightweight runtime state, not the main DB."""

    def __init__(self) -> None:
        self._state = get_runtime_state()

    def record_ping(
        self,
        plugin_id: str,
        status: str,
        latency_ms: int,
        error: str | None = None,
        url: str | None = None,
        proxy_used: bool = False,
    ) -> None:
        self._state.record_ping(plugin_id, status, latency_ms, url=url, error=error, proxy_used=proxy_used)


class SourcePingService:
    """Ping source websites to check reachability, respecting per-source proxy settings."""

    PING_TIMEOUT_SECONDS = 10.0
    MAX_CONCURRENCY = 5

    def __init__(self, scheduler: PluginScheduler | None = None, repo: Any | None = None):
        self.scheduler = scheduler or get_plugin_scheduler()
        self.repo = repo or _RuntimeHealthRepo()

    def _resolve_ping_url(self, plugin) -> str | None:
        """Resolve the URL to ping for a plugin."""
        # Prefer base_urls, then domains
        urls = []
        if hasattr(plugin, "metadata"):
            meta = plugin.metadata
            urls.extend(meta.base_urls or [])
            urls.extend([f"https://{d}" for d in (meta.domains or [])])
            urls.extend([f"http://{d}" for d in (meta.domains or [])])
        for url in urls:
            if url:
                return url
        return None

    def _should_use_proxy(self, plugin) -> tuple[bool, str]:
        """Tightened proxy policy: direct by default, proxy only when explicit."""
        proxy_cfg = self.scheduler.config.get("proxy", {})
        if not proxy_cfg.get("enabled"):
            return False, ""
        proxy_meta = plugin.metadata.proxy or {}
        proxy_mode = proxy_meta.get("mode", "auto")
        if proxy_mode == "never":
            return False, ""
        if proxy_mode == "always":
            return True, proxy_cfg.get("url", "")
        if proxy_mode == "auto" and proxy_meta.get("required") and proxy_cfg.get("allowAutoRetry"):
            return True, proxy_cfg.get("url", "")
        return False, ""

    async def ping_one(self, plugin_id: str) -> dict[str, Any]:
        """Ping a single source and record the result.

        A source is considered reachable if the server responds at all
        (including 4xx/5xx status codes). Only network-level failures
        (timeout, connection refused, DNS error) count as unreachable.
        """
        plugin = self.scheduler._plugins.get(plugin_id)
        if not plugin:
            return {"pluginId": plugin_id, "status": "not_found", "latencyMs": 0, "error": "Plugin not loaded"}

        url = self._resolve_ping_url(plugin)
        if not url:
            self.repo.record_ping(plugin_id, "unknown", 0, error="No ping URL resolved")
            return {"pluginId": plugin_id, "status": "unknown", "latencyMs": 0, "error": "No ping URL resolved"}

        use_proxy, proxy_url = self._should_use_proxy(plugin)
        start = time.perf_counter()

        try:
            mounts = None
            if use_proxy and proxy_url:
                mounts = {"all://": httpx.AsyncHTTPTransport(proxy=proxy_url)}

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.PING_TIMEOUT_SECONDS),
                mounts=mounts,
                headers={"User-Agent": get_default_user_agent()},
                follow_redirects=True,
            ) as client:
                resp = await client.head(url)
                latency_ms = int((time.perf_counter() - start) * 1000)

                # Some sites block HEAD; fallback to GET
                if resp.status_code >= 400:
                    resp = await client.get(url, timeout=httpx.Timeout(self.PING_TIMEOUT_SECONDS))
                    latency_ms = int((time.perf_counter() - start) * 1000)

                # Any HTTP response means the server is reachable.
                # 404/410 are the only exceptions where the domain itself may be gone.
                if resp.status_code in {404, 410}:
                    self.repo.record_ping(plugin_id, "unreachable", latency_ms, error=f"HTTP {resp.status_code}", url=url, proxy_used=use_proxy)
                    return {"pluginId": plugin_id, "status": "unreachable", "latencyMs": latency_ms, "url": url, "error": f"HTTP {resp.status_code}", "proxyUsed": use_proxy}

                self.repo.record_ping(plugin_id, "reachable", latency_ms, url=url, proxy_used=use_proxy)
                return {"pluginId": plugin_id, "status": "reachable", "latencyMs": latency_ms, "url": url, "proxyUsed": use_proxy}

        except httpx.TimeoutException:
            latency_ms = int((time.perf_counter() - start) * 1000)
            self.repo.record_ping(plugin_id, "unreachable", latency_ms, error="Timeout", url=url, proxy_used=use_proxy)
            return {"pluginId": plugin_id, "status": "unreachable", "latencyMs": latency_ms, "url": url, "error": "Timeout", "proxyUsed": use_proxy}
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            self.repo.record_ping(plugin_id, "unreachable", latency_ms, error=str(exc), url=url, proxy_used=use_proxy)
            return {"pluginId": plugin_id, "status": "unreachable", "latencyMs": latency_ms, "url": url, "error": str(exc), "proxyUsed": use_proxy}

    async def ping_all(self, plugin_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Ping all enabled sources (or specified subset) concurrently."""
        if plugin_ids is None:
            plugin_ids = [
                p.metadata.id for p in self.scheduler._plugins.values()
                if p.metadata.enabled
            ]

        semaphore = asyncio.Semaphore(self.MAX_CONCURRENCY)

        async def _ping_one(pid: str) -> dict[str, Any]:
            async with semaphore:
                return await self.ping_one(pid)

        results = await asyncio.gather(*[_ping_one(pid) for pid in plugin_ids])
        return list(results)
