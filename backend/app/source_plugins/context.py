"""Runtime context API exposed to plugins.

Plugins use ctx for fetch, parse, trace, cookies, auth, and utilities.
LegadoHub core owns concurrency, timeout, proxy, cache, and trace policy.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from lxml import html as lh
from bs4 import BeautifulSoup

from app.services.text_convert import to_simplified, to_traditional
from app.source_plugins.fetcher import Fetcher
from app.source_plugins.errors import ParseEmpty, ParseError


class CookieJar:
    def __init__(self, fetcher: Fetcher, plugin_id: str, auth_repository: Any = None):
        self._fetcher = fetcher
        self._plugin_id = plugin_id
        self._auth_repository = auth_repository
        self._known_domains: set[str] = set()

    def get(self, domain: str, name: str | None = None) -> str | dict[str, str] | None:
        self._known_domains.add(domain)
        jar = self._fetcher.cookies_for_domain(domain)
        if name is None:
            return jar if jar else None
        return jar.get(name)

    def set(self, domain: str, cookie: dict[str, str]) -> None:
        self._known_domains.add(domain)
        for k, v in cookie.items():
            self._fetcher.set_cookie(domain, k, v)
        self._persist()

    def set_browser_cookies(self, cookies: list[dict[str, Any]]) -> None:
        for item in cookies:
            if not isinstance(item, dict):
                continue
            domain = str(item.get("domain", "")).lstrip(".")
            name = str(item.get("name", ""))
            value = str(item.get("value", ""))
            if not domain or not name:
                continue
            self._known_domains.add(domain)
            self._fetcher.set_cookie(domain, name, value)
        self._persist()

    def clear(self, domain: str | None = None) -> None:
        self._fetcher.clear_cookies(domain)
        if self._auth_repository is None:
            return
        if domain is None:
            self._auth_repository.clear_cookies(self._plugin_id)
            return
        current = self._auth_repository.get_cookies(self._plugin_id)
        current.pop(domain, None)
        self._auth_repository.set_cookies(self._plugin_id, current)

    def _persist(self) -> None:
        if self._auth_repository is None:
            return
        traces = self._fetcher.get_traces()
        # Persist known cookie domains from the fetcher jar. Fetcher exposes
        # domain reads only, so use trace URLs plus any existing stored domains.
        from urllib.parse import urlparse

        domains = set(self._auth_repository.get_cookies(self._plugin_id).keys()) | self._known_domains
        for trace in traces:
            url = trace.get("url", "")
            domain = urlparse(url).netloc
            if domain:
                domains.add(domain)
        cookies = {domain: self._fetcher.cookies_for_domain(domain) for domain in domains}
        cookie_snapshot = getattr(self._fetcher, "cookie_snapshot", lambda: {})()
        if isinstance(cookie_snapshot, dict):
            for domain, jar in cookie_snapshot.items():
                if isinstance(jar, dict) and jar:
                    cookies[domain] = jar
        cookies = {domain: jar for domain, jar in cookies.items() if jar}
        self._auth_repository.set_cookies(self._plugin_id, cookies)


class PluginContext:
    def __init__(
        self,
        fetcher: Fetcher,
        plugin_id: str,
        auth_repository: Any = None,
        browser_fetcher: Any = None,
    ):
        self._fetcher = fetcher
        self.plugin_id = plugin_id
        self.cookies = CookieJar(fetcher, plugin_id, auth_repository)
        self._browser_fetcher = browser_fetcher
        self._traces: list[dict] = []

    # -- Network --

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
        browser: bool = False,
        wait_ms: int = 2500,
    ) -> str:
        if browser:
            if self._browser_fetcher is None:
                from app.source_plugins.errors import BrowserRequired

                raise BrowserRequired("browser fetch is not configured", url=url)
            text = await self._browser_fetcher.fetch_text(
                self.plugin_id,
                url,
                method=method,
                data=data,
                timeout=timeout or 90.0,
                wait_ms=wait_ms,
            )
            self.cookies.set_browser_cookies(getattr(self._browser_fetcher, "last_cookies", []) or [])
            self.trace("browser_fetch", url=url, message=f"{method} {len(text)} chars")
            return text
        text = await self._fetcher.fetch_text(
            url, method=method, params=params, data=data, json=json, headers=headers, timeout=timeout, impersonate=impersonate, proxy=proxy
        )
        self.cookies._persist()
        self.trace("fetch", url=url, message=f"{method} {len(text)} chars")
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
        data_out = await self._fetcher.fetch_json(
            url, method=method, params=params, data=data, json=json, headers=headers, timeout=timeout, impersonate=impersonate, proxy=proxy
        )
        self.cookies._persist()
        self.trace("fetch_json", url=url, message=f"{method} json")
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
        bs = await self._fetcher.fetch_bytes(
            url, method=method, params=params, data=data, json=json, headers=headers, timeout=timeout, impersonate=impersonate, proxy=proxy
        )
        self.cookies._persist()
        self.trace("fetch_bytes", url=url, message=f"{method} {len(bs)} bytes")
        return bs

    async def fetch_many(
        self,
        urls: list[str],
        *,
        limit: int | None = None,
    ) -> list[str]:
        texts = await self._fetcher.fetch_many(urls, limit=limit)
        self.cookies._persist()
        self.trace("fetch_many", url=urls[0] if urls else "", message=f"{len(urls)} urls")
        return texts

    # -- Parsing --

    def _to_lxml(self, html_or_node: str | Any) -> Any:
        if isinstance(html_or_node, str):
            return lh.fromstring(html_or_node)
        return html_or_node

    def select(self, html_or_node: str | Any, selector: str) -> list[Any]:
        """CSS selector; returns list of lxml elements."""
        tree = self._to_lxml(html_or_node)
        return tree.cssselect(selector)

    def text(self, html_or_node: str | Any, selector: str | None = None) -> str:
        """Extract text. If selector is None, extract from root."""
        if selector is None:
            tree = self._to_lxml(html_or_node)
            text = tree.text_content() if hasattr(tree, "text_content") else str(tree)
            return self.clean_text(text)
        nodes = self.select(html_or_node, selector)
        if not nodes:
            return ""
        return self.clean_text(nodes[0].text_content())

    def html(self, html_or_node: str | Any, selector: str | None = None) -> str:
        """Extract inner HTML."""
        if selector is None:
            tree = self._to_lxml(html_or_node)
            return lh.tostring(tree, encoding="unicode")
        nodes = self.select(html_or_node, selector)
        if not nodes:
            return ""
        return lh.tostring(nodes[0], encoding="unicode")

    def attr(self, html_or_node: str | Any, selector: str, name: str) -> str:
        """Extract attribute from first matched element."""
        nodes = self.select(html_or_node, selector)
        if not nodes:
            return ""
        return nodes[0].get(name, "")

    def json_path(self, data: Any, path: str) -> Any:
        """Simple JSON path like 'data.items' or 'data.items.0.name'."""
        current = data
        for part in path.split("."):
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    idx = int(part)
                    current = current[idx]
                except (ValueError, IndexError):
                    return None
            else:
                return None
        return current

    def regex(self, text: str, pattern: str, group: int = 1, default: str = "") -> str:
        m = re.search(pattern, text)
        if not m:
            return default
        try:
            return m.group(group)
        except IndexError:
            # If group=1 requested but no capturing groups exist, return full match
            if group == 1:
                return m.group(0)
            return default

    # -- Utilities --

    def urljoin(self, base: str, href: str) -> str:
        return urljoin(base, href)

    def clean_html(self, html: str) -> str:
        """Remove chrome/ads/scripts and return readable paragraph text."""
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "iframe"]):
            tag.decompose()
        for tag in soup.find_all(["br"]):
            tag.replace_with("\n")

        blocks: list[str] = []
        block_tags = soup.find_all(["p", "li"])
        if not block_tags:
            block_tags = soup.find_all(["div", "section", "article"])
        full_text = soup.get_text("\n", strip=True)
        if block_tags:
            for tag in block_tags:
                text = self.clean_text(tag.get_text(" ", strip=True))
                if text:
                    blocks.append(text)
            block_text_len = sum(len(block) for block in blocks)
            if len(self.clean_text(full_text)) > block_text_len * 2:
                blocks = [self.clean_text(line) for line in full_text.splitlines() if self.clean_text(line)]
        else:
            blocks = [self.clean_text(line) for line in full_text.splitlines() if self.clean_text(line)]

        cleaned: list[str] = []
        seen: set[str] = set()
        for block in blocks:
            if block in seen:
                continue
            seen.add(block)
            cleaned.append(block)
        return "\n\n".join(cleaned)

    def clean_text(self, text: str) -> str:
        """Normalize whitespace."""
        if not text:
            return ""
        return " ".join(text.split())

    def to_simplified(self, value: Any) -> Any:
        """Convert Traditional Chinese output text to Simplified Chinese."""
        return to_simplified(value)

    def to_traditional(self, value: Any) -> Any:
        """Convert Simplified Chinese input text to Traditional Chinese."""
        return to_traditional(value)

    def decode_text(self, content_bytes: bytes, charset: str | None = None) -> str:
        if charset:
            return content_bytes.decode(charset, errors="replace")
        # Try utf-8 first, then gbk
        for enc in ("utf-8", "gbk", "gb2312", "big5"):
            try:
                return content_bytes.decode(enc)
            except UnicodeDecodeError:
                pass
        return content_bytes.decode("utf-8", errors="replace")

    def trace(self, stage: str, url: str = "", message: str = "", data: Any = None) -> None:
        self._traces.append({
            "stage": stage,
            "url": url,
            "message": message,
            "data": data,
        })

    def get_traces(self) -> list[dict]:
        return list(self._traces)

    # -- Cache hooks (pass-through; scheduler may wrap) --

    def cache_get(self, key: str) -> Any:
        # Default no-op; scheduler may inject a real cache
        return None

    def cache_set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        pass

    # -- Auth/session --

    async def auth_status(self) -> dict:
        """Default auth status for sources without auth hooks."""
        return {
            "sourceId": self.plugin_id,
            "authenticated": False,
            "accountName": "",
            "expiresAt": "",
            "message": "未登录",
            "requiredActions": [],
        }

    async def request_manual_login(self, login_url: str, cookie_domains: list[str], message: str = "") -> dict:
        return {
            "sourceId": self.plugin_id,
            "mode": "manual_browser",
            "loginUrl": login_url,
            "instructions": message or "在打开的浏览器中完成登录，然后回到后台点击检测登录状态。",
            "cookieDomains": cookie_domains,
        }
