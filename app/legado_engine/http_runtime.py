"""HTTP runtime for Legado engine with proxy fallback and tracing."""

from __future__ import annotations

import httpx
from dataclasses import dataclass
from http.cookies import SimpleCookie

from app.engine.proxy import ProxyConfig, decide_proxy_mode, should_retry_with_proxy
from app.legado_engine.models import RequestSpec, TraceEvent


@dataclass
class FetchResult:
    text: str = ""
    final_url: str = ""
    proxy_used: bool = False
    attempts: int = 0
    direct_error: str = ""
    proxy_error: str = ""
    success: bool = False


class HttpRuntime:
    def __init__(
        self,
        user_agent: str = "",
        timeout: float = 8.0,
        proxy_url: str = "",
        trace: list[TraceEvent] | None = None,
        cookie_jar_enabled: bool = False,
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.proxy_url = proxy_url
        self.trace = trace or []
        self.cookie_jar_enabled = cookie_jar_enabled
        self._cookies: dict[str, str] = {}
        self._direct_client: httpx.AsyncClient | None = None
        self._proxy_client: httpx.AsyncClient | None = None

    def _make_client(self, proxy_url: str | None = None) -> httpx.AsyncClient:
        headers = {"User-Agent": self.user_agent} if self.user_agent else {}
        proxy = proxy_url if proxy_url else None
        return httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=self.timeout,
            proxy=proxy,
        )

    async def _get_direct_client(self) -> httpx.AsyncClient:
        if self._direct_client is None or self._direct_client.is_closed:
            self._direct_client = self._make_client()
        return self._direct_client

    async def _get_proxy_client(self) -> httpx.AsyncClient:
        if self._proxy_client is None or self._proxy_client.is_closed:
            self._proxy_client = self._make_client(self.proxy_url)
        return self._proxy_client

    async def _do_fetch(self, client: httpx.AsyncClient, spec: RequestSpec) -> tuple[str, str]:
        headers = dict(spec.headers)
        if self.cookie_jar_enabled and self._cookies and "Cookie" not in headers:
            headers["Cookie"] = "; ".join(f"{key}={value}" for key, value in self._cookies.items())
        if spec.method == "GET":
            response = await client.get(spec.url, headers=headers)
        else:
            response = await client.post(spec.url, data=spec.body, headers=headers)
        response.raise_for_status()
        self._store_cookies(response)
        content_bytes = response.content
        charset = spec.charset.lower()
        if charset in ("gbk", "gb2312"):
            try:
                text = content_bytes.decode("gbk", errors="replace")
            except Exception:
                text = content_bytes.decode("utf-8", errors="replace")
        else:
            try:
                text = content_bytes.decode(charset, errors="replace")
            except Exception:
                text = content_bytes.decode("utf-8", errors="replace")
        return text, str(response.url)

    def _store_cookies(self, response: httpx.Response) -> None:
        if not self.cookie_jar_enabled:
            return
        raw_cookie = response.headers.get("set-cookie", "")
        if not raw_cookie:
            return
        cookie = SimpleCookie()
        try:
            cookie.load(raw_cookie)
        except Exception:
            return
        for key, morsel in cookie.items():
            self._cookies[key] = morsel.value

    async def fetch_with_proxy(
        self,
        spec: RequestSpec,
        proxy_mode: str = "auto",
        proxy_config: ProxyConfig | None = None,
        source_id: str = "",
        stage: str = "",
    ) -> FetchResult:
        result = FetchResult()
        cfg = proxy_config or ProxyConfig()
        try_direct, try_proxy = decide_proxy_mode(proxy_mode, cfg)

        trace = TraceEvent(
            stage=stage,
            source_id=source_id,
            url=spec.url,
            proxy_used=False,
        )

        if try_direct:
            result.attempts += 1
            try:
                client = await self._get_direct_client()
                text, final_url = await self._do_fetch(client, spec)
                result.text = text
                result.final_url = final_url
                result.proxy_used = False
                result.success = True
                trace.latency_ms = 0  # Could be enhanced with real timing
                trace.error = ""
                self.trace.append(trace)
                return result
            except Exception as e:
                result.direct_error = str(e)
                trace.error = result.direct_error
                if try_proxy and should_retry_with_proxy(e, cfg):
                    result.attempts += 1
                    trace_proxy = TraceEvent(
                        stage=stage,
                        source_id=source_id,
                        url=spec.url,
                        proxy_used=True,
                    )
                    try:
                        client = await self._get_proxy_client()
                        text, final_url = await self._do_fetch(client, spec)
                        result.text = text
                        result.final_url = final_url
                        result.proxy_used = True
                        result.success = True
                        trace_proxy.error = ""
                        self.trace.append(trace_proxy)
                        return result
                    except Exception as pe:
                        result.proxy_error = str(pe)
                        result.success = False
                        trace_proxy.error = result.proxy_error
                        self.trace.append(trace_proxy)
                        return result
                else:
                    result.success = False
                    self.trace.append(trace)
                    return result

        if try_proxy and not try_direct:
            result.attempts += 1
            trace.proxy_used = True
            try:
                client = await self._get_proxy_client()
                text, final_url = await self._do_fetch(client, spec)
                result.text = text
                result.final_url = final_url
                result.proxy_used = True
                result.success = True
                trace.error = ""
                self.trace.append(trace)
                return result
            except Exception as e:
                result.proxy_error = str(e)
                result.success = False
                trace.error = result.proxy_error
                self.trace.append(trace)
                return result

        result.success = False
        self.trace.append(trace)
        return result

    async def close(self) -> None:
        if self._direct_client and not self._direct_client.is_closed:
            await self._direct_client.aclose()
        if self._proxy_client and not self._proxy_client.is_closed:
            await self._proxy_client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
