"""Quanben5 (全本小说网) source plugin.

Search requires a reverse-engineered parameter 'b'. Full-text search is limited;
this source excels at completed books.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "quanben5_com"
    name = "全本小说网"
    contract_version = "1.0"
    last_modified = "2026-06-10"
    base_url = "https://quanben5.com"

    async def search(self, ctx, keyword: str, page: int):
        items = []
        search_error = None
        try:
            html = await ctx.access.http.fetch_text(
                f"{self.base_url}/?c=book&a=search",
                params={"keywords": keyword},
            )
            results = ctx.select(html, ".pic_txt_list")
            for div in results:
                name_a = ctx.select(div, "h3 > a")
                if not name_a:
                    continue
                name = ctx.clean_text(name_a[0].text_content())
                href = name_a[0].get("href", "")
                author = ctx.clean_text(ctx.text(div, "p.info > span"))
                items.append({
                    "sourceId": self.id,
                    "name": name,
                    "author": author,
                    "bookUrl": urljoin(self.base_url, href),
                })
        except Exception as exc:
            search_error = exc
            ctx.trace("search_error", url=f"{self.base_url}/?c=book&a=search", message=str(exc))
        if not items:
            items = await self._search_from_explore(ctx, keyword)
        if items:
            return await enrich_search_items_from_detail(self, ctx, items)
        if search_error is not None:
            raise search_error
        return []

    async def _search_from_explore(self, ctx, keyword: str) -> list[dict]:
        items = []
        try:
            html = await ctx.access.http.fetch_text(f"{self.base_url}/topallvisit/1.html")
            links = ctx.select(html, ".pic_txt_list h3 > a")
            seen = set()
            for a in links:
                href = a.get("href", "")
                name = ctx.clean_text(a.text_content())
                if not href or not name or name in seen:
                    continue
                if keyword.lower() in name.lower():
                    seen.add(name)
                    items.append({
                        "sourceId": self.id,
                        "name": name,
                        "bookUrl": urljoin(self.base_url, href),
                    })
        except Exception as exc:
            ctx.trace("search_explore_fallback_error", url=f"{self.base_url}/topallvisit/1.html", message=str(exc))
        return items

    async def detail(self, ctx, book_url: str):
        html = await ctx.access.http.fetch_text(book_url)
        name = ctx.text(html, "h3 > span") or ctx.text(html, "h1") or ""
        author = ctx.text(html, ".pic_txt_list p:nth-child(3) > span")
        intro = ctx.text(html, ".description")
        cover = ctx.attr(html, ".pic_txt_list img", "src")
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, cover) if cover else "",
            "intro": intro,
            "tocUrl": book_url,
            "authRequired": False,
            "extra": {},
        }

    async def toc(self, ctx, toc_url: str):
        chapters = []
        seen = set()
        html = await ctx.access.http.fetch_text(toc_url)
        links = ctx.select(html, "ul > li > a")
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
                "chapterUrl": urljoin(toc_url, href),
                "isVip": False,
                "isLocked": False,
            })
        return chapters

    def _clean_chapter_content(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "iframe", "ins", "center"]):
            tag.decompose()
        for div in soup.find_all("div"):
            text = div.get_text(strip=True)
            if len(text) < 80 and any(kw in text for kw in ["广告", "声明", "本章结束", "返回目录", "加入书签", "推荐", "最新网址", "章节内容缺失", "章节不存在", "全本小说网", "quanben5"]):
                div.decompose()
        for br in soup.find_all("br"):
            br.replace_with("\n")
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
        html = await ctx.access.http.fetch_text(chapter_url)
        title = ctx.text(html, ".content > h1") or ctx.text(html, "h1") or ""
        content_html = ctx.html(html, "#content")
        content = self._clean_chapter_content(content_html)
        return {
            "sourceId": self.id,
            "title": title,
            "content": content,
            "chapterUrl": chapter_url,
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }
