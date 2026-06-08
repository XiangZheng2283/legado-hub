"""Plugin for 香书小说 (xbiqugu.la) based on so-novel seed."""

from urllib.parse import urljoin


class Source:
    id = "xbiqugu_la"
    name = "香书小说"
    contract_version = "1.0"
    base_url = "https://www.xbiqugu.com"
    explore_defs = [
        {"groupId": "xuanhuan", "title": "玄幻", "url": "/fenlei/1_{page}.html", "kind": "category"},
        {"groupId": "xiuzhen", "title": "修真", "url": "/fenlei/2_{page}.html", "kind": "category"},
        {"groupId": "dushi", "title": "都市", "url": "/fenlei/3_{page}.html", "kind": "category"},
        {"groupId": "chuanyue", "title": "穿越", "url": "/fenlei/4_{page}.html", "kind": "category"},
        {"groupId": "wangyou", "title": "网游", "url": "/fenlei/5_{page}.html", "kind": "category"},
    ]

    async def explore_groups(self, ctx):
        return [
            {
                "sourceId": self.id,
                "groupId": item["groupId"],
                "title": item["title"],
                "url": urljoin(self.base_url, item["url"].replace("{page}", "1")),
                "kind": item["kind"],
                "pageable": True,
                "profile": "current",
            }
            for item in self.explore_defs
        ]

    async def explore(self, ctx, group_id: str | None = None, page: int = 1):
        group = next((item for item in self.explore_defs if item["groupId"] == group_id), self.explore_defs[0])
        url = urljoin(self.base_url, group["url"].replace("{page}", str(page)))
        html = await ctx.fetch_text(url)
        rows = ctx.select(html, ".item")
        items = []
        for index, row in enumerate(rows, start=1):
            links = ctx.select(row, 'a[href*="/wapbook/"]')
            if not links:
                continue
            href = links[0].get("href", "")
            named_links = [a for a in links if ctx.clean_text(a.text_content())]
            name = ctx.clean_text(named_links[0].text_content()) if named_links else ""
            text = ctx.clean_text(row.text_content())
            author = text.split(name, 1)[0].strip() if name and name in text else ""
            intro = text.split(name, 1)[-1].strip() if name and name in text else text
            if not name:
                continue
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": author,
                "bookUrl": urljoin(self.base_url, href),
                "intro": intro,
                "kind": group["title"],
                "groupId": group["groupId"],
                "groupTitle": group["title"],
                "rank": index,
            })
        return items

    async def search(self, ctx, keyword: str, page: int):
        try:
            base_for_join = self.base_url
            html = await ctx.fetch_text(
                f"{self.base_url}/so/",
                method="POST",
                data={"searchkey": keyword, "Submit": "搜索"},
            )
            rows = ctx.select(html, ".txt-list-row5 > li")
        except Exception:
            base_for_join = "http://www.xbiqugu.la"
            legacy_url = "http://www.xbiqugu.la/modules/article/waps.php"
            html = await ctx.fetch_text(legacy_url, method="POST", data={"searchkey": keyword})
            rows = ctx.select(html, "#checkform > table > tbody > tr")
        items = []
        for row in rows:
            name_node = ctx.select(row, "span.s2 > a")
            if not name_node:
                name_node = ctx.select(row, "td.even > a")
            name = name_node[0].text_content().strip() if name_node else ""
            href = name_node[0].get("href", "") if name_node else ""
            author = ctx.text(row, "span.s4") or ctx.text(row, "td:nth-of-type(3)")
            latest = ctx.text(row, "span.s3 > a") or ctx.text(row, "td.odd > a")
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
        matched = [item for item in items if keyword in item.get("name", "")]
        if matched:
            return matched
        if items:
            return items
        return await self._search_from_explore(ctx, keyword)

    async def _search_from_explore(self, ctx, keyword: str):
        matched = []
        for group in self.explore_defs:
            for item in await self.explore(ctx, group["groupId"], 1):
                if keyword in item.get("name", ""):
                    matched.append(item)
            if matched:
                break
        return matched

    async def detail(self, ctx, book_url: str):
        html = await ctx.fetch_text(book_url)
        name = ctx.attr(html, 'meta[property="og:novel:book_name"]', "content") or ctx.text(html, "#info > h1")
        author = ctx.attr(html, 'meta[property="og:novel:author"]', "content") or ctx.text(html, "#info > p:nth-child(2)").replace("作者：", "").strip()
        intro = ctx.attr(html, 'meta[property="og:description"]', "content") or ctx.text(html, "#intro")
        cover = ctx.attr(html, 'meta[property="og:image"]', "content") or ctx.attr(html, "#fmimg > img", "src")
        last = ctx.attr(html, 'meta[property="og:novel:lastest_chapter_name"]', "content") or ctx.text(html, "#info > p:nth-child(4) > a")
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, cover) if cover else "",
            "intro": intro,
            "lastChapter": last,
            "tocUrl": book_url,
            "authRequired": False,
        }

    async def toc(self, ctx, toc_url: str):
        html = await ctx.fetch_text(toc_url)
        links = ctx.select(html, f'a[href^="/wapbook/"]') or ctx.select(html, "#list > dl > dd > a")
        chapters = []
        seen: set[str] = set()
        for index, a in enumerate(links, start=1):
            href = a.get("href", "")
            title = a.text_content().strip()
            if not href or not title or not href.endswith(".html") or href in seen:
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
        html = await ctx.fetch_text(chapter_url)
        title = ctx.text(html, ".title") or ctx.text(html, ".bookname > h1")
        content = ctx.html(html, "#content")
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
