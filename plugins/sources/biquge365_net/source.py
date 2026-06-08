"""Plugin for 笔趣阁365 (biquge365.net) based on so-novel seed."""

from urllib.parse import urljoin
import re


class Source:
    id = "biquge365_net"
    name = "笔趣阁365"
    contract_version = "1.0"
    base_url = "https://m.biquge365.net"
    headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 9) Mobile Safari/537.36"}
    explore_defs = [
        {"groupId": "top_xuanhuan", "title": "玄幻魔法排行", "url": "/top/1_{page}/", "kind": "rank"},
        {"groupId": "top_xianxia", "title": "仙侠修真排行", "url": "/top/2_{page}/", "kind": "rank"},
        {"groupId": "top_dushi", "title": "都市言情排行", "url": "/top/3_{page}/", "kind": "rank"},
        {"groupId": "sort_xuanhuan", "title": "玄幻魔法分类", "url": "/sort/1_{page}/", "kind": "category"},
        {"groupId": "full_xuanhuan", "title": "玄幻魔法全本", "url": "/full/1/", "kind": "full"},
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
                "profile": "mobile",
            }
            for item in self.explore_defs
        ]

    async def explore(self, ctx, group_id: str | None = None, page: int = 1):
        group = next((item for item in self.explore_defs if item["groupId"] == group_id), self.explore_defs[0])
        url = urljoin(self.base_url, group["url"].replace("{page}", str(page)))
        html = await ctx.fetch_text(url, headers=self.headers)
        rows = ctx.select(html, ".liebiao2 li")
        items = []
        for index, row in enumerate(rows, start=1):
            link = ctx.select(row, ".ming a") or ctx.select(row, "a")
            if not link:
                continue
            name = ctx.clean_text(link[0].text_content())
            href = link[0].get("href", "")
            author = ctx.text(row, ".zuo")
            if not name:
                continue
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": author,
                "bookUrl": urljoin(self.base_url, href),
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
                f"{self.base_url}/waps.php",
                method="POST",
                data={"s": keyword, "submit": ""},
                headers=self.headers,
            )
            rows = ctx.select(html, ".liebiao2 li")
        except Exception:
            base_for_join = "https://www.biquge365.net"
            legacy_url = "https://www.biquge365.net/s.php"
            html = await ctx.fetch_text(legacy_url, method="POST", data={"type": "articlename", "s": keyword})
            rows = ctx.select(html, "body > div.menu > div > ul > li")
        items = []
        for row in rows:
            name_node = ctx.select(row, "a")
            if ctx.select(row, "span.name > a"):
                name_node = ctx.select(row, "span.name > a")
            name = name_node[0].text_content().strip() if name_node else ""
            href = name_node[0].get("href", "") if name_node else ""
            text = row.text_content()
            author = ctx.text(row, "span.zuo > a") or (text.split(name, 1)[-1].strip() if name else "")
            latest = ctx.text(row, "span.jie > a")
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
        if "www.biquge365.net" in book_url:
            name = ctx.text(html, "#info > h1")
            author = ctx.text(html, "#info > p:nth-child(2)").replace("作者：", "").strip()
            intro = ctx.text(html, "#intro")
            cover = ctx.attr(html, "#fmimg > img", "src")
        else:
            name = ctx.text(html, "h1")
            author = ctx.text(html, "ul:nth-of-type(1) > li:nth-child(1)").replace("作者：", "").strip()
            intro = ctx.text(html, ".jianjie p")
            cover = ctx.attr(html, "img", "src")
        latest_links = ctx.select(html, "ul:nth-of-type(2) a")
        last = latest_links[0].text_content().strip() if latest_links else ""
        toc_url = book_url if "www.biquge365.net" in book_url else book_url.rstrip("/") + "_1/"
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": urljoin(self.base_url, cover) if cover else "",
            "intro": intro,
            "lastChapter": last,
            "tocUrl": toc_url,
            "authRequired": False,
        }

    async def toc(self, ctx, toc_url: str):
        html = await ctx.fetch_text(toc_url, headers=self.headers)
        ul_nodes = ctx.select(html, "ul")
        links = ctx.select(ul_nodes[2], "li > a") if len(ul_nodes) >= 3 else ctx.select(html, "ul li > a")
        if not links:
            links = ctx.select(html, "body > div.menu > div.border > ul > li > a")
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
        html = await ctx.fetch_text(chapter_url, headers=self.headers)
        title = ctx.text(html, "#neirong > h1")
        content = ctx.html(html, "#txt")
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
