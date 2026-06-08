"""Plugin for 台灣小說網 (twkan.com)."""

from urllib.parse import urljoin

from app.source_plugins.errors import BrowserRequired, CloudflareRequired, FetchNetworkError, PluginTimeout


class Source:
    id = "twkan_com"
    name = "台灣小說網"
    contract_version = "1.0"
    base_url = "https://twkan.com"
    headers = {"accept-language": "zh-TW,zh;q=0.9"}
    impersonate = "chrome120"
    explore_defs = [
        {"groupId": "hot", "title": "排行榜", "url": "/novels/hot", "kind": "rank"},
        {"groupId": "full", "title": "完本小說", "url": "/novels/full", "kind": "full"},
        {"groupId": "class_xuanhuan", "title": "玄幻奇幻", "url": "/novels/class/1_1.html", "kind": "category"},
        {"groupId": "class_wuxia", "title": "武俠仙俠", "url": "/novels/class/2_1.html", "kind": "category"},
    ]

    async def _fetch(self, ctx, url: str, **kwargs):
        headers = {**self.headers, **kwargs.pop("headers", {})}
        try:
            return await ctx.fetch_text(
                url,
                headers=headers,
                impersonate=self.impersonate,
                **kwargs,
            )
        except (CloudflareRequired, FetchNetworkError, PluginTimeout) as exc:
            try:
                return await ctx.fetch_text(
                    url,
                    headers=headers,
                    browser=True,
                    wait_ms=7000,
                    **kwargs,
                )
            except BrowserRequired:
                raise
            except Exception:
                raise exc

    async def explore_groups(self, ctx):
        return [
            {
                "sourceId": self.id,
                "groupId": item["groupId"],
                "title": item["title"],
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

    async def search(self, ctx, keyword: str, page: int):
        html = await self._fetch(
            ctx,
            f"{self.base_url}/search",
            method="POST",
            data={"searchkey": keyword, "searchtype": "all"},
        )
        items = self._parse_book_list(ctx, html, "search", "搜索")
        matched = [item for item in items if keyword in item.get("name", "")]
        if matched:
            return matched
        if items:
            return items
        return await self._search_from_explore(ctx, keyword)

    async def _search_from_explore(self, ctx, keyword: str):
        matched = []
        for group in self.explore_defs[:2]:
            for item in await self.explore(ctx, group["groupId"], 1):
                if keyword in item.get("name", ""):
                    matched.append(item)
            if matched:
                break
        return matched

    def _parse_book_list(self, ctx, html: str, group_id: str, group_title: str):
        rows = ctx.select(html, "#article_list_content li") or ctx.select(html, ".newbox li")
        items = []
        for index, row in enumerate(rows, start=1):
            name_node = ctx.select(row, "h3 a")
            if not name_node:
                continue
            name = ctx.clean_text(name_node[0].text_content())
            href = name_node[0].get("href", "")
            cover = ctx.attr(row, "img", "data-src") or ctx.attr(row, "img", "src")
            labels = [ctx.clean_text(label.text_content()) for label in ctx.select(row, ".labelbox label")]
            author = labels[0] if labels else ""
            kind = " / ".join(labels[1:]) if len(labels) > 1 else group_title
            intro = ctx.text(row, ".ellipsis_2")
            latest = ctx.text(row, ".zxzj a") or ctx.text(row, ".zxzj")
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": author,
                "bookUrl": urljoin(self.base_url, href),
                "coverUrl": urljoin(self.base_url, cover) if cover else "",
                "intro": intro,
                "kind": kind,
                "lastChapter": latest,
                "groupId": group_id,
                "groupTitle": group_title,
                "rank": index,
            })
        return items

    async def detail(self, ctx, book_url: str):
        html = await self._fetch(ctx, book_url)
        name = ctx.attr(html, 'meta[property="og:novel:book_name"]', "content") or ctx.text(html, "h1")
        author = ctx.attr(html, 'meta[property="og:novel:author"]', "content") or ctx.text(html, ".booknav2 p:nth-of-type(1) a")
        intro = ctx.attr(html, 'meta[property="og:description"]', "content") or ctx.text(html, ".navtxt")
        cover = ctx.attr(html, 'meta[property="og:image"]', "content") or ctx.attr(html, ".bookimg2 img", "src")
        kind = ctx.attr(html, 'meta[property="og:novel:category"]', "content")
        status = ctx.attr(html, 'meta[property="og:novel:status"]', "content")
        last = ctx.attr(html, 'meta[property="og:novel:latest_chapter_name"]', "content")
        toc = ctx.attr(html, 'meta[property="og:novel:read_url"]', "content")
        if not toc:
            stem = book_url.rsplit(".", 1)[0]
            toc = stem + "/index.html" if not stem.endswith("/index") else book_url
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, cover) if cover else "",
            "intro": intro,
            "kind": " / ".join([part for part in [kind, status] if part]),
            "lastChapter": last,
            "tocUrl": toc,
            "authRequired": False,
        }

    async def toc(self, ctx, toc_url: str):
        html = await self._fetch(ctx, toc_url)
        links = ctx.select(html, ".catalog li a")
        chapters = []
        for a in links:
            href = a.get("href", "")
            title = ctx.clean_text(a.text_content())
            if not href or not title or href == "#":
                continue
            chapters.append({
                "sourceId": self.id,
                "index": len(chapters) + 1,
                "title": title,
                "chapterUrl": urljoin(toc_url, href),
                "isVip": False,
                "isLocked": False,
            })
        return chapters

    async def chapter(self, ctx, chapter_url: str):
        html = await self._fetch(ctx, chapter_url)
        title = ctx.text(html, "h1")
        content = ctx.html(html, ".txtnav")
        content = ctx.clean_html(content)
        return {
            "sourceId": self.id,
            "title": title,
            "content": content,
            "chapterUrl": chapter_url,
            "format": "html",
            "authRequired": False,
            "isPaid": False,
        }
