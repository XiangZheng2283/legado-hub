"""Plugin for 笔趣阁22 (22biqu.com) based on so-novel seed."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "22biqu_com"
    name = "笔趣阁22"
    contract_version = "1.0"
    last_modified = "2026-06-10"
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
        html = await ctx.access.http.fetch_text(url)
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
        html = await ctx.access.http.fetch_text(
            f"{self.base_url}/ss/",
            method="POST",
            data={"searchkey": keyword, "Submit": "搜索"},
        )
        if "搜索间隔" in html:
            ctx.trace("search_rate_limited", message="22biqu search interval hit; falling back to explore")
            items = []
        else:
            rows = (
                ctx.select(html, "body > div.container > div > div > ul > li")
                or ctx.select(html, ".txt-list-row5 li")
                or ctx.select(html, ".search-result li")
                or ctx.select(html, "ul li")
            )
            items = []
            for row in rows:
                name_node = ctx.select(row, "span.s2 > a") or ctx.select(row, "a")
                name = name_node[0].text_content().strip() if name_node else ""
                href = name_node[0].get("href", "") if name_node else ""
                author = ctx.text(row, "span.s4") or ctx.text(row, ".s4")
                latest = ctx.text(row, "span.s3") or ctx.text(row, ".s3")
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
                items = matched or items
        if not items:
            items = await self._search_from_explore(ctx, keyword)
        return await enrich_search_items_from_detail(self, ctx, items)

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
        html = await ctx.access.http.fetch_text(book_url)
        name = ctx.text(html, ".info h1")
        info_text = ctx.text(html, ".info")
        author = ctx.regex(info_text, r"作\s*者[：:]\s*([^\s]+)", default="").strip()
        update_time = ctx.regex(info_text, r"更新时间[：:]\s*([^\s]+)", default="").strip()
        intro = ctx.text(html, ".info .desc")
        cover = ctx.attr(html, ".imgbox img", "src")
        last = ctx.text(html, ".info p:nth-child(5) a")
        kind = ctx.attr(html, 'meta[property="og:novel:category"]', "content")
        status = ctx.attr(html, 'meta[property="og:novel:status"]', "content")
        if not update_time:
            update_time = ctx.attr(html, 'meta[property="og:novel:update_time"]', "content")
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, cover) if cover else "",
            "intro": intro,
            "kind": " / ".join(part for part in [kind, status] if part),
            "lastChapter": last,
            "updateTime": update_time,
            "tocUrl": book_url,
            "authRequired": False,
        }

    async def toc(self, ctx, toc_url: str):
        chapters = []
        seen: set[str] = set()
        page_url = toc_url
        for _ in range(200):
            html = await ctx.access.http.fetch_text(page_url)
            links = ctx.select(html, "div:nth-child(4) > ul > li > a") or ctx.select(html, "#list dl dd a") or ctx.select(html, "ul li a")
            new_count = 0
            for a in links:
                href = a.get("href", "")
                title = a.text_content().strip()
                if not href or not title or href in seen:
                    continue
                seen.add(href)
                chapters.append({
                    "sourceId": self.id,
                    "index": len(chapters) + 1,
                    "title": title,
                    "chapterUrl": urljoin(page_url, href),
                    "isVip": False,
                    "isLocked": False,
                })
                new_count += 1
            next_href = ctx.attr(html, "#next_url", "href") or ctx.attr(html, "a:contains('下一页')", "href")
            if not next_href or new_count == 0:
                break
            next_url = urljoin(page_url, next_href)
            if next_url == page_url:
                break
            page_url = next_url
        return chapters

    def _chapter_stem(self, url: str) -> str:
        path = url.split("?")[0].split("#")[0]
        if "_" in path:
            return path.rsplit("_", 1)[0]
        return path.rsplit(".", 1)[0] if "." in path else path

    def _clean_chapter_content(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "iframe", "ins", "center"]):
            tag.decompose()
        for div in soup.find_all("div"):
            text = div.get_text(strip=True)
            if len(text) < 80 and any(kw in text for kw in ["广告", "声明", "本章结束", "返回目录", "加入书签", "推荐", "最新网址", "章节内容缺失", "章节不存在"]):
                div.decompose()
        for tag in soup.find_all("br"):
            tag.replace_with("\n")
        paragraphs = []
        for p in soup.find_all("p"):
            text = p.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)
        if paragraphs:
            return "\n\n".join(paragraphs)
        text = soup.get_text("\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n\n".join(lines)

    async def chapter(self, ctx, chapter_url: str):
        parts: list[str] = []
        current_url = chapter_url
        title = ""
        original_stem = self._chapter_stem(chapter_url)
        while current_url and len(parts) < 10:
            html = await ctx.access.http.fetch_text(current_url)
            if not title:
                title = ctx.text(html, ".title") or ctx.text(html, "h1") or ctx.text(html, ".bookname > h1")
            content_html = ctx.html(html, "#content") or ctx.html(html, "#booktxt") or ctx.html(html, ".content")
            content = self._clean_chapter_content(content_html)
            if content:
                parts.append(content)
            next_href = ctx.attr(html, "#next_url", "href") or ctx.attr(html, "a:contains('下一章')", "href")
            if not next_href or next_href == "javascript:void(0);":
                break
            next_url = urljoin(current_url, next_href)
            if self._chapter_stem(next_url) != original_stem:
                break
            current_url = next_url
        title = re.sub(r"[（(][\d/]+[）)]", "", title or "").strip()
        full_content = "\n\n".join(parts)
        return {
            "sourceId": self.id,
            "title": title,
            "content": full_content,
            "chapterUrl": chapter_url,
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }
