"""Plugin for 黄金屋中文 (tw.hjwzw.com)."""

from __future__ import annotations

import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    """Adapt the Traditional Chinese HTML site to the source contract."""

    id = "hjwzw_com"
    name = "黄金屋中文"
    contract_version = "1.0"
    last_modified = "2026-07-25"
    base_url = "https://tw.hjwzw.com"
    headers = {"accept-language": "zh-TW,zh;q=0.9"}

    async def _fetch(self, ctx, url: str) -> str:
        """Fetch a site page through the host-owned HTTP bridge."""
        return await ctx.access.http.fetch_text(
            urljoin(self.base_url, url),
            headers=self.headers,
        )

    def _s(self, ctx, value: str) -> str:
        """Convert user-facing Traditional Chinese text to Simplified Chinese."""
        return ctx.to_simplified(ctx.clean_text(value or ""))

    async def search(self, ctx, keyword: str, page: int) -> list[dict]:
        """Search the site's title index and enrich the first sparse results."""
        if page > 1:
            return []
        search_keyword = ctx.to_traditional(keyword.strip())
        url = f"{self.base_url}/List/{quote(search_keyword, safe='')}"
        html = await self._fetch(ctx, url)
        items = self._parse_search(ctx, html)
        exact = [item for item in items if keyword and keyword in item.get("name", "")]
        return await enrich_search_items_from_detail(self, ctx, exact or items)

    def _parse_search(self, ctx, html: str) -> list[dict]:
        """Parse table-based search cards without depending on hashed classes."""
        soup = BeautifulSoup(html or "", "html.parser")
        items: list[dict] = []
        seen: set[str] = set()
        for title_link in soup.select('span.wd10 a[href^="/Book/"]'):
            href = title_link.get("href", "")
            book_url = urljoin(self.base_url, href)
            if not href or book_url in seen:
                continue
            seen.add(book_url)
            title_row = title_link.find_parent("tr")
            detail_row = title_row.find_next_sibling("tr") if title_row else None
            container = detail_row or title_row or title_link
            author_node = container.select_one("span.wd7 a")
            cover_node = container.select_one("img[src]")
            intro_node = container.select_one("span.wd9")
            items.append(
                {
                    "sourceId": self.id,
                    "name": self._s(ctx, title_link.get_text(" ", strip=True)),
                    "author": self._s(ctx, author_node.get_text(" ", strip=True) if author_node else ""),
                    "bookUrl": book_url,
                    "coverUrl": urljoin(self.base_url, cover_node.get("src", "")) if cover_node else "",
                    "intro": self._s(ctx, intro_node.get_text(" ", strip=True) if intro_node else ""),
                    "kind": "",
                    "lastChapter": "",
                    "wordCount": "",
                    "rank": len(items) + 1,
                }
            )
        return items

    async def detail(self, ctx, book_url: str) -> dict:
        """Read stable OpenGraph metadata and the full-catalog link."""
        book_url = urljoin(self.base_url, book_url)
        html = await self._fetch(ctx, book_url)
        name = self._meta(ctx, html, "og:novel:book_name") or ctx.text(html, "h1")
        author = self._meta(ctx, html, "og:novel:author")
        category = self._meta(ctx, html, "og:novel:category")
        status = self._meta(ctx, html, "og:novel:status")
        intro = (
            self._meta(ctx, html, "og:description")
            or ctx.attr(html, 'meta[name="Description"]', "content")
            or ctx.attr(html, 'meta[name="description"]', "content")
        )
        cover = self._meta(ctx, html, "og:image")
        latest = self._meta(ctx, html, "og:novel:latest_chapter_name")
        update_time = self._meta(ctx, html, "og:novel:update_time")
        toc_href = ctx.attr(html, 'a[href*="/Book/Chapter/"]', "href")
        if not toc_href:
            book_id = self._book_id(book_url)
            toc_href = f"/Book/Chapter/{book_id}" if book_id else book_url
        return {
            "sourceId": self.id,
            "name": self._s(ctx, name),
            "author": self._s(ctx, author),
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, cover) if cover else "",
            "intro": self._s(ctx, intro),
            "kind": self._s(ctx, " / ".join(part for part in [category, status] if part)),
            "lastChapter": self._s(ctx, latest),
            "wordCount": "",
            "updateTime": update_time,
            "tocUrl": urljoin(self.base_url, toc_href),
            "authRequired": False,
        }

    def _meta(self, ctx, html: str, property_name: str) -> str:
        """Return one OpenGraph property value."""
        return ctx.attr(html, f'meta[property="{property_name}"]', "content")

    def _book_id(self, book_url: str) -> str:
        """Extract the numeric book identifier from a detail URL."""
        match = re.search(r"/Book/(\d+)", book_url or "", re.IGNORECASE)
        return match.group(1) if match else ""

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        """Parse the complete static catalog in normal reading order."""
        toc_url = urljoin(self.base_url, toc_url)
        html = await self._fetch(ctx, toc_url)
        chapters: list[dict] = []
        seen: set[str] = set()
        for link in ctx.select(html, 'a[href^="/Book/Read/"]'):
            href = link.get("href", "")
            chapter_url = urljoin(self.base_url, href)
            title = self._s(ctx, link.text_content())
            if not href or not title or chapter_url in seen:
                continue
            seen.add(chapter_url)
            chapters.append(
                {
                    "sourceId": self.id,
                    "index": len(chapters) + 1,
                    "title": title,
                    "chapterUrl": chapter_url,
                    "updateTime": self._update_time(link.get("title", "")),
                    "isVip": False,
                    "isLocked": False,
                }
            )
        return chapters

    def _update_time(self, title_attr: str) -> str:
        """Extract an optional timestamp embedded in a catalog link title."""
        match = re.search(r"(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2})?)", title_attr or "")
        return match.group(1) if match else ""

    async def chapter(self, ctx, chapter_url: str) -> dict:
        """Read one chapter and remove the site's leading domain banner."""
        chapter_url = urljoin(self.base_url, chapter_url)
        html = await self._fetch(ctx, chapter_url)
        title_raw = ctx.text(html, "h1")
        content = self._chapter_content(ctx, html, title_raw)
        return {
            "sourceId": self.id,
            "title": self._s(ctx, title_raw),
            "chapterUrl": chapter_url,
            "content": self._s(ctx, content),
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _chapter_content(self, ctx, html: str, title: str) -> str:
        """Turn the bare-text and empty-p separator layout into paragraphs."""
        soup = BeautifulSoup(html or "", "html.parser")
        candidates = soup.select('div[style*="text-indent"]')
        container = max(candidates, key=lambda node: len(node.get_text()), default=None)
        if container is None:
            return ""
        for node in container.select("script, style, iframe"):
            node.decompose()
        for separator in container.select("p, br"):
            separator.replace_with("\n")
        lines = [ctx.clean_text(line) for line in container.get_text("\n").splitlines()]
        lines = [line for line in lines if line]
        normalized_title = ctx.clean_text(title)
        for index, line in enumerate(lines):
            if normalized_title and ctx.clean_text(line) == normalized_title:
                lines = lines[index + 1 :]
                break
        blocked = ("請記住本站域名", "请记住本站域名", "黃金屋", "黄金屋", "返回目錄", "返回目录")
        lines = [line for line in lines if not any(marker in line for marker in blocked)]
        return "\n\n".join(lines).strip()
