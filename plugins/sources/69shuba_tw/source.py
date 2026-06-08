"""Plugin for 69書吧繁體 (69shuba.tw)."""

from urllib.parse import quote_plus, urljoin

from app.source_plugins.errors import FetchNetworkError, PluginTimeout


class Source:
    id = "69shuba_tw"
    name = "69書吧繁體"
    contract_version = "1.0"
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
        target_url = urljoin(self.base_url, url)
        headers = {**self.headers, **kwargs.pop("headers", {})}
        wait_ms = kwargs.pop("wait_ms", 2500)
        timeout = kwargs.pop("timeout", 25)
        last_error = None
        for attempt in range(2):
            try:
                return await ctx.fetch_text(
                    target_url,
                    headers=headers,
                    browser=True,
                    wait_ms=max(800, wait_ms - attempt * 500),
                    timeout=timeout,
                    **kwargs,
                )
            except (PluginTimeout, FetchNetworkError) as exc:
                last_error = exc
                ctx.trace("browser_fetch_retry", url=target_url, message=f"attempt {attempt + 1} failed: {exc}")
        raise last_error

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

    async def search(self, ctx, keyword: str, page: int):
        search_keyword = ctx.to_traditional(keyword)
        page_path = "/search/" if page <= 1 else f"/search/{page}"
        html = await self._fetch(
            ctx,
            f"{page_path}?searchkey={quote_plus(search_keyword)}",
            wait_ms=1500,
            timeout=25,
        )
        items = self._parse_search(ctx, html)
        exact = [item for item in items if keyword and keyword in item.get("name", "")]
        return exact or items

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
        for index, row in enumerate(ctx.select(html, "table.list-item"), start=1):
            links = [a for a in ctx.select(row, ".article a") if "/book/" in (a.get("href", ""))]
            if not links:
                continue
            title_link = links[0]
            name = ctx.clean_text(title_link.text_content())
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
            "wordCountText": word_count,
            "tocUrl": urljoin(self.base_url, toc),
            "authRequired": False,
        }

    async def toc(self, ctx, toc_url: str):
        html = await self._fetch(ctx, toc_url)
        chapters = []
        for a in ctx.select(html, '#alllist a[href*="/read/"], .lb_mulu a[href*="/read/"]'):
            href = a.get("href", "")
            title = ctx.clean_text(a.text_content())
            if not href or not title:
                continue
            chapters.append({
                "sourceId": self.id,
                "index": len(chapters) + 1,
                "title": self._s(ctx, title),
                "chapterUrl": urljoin(self.base_url, href),
                "isVip": False,
                "isLocked": False,
            })
        return chapters

    async def chapter(self, ctx, chapter_url: str):
        html = await self._fetch(ctx, chapter_url)
        title = ctx.text(html, "#nr_title") or ctx.text(html, "h1")
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
