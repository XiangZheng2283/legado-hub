"""0xs (零点小说) source plugin.

Rate-limited: even concurrency=1 can be throttled.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "0xs_net"
    name = "零点小说"
    contract_version = "1.0"
    last_modified = "2026-06-10"
    base_url = "https://www.0xs.net"

    async def search(self, ctx, keyword: str, page: int):
        items = []
        search_error = None
        try:
            html = await ctx.access.http.fetch_text(
                f"{self.base_url}/search.html",
                params={"kw": keyword},
            )
            results = ctx.select(html, ".result_list > ul > li > .book")
            for div in results:
                name_a = ctx.select(div, ".name > a")
                if not name_a:
                    continue
                name = ctx.clean_text(name_a[0].text_content())
                href = name_a[0].get("href", "")
                author = ctx.clean_text(ctx.text(div, ".author"))
                status = ctx.clean_text(ctx.text(div, ".serial"))
                wc = ctx.clean_text(ctx.text(div, ".count"))
                cat = ctx.clean_text(ctx.text(div, ".type"))
                items.append({
                    "sourceId": self.id,
                    "name": name,
                    "author": author,
                    "bookUrl": urljoin(self.base_url, href),
                    "kind": f"{cat}/{status}",
                    "wordCount": wc,
                })
        except Exception as exc:
            search_error = exc
            ctx.trace("search_error", url=f"{self.base_url}/search.html", message=str(exc))
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
            links = ctx.select(html, ".result_list > ul > li > .book .name > a")
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
        name = ctx.text(html, ".title > h1") or ctx.text(html, "h1") or ""
        author = ""
        intro = ctx.text(html, ".intro") or ""
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "intro": intro,
            "tocUrl": book_url,
            "authRequired": False,
            "extra": {},
        }

    async def toc(self, ctx, toc_url: str):
        chapters = []
        seen = set()
        html = await ctx.access.http.fetch_text(toc_url)
        links = ctx.select(html, ".catalog > div > ul > li > a")
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
            if len(text) < 80 and any(kw in text for kw in ["广告", "声明", "本章结束", "返回目录", "加入书签", "推荐", "最新网址", "章节内容缺失", "章节不存在", "零点小说", "0xs"]):
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
        parts = []
        current_url = chapter_url
        title = ""
        original_stem = self._chapter_stem(chapter_url)
        while current_url and len(parts) < 10:
            html = await ctx.access.http.fetch_text(current_url)
            if not title:
                title = ctx.text(html, ".title > h1") or ctx.text(html, "h1")
            content_html = ctx.html(html, ".content") or ctx.html(html, "#content")
            content = self._clean_chapter_content(content_html)
            if content:
                parts.append(content)
            next_href = ctx.attr(html, "#next", "href")
            if not next_href or next_href == "javascript:void(0);":
                break
            if self._chapter_stem(next_href) != original_stem:
                break
            current_url = urljoin(chapter_url, next_href)
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
