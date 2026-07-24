"""Plugin for 69书吧 (69shuba.com).

The archived Reading rules are complete, but the live site currently presents
Cloudflare verification even through the configured proxy. The parser is ready
for browser-cleared HTML and raises CLOUDFLARE_REQUIRED when the challenge page
is returned.
"""

import re
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.services.access_bridge.client import AccessBridgeUnavailable
from app.source_plugins.challenges import looks_like_cloudflare_challenge
from app.source_plugins.errors import CloudflareRequired, FetchHttp4xx, FetchHttp5xx, FetchNetworkError, PluginExecutionError, PluginTimeout


class Source:
    id = "69shuba_com"
    name = "69书吧"
    contract_version = "1.0"
    last_modified = "2026-07-25"
    base_url = "https://www.69shuba.com"
    base_urls = ["https://www.69shuba.com", "https://www.69shuba.cx"]
    headers = {"accept-language": "zh-CN,zh;q=0.9"}
    impersonate = "chrome120"

    # Whole-line ads, including obfuscated watermarks like:
    # 无错版本在读！6=9+书_吧首发本小说。
    # 正确内（容在%六九%书'吧读！{
    _AD_LINE_RE = re.compile(
        r"(?m)^.*(?:"
        r"新69书吧|69书吧|"
        r"无错版本在读|"
        r"首发本小说|"
        r"6\s*[=＝]\s*9\s*[+＋]?\s*书[_＿\s]*吧|"
        r"正确内.?容在|"
        r"[%％]\s*六九\s*[%％]|"
        r"书[''′]?\s*吧\s*读|"
        r"阅读sto55|爱75奇书屋"
        r").*$"
    )
    _INLINE_AD_RE = re.compile(
        r"(?:"
        r"无错版本在读[！!]?\s*6\s*[=＝]\s*9\s*[+＋]?\s*书[_＿\s]*吧\s*首发本小说[。．.]?"
        r"|"
        r"正确内[（(]?\s*容在\s*[%％]?\s*六九\s*[%％]?\s*书[''′]?\s*吧\s*读[！!]?\s*[\{｛]?"
        r")"
    )

    @classmethod
    def get_ad_patterns(cls) -> list[str]:
        """Host purify patterns for 69书吧 watermarks (incl. obfuscated)."""
        return [
            r"无错版本在读",
            r"首发本小说",
            r"6\s*[=＝]\s*9\s*[+＋]?\s*书[_＿\s]*吧",
            r"新?69\s*书\s*吧",
            r"正确内.?容在",
            r"[%％]\s*六九\s*[%％]",
            r"书[''′]?\s*吧\s*读",
            r"阅读sto55|爱75奇书屋",
        ]
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
        last_error: Exception | None = None
        headers = {**self.headers, **kwargs.pop("headers", {})}
        for candidate_url in self._candidate_urls(url):
            attempted.append(candidate_url)
            try:
                html = await ctx.access.stealth.fetch_text(
                    candidate_url,
                    headers=headers,
                    **kwargs,
                )
                if looks_like_cloudflare_challenge(html):
                    raise CloudflareRequired("69shuba returned Cloudflare verification page", url=candidate_url)
                return html, candidate_url
            except CloudflareRequired as exc:
                first_cloudflare = first_cloudflare or exc
                last_error = exc
                continue
            except (FetchNetworkError, FetchHttp4xx, FetchHttp5xx, PluginTimeout) as exc:
                last_error = exc
                continue
        if first_cloudflare is not None:
            message = f"{first_cloudflare}; attempted domains: {', '.join(attempted)}"
            raise CloudflareRequired(message, url=first_cloudflare.url or attempted[0])
        if last_error is not None:
            raise last_error
        raise FetchNetworkError(f"no reachable 69shuba domain for url: {url}")

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
        if page > 1:
            return []
        try:
            provider_items = await self._search_provider_search(ctx, keyword)
        except Exception as exc:
            raise PluginExecutionError(f"69shuba search provider bypass failed: {exc}") from exc
        if provider_items:
            return provider_items
        raise PluginExecutionError("69shuba search provider bypass returned no results")

    async def _search_provider_search(self, ctx, keyword: str):
        hits = []
        provider_order = ["duckduckgo_ddgs", "bing_html", "google_html"]
        search_targets = [
            ("www.69shuba.com", "/book"),
        ]
        url_patterns = [r"/(?:book|txt)/\d+\.htm", r"/book/\d+"]
        for target_domain, query_site_path in search_targets:
            try:
                hits = await ctx.access.search_provider(
                    keyword,
                    target_domain=target_domain,
                    url_patterns=url_patterns,
                    provider_order=provider_order,
                    query_site_path=query_site_path,
                    timeout=15,
                )
            except AccessBridgeUnavailable:
                raise
            except Exception as exc:
                ctx.trace(
                    "search_provider_error",
                    message=str(exc),
                    data={"targetDomain": target_domain, "querySitePath": query_site_path},
                )
                continue
            if hits:
                break
        items = []
        seen_urls: set[str] = set()
        for hit in hits:
            title = self._clean_search_provider_title(hit.title, keyword)
            book_url = self._normalize_book_url(hit.url)
            if book_url in seen_urls:
                continue
            seen_urls.add(book_url)
            snippet = (hit.snippet or "").strip()
            intro = snippet if snippet else "搜索提供器命中，详情和章节仍需目标站验证通过后读取。"
            items.append({
                "sourceId": self.id,
                "name": title,
                "author": "",
                "bookUrl": book_url,
                "coverUrl": "",
                "intro": intro,
                "kind": "",
                "lastChapter": "",
                "groupId": "search",
                "groupTitle": "搜索",
                "rank": len(items) + 1,
                "extra": {
                    "searchProvider": "source_access_bridge",
                    "sourceKind": "搜索提供器",
                    "provider": hit.provider,
                    "matchedPattern": hit.matched_pattern,
                    "searchUrl": hit.url,
                },
            })
        # Enrich top results with detail for better field completeness
        if items:
            await self._enrich_search_items(ctx, items[:3])
        return items

    async def _enrich_search_items(self, ctx, items: list[dict]):
        import asyncio
        for item in items:
            try:
                detail = await asyncio.wait_for(self.detail(ctx, item["bookUrl"]), timeout=3.0)
                if detail and detail.get("author"):
                    item["author"] = detail["author"]
                if detail and detail.get("coverUrl"):
                    item["coverUrl"] = detail["coverUrl"]
                if detail and detail.get("lastChapter"):
                    item["lastChapter"] = detail["lastChapter"]
                if detail and detail.get("kind"):
                    item["kind"] = detail["kind"]
                if detail and detail.get("wordCount"):
                    item["wordCount"] = detail["wordCount"]
                if detail and detail.get("updateTime"):
                    item["updateTime"] = detail["updateTime"]
            except Exception:
                pass

    def _clean_search_provider_title(self, text: str, keyword: str) -> str:
        title = re.sub(r"\s*[-_].*$", "", text or "").strip()
        title = re.sub(r"(无弹窗|最新章节阅读|最新章节列表|最新章节|txt全集下载).*$", "", title).strip(" ，,、-_|")
        return title or keyword

    def _normalize_book_url(self, url: str) -> str:
        match = re.search(r"https?://(?:www\.)?69shuba\.(?:com|cx)/book/(\d+)", url or "")
        if not match:
            return url
        parsed = urlparse(url)
        host = parsed.netloc or "www.69shuba.com"
        if host == "69shuba.com":
            host = "www.69shuba.com"
        if host == "69shuba.cx":
            host = "www.69shuba.cx"
        return f"https://{host}/book/{match.group(1)}.htm"

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
        html, fetched_url = await self._fetch_with_url(
            ctx,
            book_url,
            headers={"referer": self._book_detail_referer(book_url)},
        )
        soup = BeautifulSoup(html or "", "html.parser")
        dom_info = self._detail_dom_info(ctx, soup)
        name = self._meta_content(soup, "og:novel:book_name") or ctx.text(html, ".booknav2 h1")
        author = self._meta_content(soup, "og:novel:author") or dom_info.get("author", "")
        intro = self._clean_intro(
            ctx,
            ctx.html(html, ".navtxt")
            or ctx.text(html, ".navtxt")
            or self._meta_content(soup, "og:description")
            or self._meta_content(soup, "description")
        )
        cover = self._meta_content(soup, "og:image") or ctx.attr(html, ".bookimg2 img", "src")
        kind = self._meta_content(soup, "og:novel:category") or dom_info.get("kind", "")
        status = self._meta_content(soup, "og:novel:status") or dom_info.get("status", "")
        last = self._meta_content(soup, "og:novel:latest_chapter_name")
        word_count = dom_info.get("wordCount", "")
        update_time = self._meta_content(soup, "og:novel:update_time") or dom_info.get("updateTime", "")
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
            "wordCount": word_count,
            "updateTime": update_time,
            "tocUrl": urljoin(fetched_url, toc),
            "authRequired": False,
            "extra": {
                "status": status,
            },
        }

    def _meta_content(self, soup: BeautifulSoup, key: str) -> str:
        node = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        return (node.get("content", "") if node else "").strip()

    def _detail_dom_info(self, ctx, soup: BeautifulSoup) -> dict[str, str]:
        info = {"author": "", "kind": "", "status": "", "wordCount": "", "updateTime": ""}
        labels = [ctx.clean_text(node.get_text(" ", strip=True)) for node in soup.select(".booknav2 p")]
        for text in labels:
            if text.startswith("作者："):
                info["author"] = text.replace("作者：", "", 1).strip()
            elif text.startswith("分类："):
                info["kind"] = text.replace("分类：", "", 1).strip()
            elif text.startswith("更新："):
                info["updateTime"] = text.replace("更新：", "", 1).strip()
            elif "字" in text or "连载" in text or "完结" in text:
                parts = [part.strip() for part in re.split(r"[|/]", text) if part.strip()]
                for part in parts:
                    if "字" in part:
                        info["wordCount"] = part
                    elif part in {"连载", "完结", "已完结"}:
                        info["status"] = part
        return info

    def _clean_intro(self, ctx, intro: str) -> str:
        content = ctx.clean_html(intro or "")
        content = re.sub(r"(?m)^小说关键词：.*$", "", content)
        content = re.sub(r"\n{3,}", "\n\n", content)
        return content.strip()

    async def toc(self, ctx, toc_url: str):
        html, fetched_url = await self._fetch_with_url(
            ctx,
            toc_url,
            headers={"referer": self._book_detail_referer(toc_url)},
        )
        links = ctx.select(html, "#catalog li a") or ctx.select(html, ".catalog li a")
        chapters = []
        seen: set[str] = set()
        for a in links:
            href = a.get("href", "")
            title = ctx.clean_text(a.text_content())
            if not href or not title or href in seen:
                continue
            seen.add(href)
            chapters.append({
                "sourceId": self.id,
                "index": len(chapters) + 1,
                "title": title,
                "chapterUrl": urljoin(fetched_url, href),
                "isVip": False,
                "isLocked": False,
            })
        chapters = self._sort_chapters(chapters)
        for i, ch in enumerate(chapters, start=1):
            ch["index"] = i
        return chapters

    def _sort_chapters(self, chapters: list[dict]) -> list[dict]:
        numbered = [(self._chapter_number(item), index, item) for index, item in enumerate(chapters)]
        if any(number > 0 for number, _, _ in numbered):
            return [item for number, _, item in sorted(numbered, key=lambda row: (row[0] <= 0, row[0] or row[1]))]
        return list(reversed(chapters))

    def _chapter_number(self, item: dict) -> int:
        title = item.get("title", "")
        url = item.get("chapterUrl", "")
        match = re.search(r"第\s*(\d+)\s*章", title)
        if match:
            return int(match.group(1))
        match = re.search(r"/txt/\d+/(\d+)", url)
        if match:
            return int(match.group(1))
        return 0

    async def chapter(self, ctx, chapter_url: str):
        html, fetched_url = await self._fetch_with_url(
            ctx,
            chapter_url,
            headers={"referer": self._book_detail_referer(chapter_url)},
        )
        title = ctx.text(html, "h1")
        content = ctx.html(html, ".txtnav") or ctx.html(html, "#content")
        content = self._clean_chapter_html(ctx, content)
        return {
            "sourceId": self.id,
            "title": title,
            "content": content,
            "chapterUrl": fetched_url,
            "format": "text",
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
        # Convert <br> to line breaks before extracting text
        for br in soup.find_all("br"):
            br.replace_with("\n")
        # Prefer <p> tags for paragraph boundaries to preserve line breaks
        def _norm_text(text: str) -> str:
            return " ".join(text.split()) if text else ""
        paragraphs = []
        for p in soup.find_all("p"):
            text = _norm_text(p.get_text(" ", strip=True))
            if text:
                paragraphs.append(text)
        if paragraphs:
            content = "\n\n".join(paragraphs)
        else:
            # If no <p> tags, split on blank lines created by <br>
            text = soup.get_text("\n", strip=True)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            content = "\n\n".join(lines)
        content = re.sub(r"\(本章完\)|\ue5e5|loadAdv\(\d+,\d+\);", "", content)
        content = self._AD_LINE_RE.sub("", content)
        content = self._INLINE_AD_RE.sub("", content)
        content = re.sub(r"\n{3,}", "\n\n", content)
        return content.strip()

    def _book_detail_referer(self, source_url: str) -> str:
        parsed = urlparse(source_url)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] == "book":
            book_id = re.sub(r"\D", "", parts[1])
            if book_id:
                return urlunparse(parsed._replace(path=f"/book/{book_id}.htm", query="", fragment=""))
        if len(parts) >= 3 and parts[0] == "txt":
            book_id = re.sub(r"\D", "", parts[1])
            if book_id:
                return urlunparse(parsed._replace(path=f"/book/{book_id}.htm", query="", fragment=""))
        return self.base_url
