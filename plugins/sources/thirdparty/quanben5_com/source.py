"""Quanben5 (全本小说网) source plugin.

Search requires a reverse-engineered parameter 'b'. Full-text search is limited;
this source excels at completed books.
"""

import json
import re
import secrets
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup
from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "quanben5_com"
    name = "全本小说网"
    contract_version = "1.0"
    last_modified = "2026-06-10"
    base_url = "https://quanben5.com"

    _SEARCH_TOKEN_CHARS = "PXhw7UT1B0a9kQDKZsjIASmOezxYG4CHo5Jyfg2b8FLpEvRr3WtVnlqMidu6cN"

    @classmethod
    def _search_token(cls, keyword: str) -> str:
        """Match the site's client-side `base64(encodeURI(keyword))` protocol."""
        encoded = quote(keyword, safe=";/?:@&=+$,#")
        shifted = []
        for char in encoded:
            index = cls._SEARCH_TOKEN_CHARS.find(char)
            value = char if index < 0 else cls._SEARCH_TOKEN_CHARS[(index + 3) % len(cls._SEARCH_TOKEN_CHARS)]
            shifted.append(f"{secrets.choice(cls._SEARCH_TOKEN_CHARS)}{value}{secrets.choice(cls._SEARCH_TOKEN_CHARS)}")
        return "".join(shifted)

    @staticmethod
    def _search_result_html(payload: str) -> str:
        match = re.fullmatch(r"\s*\w+\((.*)\);?\s*", payload, flags=re.DOTALL)
        if not match:
            return payload
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            return ""
        return str(data.get("content", "")) if isinstance(data, dict) else ""

    async def _fetch_text(self, ctx, url: str, **kwargs) -> str:
        return ctx.decode_text(await ctx.access.http.fetch_bytes(url, **kwargs))

    async def search(self, ctx, keyword: str, page: int):
        items = []
        search_error = None
        normalized_keyword = ctx.clean_text(keyword).lower()
        try:
            html = await self._fetch_text(
                ctx,
                f"{self.base_url}/",
                params={
                    "c": "book",
                    "a": "search.json",
                    "callback": "search",
                    "keywords": keyword,
                    "b": self._search_token(keyword),
                },
                headers={"Referer": f"{self.base_url}/?c=book&a=search"},
            )
            html = self._search_result_html(html)
            results = ctx.select(html, ".pic_txt_list")
            for div in results:
                name_a = ctx.select(div, "h3 > a")
                if not name_a:
                    continue
                name = ctx.clean_text(name_a[0].text_content())
                href = name_a[0].get("href", "")
                if normalized_keyword and normalized_keyword not in name.lower():
                    continue
                author = ctx.clean_text(ctx.text(div, "p.info > span"))
                items.append({
                    "sourceId": self.id,
                    "name": name,
                    "author": author,
                    "bookUrl": urljoin(self.base_url, href),
                })
        except Exception as exc:
            search_error = exc
            ctx.trace("search_error", url=f"{self.base_url}/?c=book&a=search.json", message=str(exc))
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
            html = await self._fetch_text(ctx, f"{self.base_url}/topallvisit/1.html")
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
        html = await self._fetch_text(ctx, book_url)
        name = ctx.text(html, "h3 > span") or ctx.text(html, "h1") or ""
        author = ctx.text(html, ".pic_txt_list p.info > span.author") or ctx.text(
            html, ".pic_txt_list p.info > span"
        )
        intro = ctx.text(html, ".description")
        cover = ctx.attr(html, ".pic_txt_list img", "src")
        toc = ctx.attr(html, ".tool_button a.s1", "href") or book_url
        toc_url = urljoin(book_url, toc)
        last_chapter = ""
        try:
            catalog_html = await self._fetch_text(ctx, toc_url)
            links = ctx.select(catalog_html, "ul.list > li > a")
            if links:
                last_chapter = ctx.clean_text(links[-1].text_content())
        except Exception as exc:
            ctx.trace("detail_last_chapter_error", url=toc_url, message=str(exc))
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, cover) if cover else "",
            "intro": intro,
            "lastChapter": last_chapter,
            "tocUrl": toc_url,
            "authRequired": False,
            "extra": {},
        }

    async def toc(self, ctx, toc_url: str):
        chapters = []
        seen = set()
        html = await self._fetch_text(ctx, toc_url)
        links = ctx.select(html, "ul.list > li > a")
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
        html = await self._fetch_text(ctx, chapter_url)
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
