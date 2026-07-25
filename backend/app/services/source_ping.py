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
    PING_ATTEMPT_TIMEOUT_SECONDS = 3.0
    MAX_CONCURRENCY = 5

    def __init__(self, scheduler: PluginScheduler | None = None, repo: Any | None = None):
        self.scheduler = scheduler or get_plugin_scheduler()
        self.repo = repo or _RuntimeHealthRepo()

    def _resolve_ping_urls(self, plugin) -> list[str]:
        """Resolve all declared website URLs in preferred order."""
        if not hasattr(plugin, "metadata"):
            return []

        meta = plugin.metadata
        urls = list(getattr(meta, "base_urls", []) or [])
        for profile in getattr(meta, "domain_profiles", []) or []:
            if not isinstance(profile, dict):
                continue
            urls.append(profile.get("baseUrl", ""))
            profile_urls = profile.get("baseUrls", [])
            if isinstance(profile_urls, list):
                urls.extend(profile_urls)
        domains = getattr(meta, "domains", []) or []
        urls.extend(f"https://{domain}" for domain in domains)
        urls.extend(f"http://{domain}" for domain in domains)

        resolved: list[str] = []
        seen: set[str] = set()
        for value in urls:
            url = str(value or "").strip().rstrip("/")
            if url and url not in seen:
                seen.add(url)
                resolved.append(url)
        return resolved

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

        urls = self._resolve_ping_urls(plugin)
        if not urls:
            self.repo.record_ping(plugin_id, "unknown", 0, error="No ping URL resolved")
            return {"pluginId": plugin_id, "status": "unknown", "latencyMs": 0, "error": "No ping URL resolved"}

        use_proxy, proxy_url = self._should_use_proxy(plugin)
        start = time.perf_counter()

        attempted_url = urls[0]
        errors: list[str] = []
        try:
            mounts = None
            if use_proxy and proxy_url:
                mounts = {"all://": httpx.AsyncHTTPTransport(proxy=proxy_url)}

            async with asyncio.timeout(self.PING_TIMEOUT_SECONDS):
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self.PING_ATTEMPT_TIMEOUT_SECONDS),
                    mounts=mounts,
                    headers={"User-Agent": get_default_user_agent()},
                    follow_redirects=True,
                ) as client:
                    for url in urls:
                        attempted_url = url
                        attempt_start = time.perf_counter()
                        try:
                            response = await client.head(url)
                            if response.status_code in {404, 410}:
                                response = await client.get(url)
                        except httpx.TimeoutException:
                            errors.append(f"{url}: Timeout")
                            continue
                        except Exception as exc:
                            errors.append(f"{url}: {exc}")
                            continue

                        latency_ms = int((time.perf_counter() - attempt_start) * 1000)
                        if response.status_code in {404, 410}:
                            errors.append(f"{url}: HTTP {response.status_code}")
                            continue

                        self.repo.record_ping(plugin_id, "reachable", latency_ms, url=url, proxy_used=use_proxy)
                        return {"pluginId": plugin_id, "status": "reachable", "latencyMs": latency_ms, "url": url, "proxyUsed": use_proxy}

        except (TimeoutError, httpx.TimeoutException):
            latency_ms = int((time.perf_counter() - start) * 1000)
            error = f"{attempted_url}: Timeout"
            self.repo.record_ping(plugin_id, "unreachable", latency_ms, error=error, url=attempted_url, proxy_used=use_proxy)
            return {"pluginId": plugin_id, "status": "unreachable", "latencyMs": latency_ms, "url": attempted_url, "error": error, "proxyUsed": use_proxy}
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            self.repo.record_ping(plugin_id, "unreachable", latency_ms, error=str(exc), url=attempted_url, proxy_used=use_proxy)
            return {"pluginId": plugin_id, "status": "unreachable", "latencyMs": latency_ms, "url": attempted_url, "error": str(exc), "proxyUsed": use_proxy}

        latency_ms = int((time.perf_counter() - start) * 1000)
        error = errors[-1] if errors else "All declared URLs failed"
        self.repo.record_ping(plugin_id, "unreachable", latency_ms, error=error, url=attempted_url, proxy_used=use_proxy)
        return {"pluginId": plugin_id, "status": "unreachable", "latencyMs": latency_ms, "url": attempted_url, "error": error, "proxyUsed": use_proxy}

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
