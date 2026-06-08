"""Search-engine access owned by Browser Bridge."""

from __future__ import annotations

import base64
import re
from collections.abc import Awaitable, Callable
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.services.browser_bridge.models import SearchEngineHit


DEFAULT_HEADERS = {
    "accept-language": "zh-CN,zh;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def build_provider_urls(
    keyword: str,
    *,
    target_domain: str,
    provider_order: list[str],
    query_site_path: str = "",
) -> list[tuple[str, str]]:
    """Build no-API search provider URLs for a site-scoped query."""
    site = f"{target_domain}{query_site_path}".strip()
    query = quote_plus(f"site:{site} {keyword}")
    urls: list[tuple[str, str]] = []
    for provider in provider_order:
        if provider == "duckduckgo_html":
            urls.append((provider, f"https://html.duckduckgo.com/html/?q={query}"))
        elif provider == "duckduckgo_lite":
            urls.append((provider, f"https://lite.duckduckgo.com/lite/?q={query}"))
        elif provider == "bing_html":
            urls.append((provider, f"https://www.bing.com/search?q={query}"))
        elif provider == "bing_cn":
            urls.append((provider, f"https://cn.bing.com/search?q={query}"))
    return urls


def normalize_search_engine_url(
    href: str,
    *,
    target_domain: str,
    url_patterns: list[str],
) -> str:
    """Normalize direct, DuckDuckGo, Bing, and Google search-result URLs."""
    if not href:
        return ""
    href = _unwrap_redirect_url(href)
    href = unquote(href)
    matched_pattern = _matched_pattern(href, target_domain, url_patterns)
    if not matched_pattern:
        return ""
    match = re.search(_target_url_regex(target_domain, matched_pattern), href)
    if not match:
        return ""
    parsed = urlparse(match.group(0))
    return urlunparse(parsed._replace(scheme="https", netloc=target_domain))


def parse_search_engine_results(
    html: str,
    *,
    provider: str,
    target_domain: str,
    url_patterns: list[str],
) -> list[SearchEngineHit]:
    """Extract matching target URLs from a search-engine result page."""
    soup = BeautifulSoup(html or "", "html.parser")
    candidates: list[tuple[str, str]] = []
    for anchor in soup.find_all("a"):
        href = str(anchor.get("href", "") or "")
        title = " ".join(anchor.get_text(" ", strip=True).split())
        normalized = normalize_search_engine_url(
            href,
            target_domain=target_domain,
            url_patterns=url_patterns,
        )
        if normalized:
            candidates.append((normalized, title))

    decoded_html = unquote(html or "")
    for pattern in url_patterns:
        regex = _target_url_regex(target_domain, pattern)
        for match in re.findall(regex, decoded_html):
            normalized = normalize_search_engine_url(
                match,
                target_domain=target_domain,
                url_patterns=url_patterns,
            )
            if normalized:
                candidates.append((normalized, ""))

    hits: list[SearchEngineHit] = []
    seen: set[str] = set()
    for url, title in candidates:
        if url in seen:
            continue
        seen.add(url)
        matched = _matched_pattern(url, target_domain, url_patterns)
        hits.append(SearchEngineHit(
            title=title,
            url=url,
            provider=provider,
            rank=len(hits) + 1,
            matched_pattern=matched,
        ))
    return hits


async def search_site(
    keyword: str,
    *,
    target_domain: str,
    url_patterns: list[str],
    provider_order: list[str],
    fetch_text: Callable[[str], Awaitable[str]],
    query_site_path: str = "",
    limit: int = 10,
) -> list[SearchEngineHit]:
    """Search a target site through configured no-API search providers."""
    for provider, url in build_provider_urls(
        keyword,
        target_domain=target_domain,
        provider_order=provider_order,
        query_site_path=query_site_path,
    ):
        html = await fetch_text(url)
        hits = parse_search_engine_results(
            html,
            provider=provider,
            target_domain=target_domain,
            url_patterns=url_patterns,
        )
        if hits:
            return hits[:limit]
    return []


def _unwrap_redirect_url(href: str) -> str:
    if href.startswith("/url?") or href.startswith("https://www.google.com/url?"):
        parsed = urlparse(urljoin("https://www.google.com", href))
        return parse_qs(parsed.query).get("q", [""])[0]
    if "duckduckgo.com/l/?" in href or href.startswith("//duckduckgo.com/l/?") or href.startswith("/l/?"):
        parsed = urlparse(urljoin("https://duckduckgo.com", href))
        return parse_qs(parsed.query).get("uddg", [""])[0]
    if href.startswith("/ck/a") or "bing.com/ck/a" in href:
        parsed = urlparse(urljoin("https://www.bing.com", href))
        encoded = parse_qs(parsed.query).get("u", [""])[0]
        if encoded.startswith("a1"):
            try:
                padded = encoded[2:] + "=" * (-len(encoded[2:]) % 4)
                return base64.urlsafe_b64decode(padded).decode("utf-8", errors="ignore")
            except Exception:
                return encoded
    return href


def _matched_pattern(value: str, target_domain: str, url_patterns: list[str]) -> str:
    for pattern in url_patterns:
        if re.search(_target_url_regex(target_domain, pattern), value):
            return pattern
    return ""


def _target_url_regex(target_domain: str, pattern: str) -> str:
    domain = re.escape(target_domain)
    clean_pattern = pattern.lstrip("^")
    return rf"https?://{domain}{clean_pattern}"
