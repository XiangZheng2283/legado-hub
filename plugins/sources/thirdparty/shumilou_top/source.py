"""Plugin for 书迷楼 (shumilou.top)."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    """Adapt the mobile site to the source contract."""

    id = "shumilou_top"
    name = "书迷楼"
    contract_version = "1.0"
    last_modified = "2026-07-25"
    base_url = "https://www.shumilou.top"

    async def _fetch(self, ctx, url: str, **kwargs) -> str:
        """Fetch a site page through the host-owned HTTP bridge."""
        return await ctx.access.http.fetch_text(urljoin(self.base_url, url), **kwargs)

    async def search(self, ctx, keyword: str, page: int) -> list[dict]:
        """Search the site's POST endpoint."""
        if page > 1 or not keyword.strip():
            return []
        html = await self._fetch(
            ctx,
            "/search/",
            method="POST",
            data={"searchkey": keyword.strip()},
            headers={"Referer": self.base_url},
        )
        items = self._parse_search(ctx, html)
        exact = [item for item in items if item.get("name") == keyword.strip()]
        return await enrich_search_items_from_detail(self, ctx, exact or items)

    def _parse_search(self, ctx, html: str) -> list[dict]:
        """Parse one list item per search result."""
        soup = BeautifulSoup(html or "", "html.parser")
        items: list[dict] = []
        seen: set[str] = set()
        for box in soup.select(".bookbox"):
            a = box.select_one(".bookname a[href]") or box.select_one(".bookimg a[href]")
            if a is None:
                continue
            href = a.get("href", "").strip()
            name = ctx.clean_text(a.get("title", "")) or ctx.clean_text(a.get_text(" ", strip=True))
            book_url = self._local_url(href)
            if not href or not name or book_url in seen:
                continue
            seen.add(book_url)
            author = ""
            author_node = box.select_one(".author")
            if author_node:
                author = ctx.clean_text(author_node.get_text(" ", strip=True)).replace("作者：", "").strip()
            items.append(
                {
                    "sourceId": self.id,
                    "name": name,
                    "author": author,
                    "bookUrl": book_url,
                    "coverUrl": "",
                    "intro": "",
                    "kind": "",
                    "lastChapter": "",
                    "wordCount": "",
                    "rank": len(items) + 1,
                }
            )
        return items

    async def detail(self, ctx, book_url: str) -> dict:
        """Read the book metadata from the detail page."""
        book_url = self._local_url(book_url)
        html = await self._fetch(ctx, book_url)
        name = self._meta(ctx, html, "og:novel:book_name") or ctx.text(html, "header .title")
        author = self._meta(ctx, html, "og:novel:author") or self._text_after_label(ctx, html, ".synopsisArea_detail .author", "作者：")
        category = self._meta(ctx, html, "og:novel:category")
        status = self._meta(ctx, html, "og:novel:status")
        cover = self._meta(ctx, html, "og:image") or ctx.attr(html, ".synopsisArea_detail img", "src")
        intro = self._meta(ctx, html, "og:description") or ctx.text(html, ".synopsisArea .review")
        last = self._meta(ctx, html, "og:novel:latest_chapter_name")
        update_time = self._meta(ctx, html, "og:novel:update_time")
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": self._local_url(cover) if cover else "",
            "intro": intro,
            "kind": " / ".join(part for part in [category, status] if part),
            "lastChapter": last,
            "wordCount": "",
            "updateTime": update_time,
            "tocUrl": book_url,
            "authRequired": False,
        }

    def _meta(self, ctx, html: str, property_name: str) -> str:
        """Return one OpenGraph property value."""
        return ctx.attr(html, f'meta[property="{property_name}"]', "content")

    def _text_after_label(self, ctx, html: str, selector: str, label: str) -> str:
        """Extract text after a label such as '作者：'."""
        text = ctx.text(html, selector)
        if text.startswith(label):
            text = text[len(label):].strip()
        return text

    def _local_url(self, url: str) -> str:
        """Normalize to the verified origin."""
        value = (url or "").strip()
        if value.startswith(("http://www.shumilou.top", "https://www.shumilou.top")):
            value = value.split("www.shumilou.top", 1)[1]
        return urljoin(self.base_url, value)

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        """Parse and deduplicate the paginated body catalog."""
        toc_url = self._local_url(toc_url)
        chapters: list[dict] = []
        seen: set[str] = set()
        seen_pages: set[str] = set()
        page_url = toc_url
        while page_url and page_url not in seen_pages:
            seen_pages.add(page_url)
            try:
                html = await self._fetch(ctx, page_url)
            except Exception as exc:
                ctx.trace("toc_pagination_error", url=page_url, message=str(exc))
                break
            page_chapters = self._parse_toc_page(ctx, html, page_url)
            for ch in page_chapters:
                if ch["chapterUrl"] in seen:
                    continue
                seen.add(ch["chapterUrl"])
                ch["index"] = len(chapters) + 1
                chapters.append(ch)
            page_url = self._next_toc_page(html, page_url)
        return chapters

    def _parse_toc_page(self, ctx, html: str, base_url: str) -> list[dict]:
        """Extract body chapters from one TOC page."""
        soup = BeautifulSoup(html or "", "html.parser")
        chapters: list[dict] = []
        for block in soup.select(".recommend"):
            heading = block.select_one("h2")
            if heading is None or "正文" not in heading.get_text(" ", strip=True):
                continue
            for a in block.select(".directoryArea a[href]"):
                href = a.get("href", "").strip()
                title = ctx.clean_text(a.get_text(" ", strip=True))
                if not href or not title:
                    continue
                chapters.append(
                    {
                        "sourceId": self.id,
                        "title": title,
                        "chapterUrl": self._local_url(href),
                        "updateTime": "",
                        "isVip": False,
                        "isLocked": False,
                    }
                )
            break
        return chapters

    def _next_toc_page(self, html: str, current_url: str) -> str:
        """Find the next TOC pagination link."""
        soup = BeautifulSoup(html or "", "html.parser")
        for a in soup.find_all("a", href=True):
            if "下一页" in a.get_text(" ", strip=True):
                href = a.get("href", "").strip()
                if href:
                    next_url = urljoin(current_url, href)
                    if next_url != current_url:
                        return next_url
        return ""

    async def chapter(self, ctx, chapter_url: str) -> dict:
        """Read one chapter body, merging same-chapter pagination."""
        chapter_url = self._local_url(chapter_url)
        base_id = self._chapter_base_id(chapter_url)
        parts: list[str] = []
        title = ""
        seen_pages: set[str] = set()
        page_url = chapter_url
        while page_url and page_url not in seen_pages and len(seen_pages) < 10:
            seen_pages.add(page_url)
            try:
                html = await self._fetch(ctx, page_url)
            except Exception as exc:
                ctx.trace("chapter_pagination_error", url=page_url, message=str(exc))
                break
            if not title:
                title = ctx.text(html, "header .title") or ctx.text(html, "h1")
                title = re.sub(r"\s+\S+\s*$", "", title).strip()
            content = self._chapter_page_content(ctx, html)
            if content:
                parts.append(content)
            if len("\n\n".join(parts)) >= 200:
                break
            next_url = self._next_chapter_page(html, page_url, base_id)
            if not next_url:
                break
            page_url = next_url
        full_content = "\n\n".join(parts).strip()
        return {
            "sourceId": self.id,
            "title": title,
            "chapterUrl": chapter_url,
            "content": full_content,
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _chapter_page_content(self, ctx, html: str) -> str:
        """Extract clean text from one chapter page."""
        soup = BeautifulSoup(html or "", "html.parser")
        container = soup.select_one("#chaptercontent")
        if container is None:
            return ""
        for tag in container.find_all(["script", "style", "ins", "center"]):
            tag.decompose()
        for div in container.find_all("div"):
            text = div.get_text(" ", strip=True)
            if len(text) < 80 and any(
                kw in text
                for kw in ["加入书签", "本章结束", "返回目录", "最新网址", "书迷楼"]
            ):
                div.decompose()
        for br in container.find_all("br"):
            br.replace_with("\n")
        paragraphs = [ctx.clean_text(p.get_text(" ", strip=True)) for p in container.find_all("p")]
        paragraphs = [p for p in paragraphs if p]
        return "\n\n".join(paragraphs)

    def _chapter_base_id(self, chapter_url: str) -> str:
        """Return book_id/chapter_id without pagination suffix."""
        m = re.search(r"/shu/(\d+)/(\d+)(?:_\d+)?\.html", chapter_url or "")
        return f"{m.group(1)}/{m.group(2)}" if m else ""

    def _next_chapter_page(self, html: str, current_url: str, base_id: str) -> str:
        """Find the next page link within the same chapter."""
        soup = BeautifulSoup(html or "", "html.parser")
        for a in soup.find_all("a", href=True):
            if "下一页" in a.get_text(" ", strip=True):
                href = a.get("href", "").strip()
                if not href:
                    continue
                next_url = urljoin(current_url, href)
                if self._chapter_base_id(next_url) == base_id:
                    return next_url
        return ""
