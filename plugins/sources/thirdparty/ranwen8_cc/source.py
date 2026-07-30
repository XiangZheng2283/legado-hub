"""Ranwen8 (燃文小说网) source plugin.

Chapter content is base64-encoded in <script>document.writeln(qsbs.bb('...'));</script> tags.
"""

import base64
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "ranwen8_cc"
    name = "燃文小说网"
    contract_version = "1.0"
    last_modified = "2026-06-10"
    base_url = "https://www.ranwen8.cc"

    async def search(self, ctx, keyword: str, page: int):
        items = []
        search_error = None
        try:
            html = await ctx.access.http.fetch_text(
                f"{self.base_url}/search.html",
                method="POST",
                data={"submit": "搜索", "s": keyword},
            )
            rows = ctx.select(html, "body > div.padding > div > table > tbody > tr")
            for row in rows:
                name_a = ctx.select(row, "td:nth-child(1) > a")
                if not name_a:
                    continue
                name = ctx.clean_text(name_a[0].text_content())
                book_url = urljoin(self.base_url, name_a[0].get("href", ""))
                author = ctx.clean_text(ctx.text(row, "td:nth-child(3)"))
                latest = ctx.clean_text(ctx.text(row, "td:nth-child(2) > a"))
                update_time = ctx.clean_text(ctx.text(row, "td:nth-child(4)"))
                items.append({
                    "sourceId": self.id,
                    "name": name,
                    "author": author,
                    "bookUrl": book_url,
                    "lastChapter": latest,
                    "updateTime": update_time,
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
            links = ctx.select(html, "body > div.padding > div > div > ul > li > a")
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
        name = ctx.text(html, 'meta[property="og:title"]') or ctx.text(html, "#info > h1")
        author = ctx.text(html, "#info > h1 > small > a")
        cover = ctx.attr(html, 'meta[property="og:image"]', "content")
        intro = ctx.text(html, "#intro > p") or ""
        toc_url = book_url
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, cover) if cover else "",
            "intro": intro,
            "tocUrl": toc_url,
            "authRequired": False,
            "extra": {},
        }

    async def toc(self, ctx, toc_url: str):
        chapters = []
        seen: set[str] = set()
        seen_pages: set[str] = set()
        page_url = toc_url
        while page_url and page_url not in seen_pages:
            seen_pages.add(page_url)
            html = await ctx.access.http.fetch_text(page_url)
            links = ctx.select(html, "body > div:nth-child(4) > div > ul > li > a")
            new_count = 0
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
                    "chapterUrl": urljoin(page_url, href),
                    "isVip": False,
                    "isLocked": False,
                })
                new_count += 1
            next_href = ctx.attr(
                html,
                "body > div:nth-child(4) > div > div > select > option:last-child",
                "value",
            )
            if not next_href or new_count == 0:
                break
            next_url = urljoin(page_url, next_href)
            if next_url == page_url:
                break
            page_url = next_url
        return chapters

    def _decode_base64_content(self, html: str) -> str:
        """Decode base64-encoded chapter content injected via <script>."""
        pattern = re.compile(
            r'<script>\s*document\.writeln\(qsbs\.bb\(\'([^\']+)\'\)\);\s*</script>',
            re.IGNORECASE,
        )

        def _decode(match: re.Match) -> str:
            b64 = match.group(1)
            try:
                cleaned = re.sub(r"[^A-Za-z0-9+/=]", "", b64)
                decoded = base64.b64decode(cleaned)
                return decoded.decode("utf-8", errors="replace")
            except Exception:
                return ""

        return pattern.sub(_decode, html)

    def _chapter_stem(self, url: str) -> str:
        path = url.split("?")[0].split("#")[0]
        if "_" in path:
            return path.rsplit("_", 1)[0]
        return path.rsplit(".", 1)[0] if "." in path else path

    def _clean_chapter_content(self, html: str) -> str:
        html = self._decode_base64_content(html)
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "iframe", "ins", "center"]):
            tag.decompose()
        for div in soup.find_all("div"):
            text = div.get_text(strip=True)
            if len(text) < 80 and any(kw in text for kw in ["广告", "声明", "本章结束", "返回目录", "加入书签", "推荐", "最新网址", "章节内容缺失", "章节不存在", "首发", "燃文"]):
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
        parts: list[str] = []
        current_url = chapter_url
        title = ""
        original_stem = self._chapter_stem(chapter_url)
        while current_url and len(parts) < 10:
            html = await ctx.access.http.fetch_text(current_url)
            if not title:
                title = ctx.text(html, "#jsnc_l > div > h1") or ctx.text(html, "h1")
            content_html = ctx.html(html, "#htmlContent")
            content = self._clean_chapter_content(content_html)
            if content:
                parts.append(content)
            next_href = ctx.attr(html, "#link-next", "href")
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
