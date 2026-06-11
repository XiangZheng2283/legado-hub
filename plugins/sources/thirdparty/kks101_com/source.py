"""Plugin for 101看书 (101kks.com)."""

import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from app.source_plugins.challenges import looks_like_browser_challenge, looks_like_cloudflare_challenge
from app.source_plugins.errors import BrowserRequired, CloudflareRequired
from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "kks101_com"
    name = "101看书网"
    contract_version = "1.0"
    last_modified = "2026-06-10"
    base_url = "https://101kks.com"
    headers = {"accept-language": "zh-TW,zh;q=0.9"}
    impersonate = "chrome120"
    explore_defs = [
        {"groupId": "hot", "title": "排行榜", "url": "/novels/hot", "kind": "rank"},
        {"groupId": "full", "title": "完本小說", "url": "/novels/full", "kind": "full"},
        {"groupId": "class_xuanhuan", "title": "玄幻奇幻", "url": "/novels/class/1_1.html", "kind": "category"},
        {"groupId": "class_wuxia", "title": "武俠仙俠", "url": "/novels/class/2_1.html", "kind": "category"},
    ]

    async def _fetch(self, ctx, url: str, **kwargs):
        """Fetch via stealth (curl_cffi).

        The search path falls back to browser access only when stealth hits
        a browser or Cloudflare challenge.
        """
        headers = {**self.headers, **kwargs.pop("headers", {})}
        return await ctx.access.stealth.fetch_text(
            url,
            headers=headers,
            **kwargs,
        )

    def _s(self, ctx, value: str) -> str:
        """Convert Traditional Chinese output text to Simplified Chinese."""
        return ctx.to_simplified(value)

    async def explore_groups(self, ctx):
        return [
            {
                "sourceId": self.id,
                "groupId": item["groupId"],
                "title": self._s(ctx, item["title"]),
                "url": urljoin(self.base_url, item["url"]),
                "kind": item["kind"],
                "pageable": item["url"].endswith("_1.html"),
                "profile": "primary",
            }
            for item in self.explore_defs
        ]

    async def explore(self, ctx, group_id: str | None = None, page: int = 1):
        group = next((item for item in self.explore_defs if item["groupId"] == group_id), self.explore_defs[0])
        path = group["url"].replace("_1.html", f"_{page}.html")
        html = await self._fetch(ctx, urljoin(self.base_url, path))
        return self._parse_book_list(ctx, html, group["groupId"], group["title"])

    async def _search_from_explore(self, ctx, keyword: str):
        matched = []
        for group in self.explore_defs[:4]:
            try:
                items = await self.explore(ctx, group["groupId"], 1)
            except Exception:
                continue
            matched.extend(item for item in items if keyword and keyword in item.get("name", ""))
            if matched:
                break
        return matched

    async def _browser_search_html(self, ctx, search_keyword: str) -> str:
        try:
            html = await ctx.access.browser.fetch_text(
                f"{self.base_url}/search",
                method="POST",
                data={"searchkey": search_keyword, "searchtype": "all"},
                headers=self.headers,
                stage="search",
                wait_ms=3000,
                timeout_ms=45000,
            )
            return html or ""
        except Exception as exc:
            ctx.trace("browser_search_error", url=f"{self.base_url}/search", message=str(exc))
            return ""

    def _looks_like_challenge(self, html: str) -> bool:
        return looks_like_cloudflare_challenge(html) or looks_like_browser_challenge(html)

    async def _fallback_after_challenge(self, ctx, keyword: str, search_keyword: str):
        html = await self._browser_search_html(ctx, search_keyword)
        if html:
            items = self._items_from_search_html(ctx, html, keyword)
            if items:
                return items
        return await self._search_from_explore(ctx, keyword)

    def _detail_page_search_item(self, ctx, html: str) -> dict | None:
        name = ctx.attr(html, 'meta[property="og:novel:book_name"]', "content") or ctx.attr(html, 'meta[property="og:title"]', "content")
        book_url = ctx.attr(html, 'meta[property="og:url"]', "content")
        if not name or not book_url:
            return None
        author = ctx.attr(html, 'meta[property="og:novel:author"]', "content")
        cover = ctx.attr(html, 'meta[property="og:image"]', "content")
        intro = ctx.attr(html, 'meta[property="og:description"]', "content") or ctx.attr(html, 'meta[name="description"]', "content")
        kind = ctx.attr(html, 'meta[property="og:novel:category"]', "content")
        status = ctx.attr(html, 'meta[property="og:novel:status"]', "content")
        latest = ctx.attr(html, 'meta[property="og:novel:latest_chapter_name"]', "content")
        update_time = ctx.attr(html, 'meta[property="og:novel:update_time"]', "content")
        return {
            "sourceId": self.id,
            "name": self._s(ctx, name),
            "author": self._s(ctx, author),
            "bookUrl": book_url,
            "coverUrl": cover,
            "intro": self._s(ctx, intro),
            "kind": self._s(ctx, " / ".join([part for part in [kind, status] if part])),
            "lastChapter": self._s(ctx, latest),
            "updateTime": update_time,
        }

    async def search(self, ctx, keyword: str, page: int):
        if page > 1:
            return []
        search_keyword = ctx.to_traditional(keyword)
        try:
            html = await self._fetch(
                ctx,
                f"{self.base_url}/search",
                method="POST",
                data={"searchkey": search_keyword, "searchtype": "all"},
            )
        except (BrowserRequired, CloudflareRequired):
            return await enrich_search_items_from_detail(self, ctx, await self._fallback_after_challenge(ctx, keyword, search_keyword))
        except Exception:
            try:
                html = await self._fetch(
                    ctx,
                    f"{self.base_url}/search",
                    params={"searchkey": search_keyword, "searchtype": "all"},
                )
            except (BrowserRequired, CloudflareRequired):
                return await enrich_search_items_from_detail(self, ctx, await self._fallback_after_challenge(ctx, keyword, search_keyword))
            except Exception:
                return await enrich_search_items_from_detail(self, ctx, await self._search_from_explore(ctx, keyword))
        if self._looks_like_challenge(html):
            return await enrich_search_items_from_detail(self, ctx, await self._fallback_after_challenge(ctx, keyword, search_keyword))
        items = self._items_from_search_html(ctx, html, keyword)
        if items:
            return await enrich_search_items_from_detail(self, ctx, items)
        return await enrich_search_items_from_detail(self, ctx, await self._search_from_explore(ctx, keyword))

    def _items_from_search_html(self, ctx, html: str, keyword: str):
        items = self._parse_book_list(ctx, html, "search", "搜索")
        matched = [item for item in items if keyword in item.get("name", "")]
        if matched:
            return matched
        if items:
            return items
        detail_item = self._detail_page_search_item(ctx, html)
        if detail_item:
            return [detail_item]
        return []

    def _parse_book_list(self, ctx, html: str, group_id: str, group_title: str):
        rows = ctx.select(html, "#article_list_content li") or ctx.select(html, ".newbox li") or ctx.select(html, ".booklist li")
        items = []
        for index, row in enumerate(rows, start=1):
            name_node = ctx.select(row, "h3 a")
            if not name_node:
                continue
            name = ctx.clean_text(name_node[0].text_content())
            href = name_node[0].get("href", "")
            cover = ctx.attr(row, ".imgbox img", "data-src") or ctx.attr(row, ".imgbox img", "src")
            labels = [ctx.clean_text(label.text_content()) for label in ctx.select(row, ".labelbox label")]
            author = labels[0] if labels else ""
            kind = " / ".join(labels[1:]) if len(labels) > 1 else group_title
            intro = ctx.text(row, ".ellipsis_2")
            latest = ctx.text(row, ".zxzj a")
            items.append({
                "sourceId": self.id,
                "name": self._s(ctx, name),
                "author": self._s(ctx, author),
                "bookUrl": urljoin(self.base_url, href),
                "coverUrl": urljoin(self.base_url, cover) if cover else "",
                "intro": self._s(ctx, intro),
                "kind": self._s(ctx, kind),
                "lastChapter": self._s(ctx, latest),
                "groupId": group_id,
                "groupTitle": group_title,
                "rank": index,
            })
        return items

    async def detail(self, ctx, book_url: str):
        html = await self._fetch(ctx, book_url)
        name = ctx.attr(html, 'meta[property="og:novel:book_name"]', "content") or ""
        author = ctx.attr(html, 'meta[property="og:novel:author"]', "content") or ""
        intro = ctx.attr(html, 'meta[property="og:description"]', "content") or ""
        cover = ctx.attr(html, 'meta[property="og:image"]', "content") or ""
        kind = ctx.attr(html, 'meta[property="og:novel:category"]', "content") or ""
        status = ctx.attr(html, 'meta[property="og:novel:status"]', "content") or ""
        last = ctx.attr(html, 'meta[property="og:novel:latest_chapter_name"]', "content") or ""
        update_time = ctx.attr(html, 'meta[property="og:novel:update_time"]', "content") or ""

        if not name:
            name = ctx.text(html, "h1")
        if not author:
            author_text = ctx.text(html, ".booknav2 p:nth-of-type(1)")
            author = re.sub(r"^作者：", "", author_text).strip()
        if not kind:
            kind_text = ctx.text(html, ".booknav2 p:nth-of-type(2)")
            kind = re.sub(r"^分類：", "", kind_text).strip()
        if not status:
            info_text = ctx.text(html, ".booknav2 p:nth-of-type(3)")
            if "連載" in info_text:
                status = "連載"
            elif "完結" in info_text:
                status = "完結"
        if not cover:
            cover = ctx.attr(html, ".bookimg2 img", "src")
        if not intro:
            intro_node = ctx.select(html, ".navtxt p")
            if intro_node:
                intro = ctx.clean_text(intro_node[0].text_content())

        # 清理简介中的SEO关键词
        intro = re.sub(r"小說關鍵詞：.*$", "", intro, flags=re.DOTALL).strip()
        intro = re.sub(r"\n{3,}", "\n\n", intro).strip()

        toc = ctx.attr(html, 'a.more-btn', "href")
        if not toc:
            m = re.search(r"/book/(\d+)\.html", book_url)
            if m:
                toc = f"{self.base_url}/book/{m.group(1)}/index.html"

        return {
            "sourceId": self.id,
            "name": self._s(ctx, name),
            "author": self._s(ctx, author),
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, cover) if cover else "",
            "intro": self._s(ctx, intro),
            "kind": self._s(ctx, " / ".join([p for p in [kind, status] if p])),
            "lastChapter": self._s(ctx, last),
            "wordCount": "",
            "updateTime": update_time,
            "tocUrl": toc,
            "authRequired": False,
            "extra": {
                "status": status,
            },
        }

    async def toc(self, ctx, toc_url: str):
        html = await self._fetch_complete_toc_html(ctx, toc_url)
        links = ctx.select(html, "#allchapter li a") or ctx.select(html, ".catalog li a") or ctx.select(html, "li a")
        chapters = []
        for a in links:
            href = a.get("href", "")
            title = ctx.clean_text(a.text_content())
            if not href or not title or href == "#":
                continue
            chapters.append({
                "sourceId": self.id,
                "index": len(chapters) + 1,
                "title": self._s(ctx, title),
                "chapterUrl": urljoin(toc_url, href),
                "isVip": False,
                "isLocked": False,
            })
        return chapters

    async def _fetch_complete_toc_html(self, ctx, toc_url: str) -> str:
        html = ""
        ajax_url = self._chapterlist_url(toc_url)
        ajax_html = ""
        if ajax_url:
            ajax_html = await self._fetch_toc_ajax_html(ctx, ajax_url, toc_url)
        try:
            html = await self._fetch(ctx, toc_url)
        except (BrowserRequired, CloudflareRequired):
            if ajax_html and ctx.select(ajax_html, "li a"):
                return ajax_html
            raise
        except Exception as exc:
            if ajax_html and ctx.select(ajax_html, "li a"):
                ctx.trace("toc_static_fallback_to_ajax", url=toc_url, message=str(exc))
                return ajax_html
            raise
        extracted_ajax_url = self._extract_chapterlist_url(html, toc_url)
        if extracted_ajax_url and extracted_ajax_url != ajax_url:
            extracted_html = await self._fetch_toc_ajax_html(ctx, extracted_ajax_url, toc_url)
            if extracted_html and len(ctx.select(extracted_html, "li a")) > len(ctx.select(html, "#allchapter li a")):
                return extracted_html
        if not ajax_url:
            return html
        if ajax_html and len(ctx.select(ajax_html, "li a")) > len(ctx.select(html, "#allchapter li a")):
            return ajax_html
        return html

    async def _fetch_toc_ajax_html(self, ctx, ajax_url: str, referer: str) -> str:
        try:
            return await self._fetch(ctx, ajax_url, headers={"referer": referer})
        except (BrowserRequired, CloudflareRequired):
            return await self._browser_fetch_toc_html(ctx, ajax_url)
        except Exception as exc:
            ctx.trace("toc_ajax_fallback", url=ajax_url, message=str(exc))
            return ""

    async def _browser_fetch_toc_html(self, ctx, url: str) -> str:
        try:
            return await ctx.access.browser.fetch_text(
                url,
                headers=self.headers,
                stage="toc",
                wait_ms=1200,
                timeout_ms=45000,
            )
        except Exception as exc:
            ctx.trace("browser_toc_error", url=url, message=str(exc))
            return ""

    def _chapterlist_url(self, toc_url: str) -> str:
        match = re.search(r"/book/(\d+)", toc_url or "")
        if not match:
            return ""
        return f"{self.base_url}/ajax_novels/chapterlist/{match.group(1)}.html"

    def _extract_chapterlist_url(self, html: str, base_url: str) -> str:
        match = re.search(r"""['"]([^'"]*/ajax_novels/chapterlist/\d+\.html)['"]""", html or "")
        if not match:
            return ""
        return urljoin(base_url, match.group(1))

    def _clean_chapter_content(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "iframe", "ins", "center"]):
            tag.decompose()
        for div in soup.find_all("div"):
            text = div.get_text(strip=True)
            if len(text) < 80 and any(kw in text for kw in ["广告", "本章完", "返回目录", "101看書", "101看书", "推薦閱讀", "最新网址"]):
                div.decompose()
        for tag in soup.find_all("br"):
            tag.replace_with("\n")
        paragraphs = []
        for p in soup.find_all("p"):
            text = p.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)
        if paragraphs:
            content = "\n\n".join(paragraphs)
        else:
            text = soup.get_text("\n", strip=True)
            lines = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                if any(kw in line for kw in ["101看書", "101看书", "返回目录", "本章完", "推薦閱讀", "最新网址"]):
                    continue
                lines.append(line)
            content = "\n\n".join(lines)
        content = re.sub(r"\n{3,}", "\n\n", content).strip()
        return self._normalize_chapter_text(content)

    def _normalize_chapter_text(self, content: str, title: str = "") -> str:
        lines = [line.strip() for line in (content or "").splitlines()]
        normalized: list[str] = []
        body_started = False
        for line in lines:
            if not line:
                if normalized and normalized[-1]:
                    normalized.append("")
                continue
            line = re.sub(r"[^\s，。！？!?；;：:]*\.com", "", line, flags=re.IGNORECASE).strip()
            if not line:
                continue
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", line):
                continue
            if re.match(r"^作者[：:]", line):
                continue
            if title and line == title.strip():
                continue
            if not body_started and len(line) <= 6 and re.fullmatch(r"[\u4e00-\u9fffA-Za-z]+", line):
                continue
            if not body_started and len(line) >= 8 and re.search(r"[。！？!?]", line):
                body_started = True
            normalized.append(line)
        while normalized and not normalized[-1]:
            normalized.pop()
        return "\n".join(normalized).replace("\n\n\n", "\n\n").strip()

    async def chapter(self, ctx, chapter_url: str):
        html = await self._fetch(ctx, chapter_url)
        title = ctx.text(html, "h1")
        content = ctx.html(html, ".txtnav") or ctx.html(html, "#content")
        content = self._clean_chapter_content(content)
        content = self._normalize_chapter_text(content, title)
        # 额外清理广告与站点痕迹
        content = re.sub(r"\(本章完\)|\ue5e5|loadAdv\(\d+,\d+\);", "", content)
        content = re.sub(r"101看書|101看书", "", content)
        content = re.sub(r"\n{3,}", "\n\n", content).strip()
        return {
            "sourceId": self.id,
            "title": self._s(ctx, title),
            "content": self._s(ctx, content),
            "chapterUrl": chapter_url,
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }
