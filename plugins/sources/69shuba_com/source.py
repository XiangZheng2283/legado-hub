"""Plugin for 69书吧 (69shuba.com).

The archived Reading rules are complete, but the live site currently presents
Cloudflare verification even through the configured proxy. The parser is ready
for browser-cleared HTML and raises CLOUDFLARE_REQUIRED when the challenge page
is returned.
"""

import re
import asyncio
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.source_plugins.challenges import looks_like_cloudflare_challenge
from app.source_plugins.errors import BrowserRequired, CloudflareRequired, FetchHttp4xx, FetchHttp5xx, FetchNetworkError, PluginTimeout


class Source:
    id = "69shuba_com"
    name = "69书吧"
    contract_version = "1.0"
    base_url = "https://www.69shuba.com"
    base_urls = ["https://www.69shuba.com", "https://www.69shuba.cx"]
    headers = {"accept-language": "zh-CN,zh;q=0.9"}
    impersonate = "chrome120"
    explore_defs = [
        {"groupId": "newhot", "title": "新书热榜", "url": "/newhot_0_1_{page}.htm", "kind": "rank"},
        {"groupId": "recent", "title": "最近更新", "url": "/newhot_0_2_{page}.htm", "kind": "new"},
        {"groupId": "weekvisit", "title": "总人气榜", "url": "/weekvisit_0_0_{page}.htm", "kind": "rank"},
        {"groupId": "allvote", "title": "总推荐榜", "url": "/allvote_0_0_{page}.htm", "kind": "rank"},
        {"groupId": "class_all", "title": "全部分类", "url": "/novels/class/0.htm", "kind": "category"},
    ]

    async def _fetch(self, ctx, url: str, **kwargs):
        html, _ = await self._fetch_with_url(ctx, url, **kwargs)
        return html

    async def _fetch_with_url(self, ctx, url: str, **kwargs):
        attempted: list[str] = []
        first_cloudflare: CloudflareRequired | None = None
        first_browser_required: BrowserRequired | None = None
        last_error: Exception | None = None
        headers = {**self.headers, **kwargs.pop("headers", {})}
        for candidate_url in self._candidate_urls(url):
            attempted.append(candidate_url)
            try:
                html = await ctx.fetch_text(
                    candidate_url,
                    headers=headers,
                    impersonate=self.impersonate,
                    **kwargs,
                )
                if looks_like_cloudflare_challenge(html):
                    raise CloudflareRequired("69shuba returned Cloudflare verification page", url=candidate_url)
                return html, candidate_url
            except CloudflareRequired as exc:
                first_cloudflare = first_cloudflare or exc
                last_error = exc
                browser_html = await self._try_browser_fetch(ctx, candidate_url, headers=headers, **kwargs)
                if browser_html is not None:
                    return browser_html, candidate_url
                browser_error = getattr(ctx, "_last_69shuba_browser_error", None)
                if isinstance(browser_error, BrowserRequired):
                    first_browser_required = first_browser_required or browser_error
                continue
            except (FetchNetworkError, FetchHttp4xx, FetchHttp5xx, PluginTimeout) as exc:
                last_error = exc
                browser_html = await self._try_browser_fetch(ctx, candidate_url, headers=headers, **kwargs)
                if browser_html is not None:
                    return browser_html, candidate_url
                browser_error = getattr(ctx, "_last_69shuba_browser_error", None)
                if isinstance(browser_error, BrowserRequired):
                    first_browser_required = first_browser_required or browser_error
                continue
        if first_browser_required is not None:
            message = f"{first_browser_required}; attempted domains: {', '.join(attempted)}"
            raise BrowserRequired(message, url=first_browser_required.url or attempted[0])
        if first_cloudflare is not None:
            message = f"{first_cloudflare}; attempted domains: {', '.join(attempted)}"
            raise CloudflareRequired(message, url=first_cloudflare.url or attempted[0])
        if last_error is not None:
            raise last_error
        raise FetchNetworkError(f"no reachable 69shuba domain for url: {url}")

    async def _try_browser_fetch(self, ctx, url: str, **kwargs):
        if getattr(ctx, "_browser_fetcher", None) is None:
            return None
        try:
            html = await ctx.fetch_text(url, browser=True, wait_ms=5000, **kwargs)
            if looks_like_cloudflare_challenge(html):
                raise BrowserRequired("69shuba browser verification required", url=url)
            return html
        except BrowserRequired as exc:
            setattr(ctx, "_last_69shuba_browser_error", exc)
            return None
        except Exception as exc:
            setattr(ctx, "_last_69shuba_browser_error", exc)
            return None

    def _candidate_urls(self, url: str) -> list[str]:
        parsed = urlparse(url)
        if not parsed.netloc:
            url = urljoin(self.base_url, url)
            parsed = urlparse(url)
        candidates = [url]
        for base in self.base_urls:
            base_parsed = urlparse(base)
            replaced = urlunparse(parsed._replace(scheme=base_parsed.scheme, netloc=base_parsed.netloc))
            if replaced not in candidates:
                candidates.append(replaced)
        return candidates

    async def explore_groups(self, ctx):
        return [
            {
                "sourceId": self.id,
                "groupId": item["groupId"],
                "title": item["title"],
                "url": urljoin(self.base_url, item["url"].replace("{page}", "1")),
                "kind": item["kind"],
                "pageable": "{page}" in item["url"],
                "profile": "primary",
            }
            for item in self.explore_defs
        ]

    async def explore(self, ctx, group_id: str | None = None, page: int = 1):
        group = next((item for item in self.explore_defs if item["groupId"] == group_id), self.explore_defs[0])
        url = urljoin(self.base_url, group["url"].replace("{page}", str(page)))
        html, fetched_url = await self._fetch_with_url(ctx, url)
        return self._parse_book_list(ctx, html, group["groupId"], group["title"], base_url=fetched_url)

    async def search(self, ctx, keyword: str, page: int):
        search_url = f"{self.base_url}/modules/article/search.php"
        if not self._has_clearance_cookie(ctx):
            if getattr(ctx, "allow_search_engine_fallback", False):
                try:
                    fallback_items = await asyncio.wait_for(self._search_engine_fallback(ctx, keyword), timeout=10.0)
                except Exception:
                    fallback_items = []
                if fallback_items:
                    return fallback_items
            raise BrowserRequired("69shuba search requires browser verification cookies", url=search_url)
        try:
            html, fetched_url = await self._fetch_with_url(
                ctx,
                search_url,
                method="POST",
                data={"searchkey": keyword, "searchtype": "all", "submit": "Search"},
                timeout=5,
            )
            return self._parse_book_list(ctx, html, "search", "搜索", base_url=fetched_url)
        except PluginTimeout as exc:
            raise BrowserRequired("69shuba search timed out and likely requires browser verification", url=search_url) from exc
        except (BrowserRequired, CloudflareRequired, FetchHttp4xx) as exc:
            try:
                fallback_items = await asyncio.wait_for(self._search_engine_fallback(ctx, keyword), timeout=8.0)
            except Exception:
                fallback_items = []
            if fallback_items:
                return fallback_items
            raise exc

    def _has_clearance_cookie(self, ctx) -> bool:
        for domain in ("69shuba.com", "www.69shuba.com", "69shuba.cx", "www.69shuba.cx"):
            jar = ctx.cookies.get(domain) or {}
            if "cf_clearance" in jar:
                return True
        return False

    async def _search_engine_fallback(self, ctx, keyword: str):
        try:
            hits = await ctx.browser.search_engine(
                keyword,
                target_domain="www.69shuba.com",
                url_patterns=[r"/(?:book|txt)/\d+\.htm"],
                provider_order=["duckduckgo_html", "duckduckgo_lite", "bing_html", "bing_cn"],
                query_site_path="/book",
                timeout=5,
                proxy=False,
            )
        except Exception as exc:
            ctx.trace("search_engine_fallback_error", message=str(exc))
            return []
        items = []
        for hit in hits:
            title = self._clean_search_engine_title(hit.title, keyword)
            items.append({
                "sourceId": self.id,
                "name": title,
                "author": "",
                "bookUrl": hit.url,
                "coverUrl": "",
                "intro": "搜索引擎 fallback 命中，详情和章节仍需目标站验证通过后读取。",
                "kind": "搜索引擎",
                "lastChapter": "",
                "groupId": "search",
                "groupTitle": "搜索",
                "rank": len(items) + 1,
                "extra": {
                    "fallback": "search_engine",
                    "provider": hit.provider,
                    "matchedPattern": hit.matched_pattern,
                },
            })
        return items

    def _clean_search_engine_title(self, text: str, keyword: str) -> str:
        title = re.sub(r"\s*[-_].*$", "", text or "").strip()
        title = re.sub(r"(无弹窗|最新章节阅读|txt全集下载).*$", "", title).strip(" ，,、-_|")
        return title or keyword

    def _parse_book_list(self, ctx, html: str, group_id: str, group_title: str, base_url: str | None = None):
        base_url = base_url or self.base_url
        rows = ctx.select(html, "#article_list_content li") or ctx.select(html, ".newbox li")
        items = []
        for index, row in enumerate(rows, start=1):
            name_node = ctx.select(row, "h3 a")
            if not name_node:
                continue
            name = ctx.clean_text(name_node[0].text_content())
            href = name_node[0].get("href", "")
            cover = ctx.attr(row, "img", "data-src") or ctx.attr(row, "img", "src")
            labels = [ctx.clean_text(label.text_content()) for label in ctx.select(row, "label")]
            author = labels[0] if labels else ""
            kind = " / ".join(labels[1:]) if len(labels) > 1 else group_title
            intro = ctx.text(row, ".ellipsis_2") or ctx.text(row, "ol")
            latest = ctx.text(row, ".zxzj a") or ctx.text(row, ".zxzj")
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": author,
                "bookUrl": urljoin(base_url, href),
                "coverUrl": urljoin(base_url, cover) if cover else "",
                "intro": intro,
                "kind": kind,
                "lastChapter": latest,
                "groupId": group_id,
                "groupTitle": group_title,
                "rank": index,
            })
        return items

    async def detail(self, ctx, book_url: str):
        html, fetched_url = await self._fetch_with_url(ctx, book_url)
        name = ctx.attr(html, 'meta[property="og:novel:book_name"]', "content") or ctx.text(html, ".booknav2 h1")
        author = ctx.attr(html, 'meta[property="og:novel:author"]', "content") or ctx.text(html, ".booknav2 p:nth-of-type(1) a")
        intro = ctx.attr(html, 'meta[property="og:description"]', "content") or ctx.text(html, ".navtxt")
        cover = ctx.attr(html, 'meta[property="og:image"]', "content") or ctx.attr(html, ".bookimg2 img", "src")
        kind = ctx.attr(html, 'meta[property="og:novel:category"]', "content")
        status = ctx.attr(html, 'meta[property="og:novel:status"]', "content")
        last = ctx.attr(html, 'meta[property="og:novel:latest_chapter_name"]', "content")
        toc = ctx.attr(html, 'a[class$="more-btn"]', "href") or book_url.replace(".htm", "/")
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": fetched_url,
            "coverUrl": urljoin(fetched_url, cover) if cover else "",
            "intro": intro,
            "kind": " / ".join([part for part in [kind, status] if part]),
            "lastChapter": last,
            "tocUrl": urljoin(fetched_url, toc),
            "authRequired": False,
        }

    async def toc(self, ctx, toc_url: str):
        html, fetched_url = await self._fetch_with_url(ctx, toc_url)
        links = ctx.select(html, "#catalog li a") or ctx.select(html, ".catalog li a")
        chapters = []
        for a in links:
            href = a.get("href", "")
            title = ctx.clean_text(a.text_content())
            if not href or not title:
                continue
            chapters.append({
                "sourceId": self.id,
                "index": len(chapters) + 1,
                "title": title,
                "chapterUrl": urljoin(fetched_url, href),
                "isVip": False,
                "isLocked": False,
            })
        return list(reversed(chapters))

    async def chapter(self, ctx, chapter_url: str):
        html, fetched_url = await self._fetch_with_url(
            ctx,
            chapter_url,
            headers={"referer": self._chapter_referer(chapter_url)},
        )
        title = ctx.text(html, "h1")
        content = ctx.html(html, ".txtnav") or ctx.html(html, "#content")
        content = self._clean_chapter_html(ctx, content)
        return {
            "sourceId": self.id,
            "title": title,
            "content": content,
            "chapterUrl": fetched_url,
            "format": "html",
            "authRequired": False,
            "isPaid": False,
        }

    def _clean_chapter_html(self, ctx, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for selector in [
            "h1",
            "script",
            "style",
            "#txtright",
            ".txtinfo",
            ".contentadv",
            ".bottom-ad",
        ]:
            for node in soup.select(selector):
                node.decompose()
        content = ctx.clean_html(str(soup))
        content = re.sub(r"\(本章完\)|\ue5e5|loadAdv\(\d+,\d+\);", "", content)
        content = re.sub(r"(?m)^.*(?:新69书吧|69书吧|阅读sto55|爱75奇书屋).*$", "", content)
        content = re.sub(r"\n{3,}", "\n\n", content)
        return content.strip()

    def _chapter_referer(self, chapter_url: str) -> str:
        parsed = urlparse(chapter_url)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 3 and parts[0] == "txt":
            return urlunparse(parsed._replace(path=f"/book/{parts[1]}/", query="", fragment=""))
        return self.base_url
