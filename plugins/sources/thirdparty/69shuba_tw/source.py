"""Plugin for 69書吧繁體 (69shuba.tw)."""

import re
from urllib.parse import quote_plus, urljoin

from app.source_plugins.challenges import looks_like_any_challenge
from app.source_plugins.errors import BrowserRequired, FetchHttp4xx, FetchNetworkError
from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "69shuba_tw"
    name = "69書吧繁體"
    contract_version = "1.0"
    last_modified = "2026-08-02"
    base_url = "https://69shuba.tw"
    headers = {"accept-language": "zh-TW,zh;q=0.9"}
    explore_defs = [
        {"groupId": "home_recommend", "title": "重磅推薦", "url": "/", "kind": "rank"},
        {"groupId": "home_hot", "title": "熱門書籍", "url": "/", "kind": "rank"},
        {"groupId": "class_xuanhuan", "title": "玄幻", "url": "/fenlei/xuanhuan/{page}/", "kind": "category"},
        {"groupId": "class_wuxia", "title": "仙俠", "url": "/fenlei/wuxia/{page}/", "kind": "category"},
        {"groupId": "class_dushi", "title": "都市", "url": "/fenlei/dushi/{page}/", "kind": "category"},
    ]

    async def _fetch(self, ctx, url: str, **kwargs):
        """Reuse a browser-established Aegis session through stealth HTTP."""
        target_url = urljoin(self.base_url, url)
        headers = {**self.headers, **kwargs.pop("headers", {})}
        wait_ms = kwargs.pop("wait_ms", 2500)
        timeout = kwargs.pop("timeout", 10)
        try:
            return await ctx.access.stealth.fetch_text(
                target_url,
                headers=headers,
                timeout=timeout,
                **kwargs,
            )
        except (BrowserRequired, FetchHttp4xx) as original_error:
            html = await ctx.access.browser.fetch_text(
                target_url,
                headers=headers,
                stage="page_fallback",
                wait_ms=wait_ms,
                timeout=timeout,
                **kwargs,
            )
            if looks_like_any_challenge(html):
                raise original_error
        if not html.strip():
            raise FetchNetworkError(f"browser fetch returned empty document: {target_url}")
        return html

    async def explore_groups(self, ctx):
        return [
            {
                "sourceId": self.id,
                "groupId": item["groupId"],
                "title": self._s(ctx, item["title"]),
                "url": urljoin(self.base_url, item["url"].replace("{page}", "1")),
                "kind": item["kind"],
                "pageable": "{page}" in item["url"],
                "profile": "mobile",
            }
            for item in self.explore_defs
        ]

    async def explore(self, ctx, group_id: str | None = None, page: int = 1):
        group = next((item for item in self.explore_defs if item["groupId"] == group_id), self.explore_defs[0])
        html = await self._fetch(ctx, group["url"].replace("{page}", str(page)))
        if group["url"] == "/":
            return self._parse_home_section(ctx, html, group["groupId"], group["title"])
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

    async def search(self, ctx, keyword: str, page: int):
        search_keyword = ctx.to_traditional(keyword)
        page_path = "/search/" if page <= 1 else f"/search/{page}"
        try:
            html = await self._fetch(
                ctx,
                f"{page_path}?searchkey={quote_plus(search_keyword)}",
                wait_ms=5000,
                timeout=25,
            )
        except Exception:
            return []
        try:
            items = self._parse_search(ctx, html)
        except Exception:
            return []
        exact = [item for item in items if keyword and keyword in item.get("name", "")]
        result = exact or items
        if result:
            return await enrich_search_items_from_detail(self, ctx, result, timeout=35.0)
        return []

    def _parse_home_section(self, ctx, html: str, group_id: str, group_title: str):
        sections = ctx.select(html, ".s_m")
        selected = []
        for section in sections:
            title = ctx.text(section, ".q_top p") or ctx.text(section, ".q_top")
            if title == group_title or self._s(ctx, title) == self._s(ctx, group_title):
                selected = [section]
                break
        items = []
        for section in selected:
            items.extend(self._parse_book_cards(ctx, section, group_id, group_title))
            for a in ctx.select(section, ".s_list a"):
                item = self._item_from_list_link(ctx, a, group_id, group_title)
                if item:
                    items.append(item)
        return self._dedupe(items)

    def _parse_book_list(self, ctx, html_or_node, group_id: str, group_title: str):
        items = self._parse_book_cards(ctx, html_or_node, group_id, group_title)
        for a in ctx.select(html_or_node, ".s_list a"):
            item = self._item_from_list_link(ctx, a, group_id, group_title)
            if item:
                items.append(item)
        return self._dedupe(items)

    def _parse_book_cards(self, ctx, html_or_node, group_id: str, group_title: str):
        items = []
        for index, row in enumerate(ctx.select(html_or_node, ".sort_top"), start=1):
            title_node = ctx.select(row, "a.s_title")
            if not title_node:
                continue
            title_text = ctx.clean_text(title_node[0].text_content())
            container_text = ctx.clean_text(ctx.text(row))
            author = ""
            if " / " in container_text:
                author = container_text.split(" / ", 1)[1].split(" ", 1)[0]
            href = title_node[0].get("href", "")
            cover = ctx.attr(row, "img", "src")
            items.append({
                "sourceId": self.id,
                "name": self._s(ctx, title_text),
                "author": self._s(ctx, author),
                "bookUrl": urljoin(self.base_url, href),
                "coverUrl": self._absolute_asset(cover),
                "intro": self._s(ctx, ctx.text(row, ".s_intro")),
                "kind": self._s(ctx, group_title),
                "lastChapter": "",
                "groupId": group_id,
                "groupTitle": group_title,
                "rank": index,
            })
        return items

    def _item_from_list_link(self, ctx, a, group_id: str, group_title: str):
        href = a.get("href", "")
        text = ctx.clean_text(a.text_content())
        if not href or "/book/" not in href or not text:
            return None
        author = ""
        name = text
        if "：《" in text and text.endswith("》"):
            author, name = text.split("：《", 1)
            name = name[:-1]
        elif ":" in text:
            author, name = text.split(":", 1)
        return {
            "sourceId": self.id,
            "name": self._s(ctx, name),
            "author": self._s(ctx, author),
            "bookUrl": urljoin(self.base_url, href),
            "coverUrl": "",
            "intro": "",
            "kind": self._s(ctx, group_title),
            "lastChapter": "",
            "groupId": group_id,
            "groupTitle": group_title,
            "rank": 0,
        }

    def _parse_search(self, ctx, html: str):
        items = []
        rows = (
            ctx.select(html, ".list-item")
            or ctx.select(html, "table.list-item")
            or ctx.select(html, ".search_list li")
            or ctx.select(html, ".result-item")
        )
        for index, row in enumerate(rows, start=1):
            links = [
                a for a in ctx.select(row, 'a[href*="/book/"]')
                if ctx.clean_text(a.text_content())
            ]
            if not links:
                continue
            title_link = links[0]
            name = ctx.clean_text(title_link.text_content())
            if not name:
                continue
            author_line = ctx.text(row, ".mr15")
            author = author_line.replace("作者:", "").strip()
            cover = ctx.attr(row, "img", "src")
            intro = ctx.text(row, ".article a .fs12") or ctx.text(row, ".article .fs12")
            items.append({
                "sourceId": self.id,
                "name": self._s(ctx, name),
                "author": self._s(ctx, author),
                "bookUrl": urljoin(self.base_url, title_link.get("href", "")),
                "coverUrl": self._absolute_asset(cover),
                "intro": self._s(ctx, intro),
                "kind": "搜索",
                "lastChapter": "",
                "groupId": "search",
                "groupTitle": "搜索",
                "rank": index,
            })
        return items

    async def detail(self, ctx, book_url: str):
        html = await self._fetch(ctx, book_url)
        name = ctx.attr(html, 'meta[property="og:novel:book_name"]', "content") or ctx.text(html, ".bookinfo h1")
        author = ctx.attr(html, 'meta[property="og:novel:author"]', "content")
        intro = ctx.attr(html, 'meta[property="og:description"]', "content") or ctx.text(html, ".intro")
        cover = ctx.attr(html, 'meta[property="og:image"]', "content") or ctx.attr(html, ".bookinfo img", "src")
        kind = ctx.attr(html, 'meta[property="og:novel:category"]', "content")
        status = ctx.attr(html, 'meta[property="og:novel:status"]', "content")
        last = ctx.attr(html, 'meta[property="og:novel:latest_chapter_name"]', "content")
        update_time = ctx.attr(html, 'meta[property="og:novel:update_time"]', "content") or ""
        word_count = self._extract_word_count(ctx.text(html, ".bookinfo .info"))
        toc = ctx.attr(html, '.book-op a[href*="/indexlist/"]', "href") or self._toc_from_book_url(book_url)
        return {
            "sourceId": self.id,
            "name": self._s(ctx, name),
            "author": self._s(ctx, author),
            "bookUrl": book_url,
            "coverUrl": self._absolute_asset(cover),
            "intro": self._s(ctx, intro),
            "kind": self._s(ctx, " / ".join([part for part in [kind, status] if part])),
            "lastChapter": self._s(ctx, last),
            "wordCount": word_count,
            "updateTime": update_time,
            "tocUrl": urljoin(self.base_url, toc),
            "authRequired": False,
        }

    async def toc(self, ctx, toc_url: str):
        chapters = []
        seen: set[str] = set()
        seen_pages: set[str] = set()
        page_url = toc_url
        while page_url and page_url not in seen_pages:
            seen_pages.add(page_url)
            html = await self._fetch(ctx, page_url, headers={"referer": self._book_url_from_toc_url(page_url)})
            page_chapters = self._parse_toc_page(ctx, html, page_url, seen)
            if not page_chapters:
                break
            chapters.extend(page_chapters)
            next_href = self._next_page_href(ctx, html)
            if not next_href:
                break
            next_url = urljoin(page_url, next_href)
            if next_url == page_url:
                break
            page_url = next_url
        for index, chapter in enumerate(chapters, start=1):
            chapter["index"] = index
        return chapters

    def _parse_toc_page(self, ctx, html: str, base_url: str, seen: set[str]):
        chapters = []
        for a in ctx.select(html, '#alllist a[href*="/read/"], .lb_mulu a[href*="/read/"]'):
            href = a.get("href", "")
            title = ctx.clean_text(a.text_content())
            chapter_url = urljoin(base_url, href)
            if not href or not title or chapter_url in seen:
                continue
            seen.add(chapter_url)
            chapters.append({
                "sourceId": self.id,
                "title": self._s(ctx, title),
                "chapterUrl": chapter_url,
                "isVip": False,
                "isLocked": False,
            })
        return chapters

    def _next_page_href(self, ctx, html: str) -> str:
        for a in ctx.select(html, "a"):
            text = ctx.clean_text(a.text_content())
            href = a.get("href", "")
            if text == "下一页" and href:
                return href
        return ""

    def _book_url_from_toc_url(self, toc_url: str) -> str:
        match = re.search(r"/indexlist/(\d+)", toc_url or "")
        return f"{self.base_url}/book/{match.group(1)}/" if match else self.base_url

    async def chapter(self, ctx, chapter_url: str):
        html = await self._fetch(ctx, chapter_url)
        title = ctx.text(html, "#nr_title") or ctx.text(html, "h1")
        title = re.sub(r"\s*[（(]\s*\d+\s*/\s*\d+\s*[）)]\s*$", "", title).strip()
        paragraphs = []
        for p in ctx.select(html, "#nr1 > p"):
            text = ctx.clean_text(p.text_content())
            if text:
                paragraphs.append(text)
        content = "\n\n".join(paragraphs) if paragraphs else ctx.clean_html(ctx.html(html, "#nr1"))
        return {
            "sourceId": self.id,
            "title": self._s(ctx, title),
            "content": self._s(ctx, content),
            "chapterUrl": chapter_url,
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _toc_from_book_url(self, book_url: str):
        book_id = book_url.rstrip("/").split("/")[-1]
        return f"/indexlist/{book_id}/" if book_id else book_url

    def _extract_word_count(self, text: str) -> str:
        marker = "字數："
        if marker not in text:
            return ""
        return text.split(marker, 1)[1].split(" ", 1)[0].strip()

    def _absolute_asset(self, url: str) -> str:
        if not url:
            return ""
        if url.startswith("//"):
            return "https:" + url
        return urljoin(self.base_url, url)

    def _dedupe(self, items):
        seen = set()
        result = []
        for item in items:
            key = item.get("bookUrl") or item.get("name")
            if not key or key in seen:
                continue
            seen.add(key)
            item["rank"] = len(result) + 1
            result.append(item)
        return result

    def _s(self, ctx, value: str) -> str:
        return ctx.to_simplified(value)
