"""Plugin for 书海阁小说网 (shuhaige.net) based on so-novel seed."""

from urllib.parse import urljoin


class Source:
    id = "shuhaige_net"
    name = "书海阁小说网"
    contract_version = "1.0"
    base_url = "https://m.shuhaige.tw"
    explore_url = "https://m.shuhaige.net"
    headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 9) Mobile Safari/537.36"}
    explore_defs = [
        {"groupId": "allvisit", "title": "总点击榜", "url": "/allvisit/{page}.html", "kind": "rank"},
        {"groupId": "monthvisit", "title": "月点击榜", "url": "/monthvisit/{page}.html", "kind": "rank"},
        {"groupId": "weekvisit", "title": "周点击榜", "url": "/weekvisit/{page}.html", "kind": "rank"},
        {"groupId": "goodnew", "title": "新书榜单", "url": "/goodnew/{page}.html", "kind": "new"},
        {"groupId": "shuku_all", "title": "书库全部", "url": "/shuku/0_0_0_{page}.html", "kind": "category"},
    ]

    async def explore_groups(self, ctx):
        return [
            {
                "sourceId": self.id,
                "groupId": item["groupId"],
                "title": item["title"],
                "url": urljoin(self.explore_url, item["url"].replace("{page}", "1")),
                "kind": item["kind"],
                "pageable": True,
                "profile": "mobile_net",
            }
            for item in self.explore_defs
        ]

    async def explore(self, ctx, group_id: str | None = None, page: int = 1):
        group = next((item for item in self.explore_defs if item["groupId"] == group_id), self.explore_defs[0])
        url = urljoin(self.explore_url, group["url"].replace("{page}", str(page)))
        html = await ctx.fetch_text(url, headers=self.headers)
        rows = ctx.select(html, ".list li")
        items = []
        for index, row in enumerate(rows, start=1):
            links = ctx.select(row, "a")
            if len(links) < 2:
                continue
            book_link = links[1]
            name = ctx.clean_text(book_link.text_content())
            href = book_link.get("href", "")
            author = ctx.clean_text(links[2].text_content()) if len(links) > 2 else ""
            text = ctx.clean_text(row.text_content())
            latest = ctx.text(row, ".s5") or ctx.regex(text, r"最新：(.+)$", default="")
            intro = text
            if latest:
                intro = intro.replace(f"最新：{latest}", "").strip()
            if name and intro.startswith(name):
                intro = intro[len(name):].strip()
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": author,
                "bookUrl": urljoin(self.explore_url, href),
                "intro": intro,
                "lastChapter": latest,
                "kind": group["title"],
                "groupId": group["groupId"],
                "groupTitle": group["title"],
                "rank": index,
            })
        return items

    async def search(self, ctx, keyword: str, page: int):
        items = []
        base_for_join = self.base_url
        try:
            html = await ctx.fetch_text(
                f"{self.base_url}/search.html",
                params={"keyword": keyword},
                headers=self.headers,
            )
            items = self._parse_search_rows(ctx, html, base_for_join, ".layui-btn-container a[title]")
            matched = [item for item in items if keyword in item.get("name", "")]
            items = matched or []
        except Exception:
            items = []
        if not items:
            try:
                base_for_join = "https://m.shuhaige.net"
                legacy_url = "https://m.shuhaige.net/search.html"
                html = await ctx.fetch_text(legacy_url, method="POST", data={"searchkey": keyword}, headers=self.headers)
                items = self._parse_search_rows(ctx, html, base_for_join, "#sitembox > dl")
            except Exception:
                base_for_join = "https://www.shuhaige.net"
                legacy_url = "https://www.shuhaige.net/search.html"
                html = await ctx.fetch_text(legacy_url, method="POST", data={"searchkey": keyword, "searchtype": "all"})
                items = self._parse_search_rows(ctx, html, base_for_join, "#sitembox > dl")
        if not items:
            items = await self._search_from_explore(ctx, keyword)
        return items

    async def _search_from_explore(self, ctx, keyword: str):
        matched = []
        for group in self.explore_defs[:3]:
            for item in await self.explore(ctx, group["groupId"], 1):
                if keyword in item.get("name", ""):
                    matched.append(item)
            if matched:
                break
        return matched

    def _parse_search_rows(self, ctx, html: str, base_for_join: str, selector: str):
        rows = ctx.select(html, selector)
        items = []
        for row in rows:
            name_node = ctx.select(row, "dd > h3 > a")
            if name_node:
                name = name_node[0].text_content().strip()
                href = name_node[0].get("href", "")
                author = ctx.text(row, "dd:nth-child(3) > span:nth-child(1)")
                latest = ctx.text(row, "dd:nth-child(5) > a")
            else:
                name = row.get("title", "") or row.text_content().strip()
                href = row.get("href", "")
                author = ""
                latest = ""
            book_url = urljoin(base_for_join, href)
            if not name:
                continue
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": author,
                "bookUrl": book_url,
                "lastChapter": latest,
            })
        return items

    async def detail(self, ctx, book_url: str):
        html = await ctx.fetch_text(book_url, headers=self.headers)
        name = ctx.attr(html, 'meta[property="og:novel:book_name"]', "content") or ctx.text(html, ".name") or ctx.text(html, "#info > h1")
        author = ctx.attr(html, 'meta[property="og:novel:author"]', "content") or ctx.text(html, "#info > p:nth-child(2)").replace("作者：", "").strip()
        intro = ctx.attr(html, 'meta[property="og:description"]', "content") or ctx.text(html, ".intro") or ctx.text(html, "#intro > p:nth-child(1)")
        cover = ctx.attr(html, 'meta[property="og:image"]', "content") or ctx.attr(html, "#fmimg > img", "src")
        last = ctx.attr(html, 'meta[property="og:novel:latest_chapter_name"]', "content") or ctx.text(html, "#info > p:nth-child(4) > a")
        toc_url = ctx.attr(html, 'meta[property="og:novel:read_url"]', "content") or book_url
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, cover) if cover else "",
            "intro": intro,
            "lastChapter": last,
            "tocUrl": toc_url,
            "authRequired": False,
        }

    async def toc(self, ctx, toc_url: str):
        html = await ctx.fetch_text(toc_url, headers=self.headers)
        marker = "/" + toc_url.rstrip("/").split("/")[-1] + "/"
        links = [
            a for a in ctx.select(html, 'a[href$=".html"]')
            if marker in urljoin(toc_url, a.get("href", ""))
        ]
        if not links:
            links = ctx.select(html, "dl > dt:nth-of-type(2) ~ dd > a")
        chapters = []
        seen: set[str] = set()
        for index, a in enumerate(links, start=1):
            href = a.get("href", "")
            title = a.text_content().strip()
            if not href or not title or href in seen:
                continue
            seen.add(href)
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
        html = await ctx.fetch_text(chapter_url, headers=self.headers)
        title = ctx.text(html, "h1") or ctx.text(html, ".bookname > h1")
        content = ctx.html(html, ".content") or ctx.html(html, "#content")
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
