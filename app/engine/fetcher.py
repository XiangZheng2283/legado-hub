"""HTTP fetcher with support for Legado request specs and proxy fallback."""

from __future__ import annotations

import json
from urllib.parse import urljoin, quote

import httpx

from app.engine.proxy import ProxyConfig, FetchResult, should_retry_with_proxy, decide_proxy_mode


def parse_request_spec(spec_str: str, base_url: str = "") -> dict:
    """Parse Legado request spec like 'url,{"method":"POST","body":"...","charset":"gbk"}'"""
    url = spec_str
    method = "GET"
    body = None
    headers = {}
    charset = "utf-8"

    if spec_str.startswith("{"):
        try:
            opts = json.loads(spec_str)
            url = opts.get("url", "")
            method = opts.get("method", "GET")
            body = opts.get("body")
            headers = opts.get("headers", {})
            charset = opts.get("charset", "utf-8")
        except json.JSONDecodeError:
            pass
    elif "," in spec_str:
        parts = spec_str.split(",", 1)
        url = parts[0].strip()
        try:
            opts = json.loads(parts[1])
            method = opts.get("method", "GET")
            body = opts.get("body")
            headers = opts.get("headers", {})
            charset = opts.get("charset", "utf-8")
        except json.JSONDecodeError:
            pass

    if base_url and url and not url.startswith(("http://", "https://")):
        url = urljoin(base_url, url)

    return {
        "url": url,
        "method": method.upper(),
        "body": body,
        "headers": headers,
        "charset": charset,
    }


def build_search_url(search_url_template: str, keyword: str, page: int, base_url: str = "", charset: str = "utf-8") -> str:
    url = search_url_template
    url = url.replace("{{key}}", quote(keyword, encoding=charset, safe=""))
    url = url.replace("{{page}}", str(page))
    if base_url and not url.startswith(("http://", "https://")):
        url = urljoin(base_url, url)
    return url


class Fetcher:
    def __init__(self, user_agent: str = "", timeout: float = 8.0, proxy_url: str = ""):
        self.user_agent = user_agent
        self.timeout = timeout
        self.proxy_url = proxy_url
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

    async def _do_fetch(self, client: httpx.AsyncClient, spec: dict) -> tuple[str, str]:
        url = spec["url"]
        method = spec["method"]
        body = spec.get("body")
        headers = spec.get("headers", {})
        charset = spec.get("charset", "utf-8")

        if method == "GET":
            response = await client.get(url, headers=headers)
        else:
            response = await client.post(url, data=body, headers=headers)

        response.raise_for_status()

        content_bytes = response.content
        if charset.lower() in ("gbk", "gb2312"):
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

    async def fetch_with_proxy(
        self,
        spec: dict,
        proxy_mode: str = "auto",
        proxy_config: ProxyConfig | None = None,
    ) -> FetchResult:
        """Fetch with proxy fallback according to proxy_mode and proxy_config."""
        result = FetchResult()
        cfg = proxy_config or ProxyConfig()
        try_direct, try_proxy = decide_proxy_mode(proxy_mode, cfg)

        if try_direct:
            result.attempts += 1
            try:
                client = await self._get_direct_client()
                text, final_url = await self._do_fetch(client, spec)
                result.text = text
                result.final_url = final_url
                result.proxy_used = False
                result.success = True
                return result
            except Exception as e:
                result.direct_error = str(e)
                if try_proxy and should_retry_with_proxy(e, cfg):
                    result.attempts += 1
                    try:
                        client = await self._get_proxy_client()
                        text, final_url = await self._do_fetch(client, spec)
                        result.text = text
                        result.final_url = final_url
                        result.proxy_used = True
                        result.success = True
                        return result
                    except Exception as pe:
                        result.proxy_error = str(pe)
                        result.success = False
                        return result
                else:
                    result.success = False
                    return result

        if try_proxy and not try_direct:
            result.attempts += 1
            try:
                client = await self._get_proxy_client()
                text, final_url = await self._do_fetch(client, spec)
                result.text = text
                result.final_url = final_url
                result.proxy_used = True
                result.success = True
                return result
            except Exception as e:
                result.proxy_error = str(e)
                result.success = False
                return result

        result.success = False
        return result

    # Backward-compatible fetch without proxy logic
    async def fetch(self, spec: dict) -> tuple[str, str]:
        result = await self.fetch_with_proxy(spec, proxy_mode="never")
        if not result.success:
            raise Exception(result.direct_error or result.proxy_error)
        return result.text, result.final_url

    async def close(self) -> None:
        if self._direct_client and not self._direct_client.is_closed:
            await self._direct_client.aclose()
        if self._proxy_client and not self._proxy_client.is_closed:
            await self._proxy_client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()
