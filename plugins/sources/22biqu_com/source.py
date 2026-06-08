"""Plugin for 笔趣阁22 (22biqu.com) based on so-novel seed."""

from urllib.parse import urljoin


class Source:
    id = "22biqu_com"
    name = "笔趣阁22"
    contract_version = "1.0"
    base_url = "https://www.22biqu.com"
    mobile_url = "https://m.22biqu.com"
    explore_defs = [
        {"groupId": "rank_all", "title": "总排行榜", "url": "/rank/allvisit/", "kind": "rank"},
        {"groupId": "rank_month", "title": "月排行榜", "url": "/rank/monthvisit/", "kind": "rank"},
        {"groupId": "rank_week", "title": "周排行榜", "url": "/rank/weekvisit/", "kind": "rank"},
        {"groupId": "rank_collect", "title": "总收藏榜", "url": "/rank/goodnum/", "kind": "rank"},
        {"groupId": "category_xuanhuan", "title": "玄幻魔法", "url": "/quanben/fenlei/1_{page}.html", "kind": "category"},
    ]

    async def explore_groups(self, ctx):
        return [
            {
                "sourceId": self.id,
                "groupId": item["groupId"],
                "title": item["title"],
                "url": urljoin(self.base_url, item["url"].replace("{page}", "1")),
                "kind": item["kind"],
                "pageable": "{page}" in item["url"],
                "profile": "desktop",
            }
            for item in self.explore_defs
        ]

    async def explore(self, ctx, group_id: str | None = None, page: int = 1):
        group = next((item for item in self.explore_defs if item["groupId"] == group_id), self.explore_defs[0])
        url = urljoin(self.base_url, group["url"].replace("{page}", str(page)))
        html = await ctx.fetch_text(url)
        rows = ctx.select(html, ".hot_sale") or ctx.select(html, ".txt-list-row3 li")
        items = []
        for index, row in enumerate(rows, start=1):
            link = ctx.select(row, "a")
            if not link:
                continue
            href = link[0].get("href", "")
            raw_title = ctx.clean_text(link[0].text_content())
            name = raw_title.split("作者：", 1)[0]
            name = name.split(".", 1)[-1].strip()
            text = ctx.clean_text(row.text_content())
            author = ctx.regex(text, r"作者：([^简]+)", default="").strip()
            intro = text.split("简介：", 1)[-1].strip() if "简介：" in text else ""
            latest = ctx.text(row, ".s5")
            if not name:
                continue
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": author,
                "bookUrl": urljoin(self.base_url, href),
                "intro": intro,
                "lastChapter": latest,
                "kind": group["title"],
                "groupId": group["groupId"],
                "groupTitle": group["title"],
                "rank": index,
            })
        return items

    async def search(self, ctx, keyword: str, page: int):
        html = await ctx.fetch_text(
            f"{self.base_url}/ss/",
            method="POST",
            data={"searchkey": keyword, "Submit": "搜索"},
        )
        if "搜索间隔" in html:
            return await self._search_from_explore(ctx, keyword)
        rows = ctx.select(html, "body > div.container > div > div > ul > li")
        items = []
        for row in rows:
            name_node = ctx.select(row, "span.s2 > a")
            name = name_node[0].text_content().strip() if name_node else ""
            href = name_node[0].get("href", "") if name_node else ""
            author = ctx.text(row, "span.s4")
            latest = ctx.text(row, "span.s3")
            book_url = urljoin(self.base_url, href)
            if not name:
                continue
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": author,
                "bookUrl": book_url,
                "lastChapter": latest,
            })
        if items:
            matched = [item for item in items if keyword in item.get("name", "")]
            return matched or items
        return await self._search_from_explore(ctx, keyword)

    async def _search_from_explore(self, ctx, keyword: str):
        matched = []
        for group in self.explore_defs:
            try:
                items = await self.explore(ctx, group["groupId"], 1)
            except Exception as exc:
                ctx.trace("search_explore_fallback_error", url=group["url"], message=str(exc))
                continue
            matched.extend(item for item in items if keyword and keyword in item.get("name", ""))
            if matched:
                break
        return matched

    async def detail(self, ctx, book_url: str):
        html = await ctx.fetch_text(book_url)
        name = ctx.text(html, "#info > h1")
        author = ctx.text(html, "#info > p:nth-child(2)").replace("作者：", "").strip()
        intro = ctx.text(html, "#intro")
        cover = ctx.attr(html, "#fmimg > img", "src")
        last = ctx.text(html, "#info > p:nth-child(4) > a")
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
        links = ctx.select(html, "div:nth-child(4) > ul > li > a")
        chapters = []
        for index, a in enumerate(links, start=1):
            href = a.get("href", "")
            title = a.text_content().strip()
            if not href or not title:
                continue
            chapters.append({
                "sourceId": self.id,
                "index": index,
                "title": title,
                "chapterUrl": urljoin(toc_url, href),
                "isVip": False,
                "isLocked": False,
            })
        return chapters

    async def chapter(self, ctx, chapter_url: str):
        html = await ctx.fetch_text(chapter_url)
        title = ctx.text(html, ".title")
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
