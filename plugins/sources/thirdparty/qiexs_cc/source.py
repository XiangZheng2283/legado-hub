"""Plugin for 企鹅小说 (www.qiexs.cc)."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    """Adapt the site to the source contract."""

    id = "qiexs_cc"
    name = "企鹅小说"
    contract_version = "1.0"
    last_modified = "2026-07-27"
    base_url = "http://www.qiexs.cc"

    async def _fetch(self, ctx, url: str, **kwargs) -> str:
        """Fetch a site page through the host-owned HTTP bridge."""
        return await ctx.access.http.fetch_text(urljoin(self.base_url, url), **kwargs)

    async def search(self, ctx, keyword: str, page: int) -> list[dict]:
        """Search the site's POST endpoint."""
        keyword = (keyword or "").strip()
        if page > 1 or not keyword:
            return []
        html = await self._fetch(
            ctx,
            "/search/",
            method="POST",
            data={"keyword": keyword},
            headers={"Referer": self.base_url},
        )
        items = self._parse_search(ctx, html)
        exact = [item for item in items if item.get("name") == keyword]
        return await enrich_search_items_from_detail(self, ctx, exact or items)

    def _parse_search(self, ctx, html: str) -> list[dict]:
        """Parse one result block per book."""
        soup = BeautifulSoup(html or "", "html.parser")
        items: list[dict] = []
        seen: set[str] = set()
        for title_node in soup.select("h4.bookTitle a[href]"):
            href = title_node.get("href", "").strip()
            if not re.search(r"/xiaoshuo/\d+\.html", href):
                continue
            book_url = self._local_url(href)
            if book_url in seen:
                continue
            seen.add(book_url)
            # The keyword is wrapped in <em>; take the text, not the title attribute.
            name = ctx.clean_text(title_node.get_text("", strip=True))
            block = title_node.find_parent("div", class_="col-md-10")
            author = ""
            intro = ""
            last = ""
            cover = ""
            if block is not None:
                author_node = block.select_one("p.booktag a[href*='/author/']")
                if author_node is not None:
                    author = ctx.clean_text(author_node.get_text(" ", strip=True))
                intro_node = block.select_one("#bookIntro")
                if intro_node is not None:
                    intro = ctx.clean_text(intro_node.get_text(" ", strip=True))
                last_node = block.select_one("a.text-danger[href]")
                if last_node is not None:
                    last = ctx.clean_text(last_node.get_text(" ", strip=True))
                row = block.parent
                if row is not None:
                    img = row.select_one("img[src]")
                    if img is not None:
                        cover = img.get("src", "").strip()
            items.append(
                {
                    "sourceId": self.id,
                    "name": name,
                    "author": author,
                    "bookUrl": book_url,
                    "coverUrl": self._local_url(cover) if cover else "",
                    "intro": intro,
                    "kind": "",
                    "lastChapter": last,
                    "wordCount": "",
                    "rank": len(items) + 1,
                }
            )
        return items

    async def detail(self, ctx, book_url: str) -> dict:
        """Read the book metadata from the detail page."""
        book_url = self._local_url(book_url)
        html = await self._fetch(ctx, book_url)
        name = self._meta(ctx, html, "og:novel:book_name") or ctx.text(html, "h1.bookTitle")
        author = self._meta(ctx, html, "og:novel:author")
        category = self._meta(ctx, html, "og:novel:category")
        status = ctx.clean_text(self._meta(ctx, html, "og:novel:status"))
        cover = self._meta(ctx, html, "og:image")
        intro = self._meta(ctx, html, "og:description") or ctx.text(html, "#bookIntro")
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
            "wordCount": self._word_count(html),
            "updateTime": update_time,
            "tocUrl": book_url,
            "authRequired": False,
        }

    def _meta(self, ctx, html: str, property_name: str) -> str:
        """Return one OpenGraph property value."""
        return ctx.attr(html, f'meta[property="{property_name}"]', "content")

    def _word_count(self, html: str) -> str:
        """Read '字数：163万' from the info bar."""
        soup = BeautifulSoup(html or "", "html.parser")
        for span in soup.select("p.booktag span"):
            text = span.get_text(" ", strip=True)
            if text.startswith("字数："):
                return text.split("：", 1)[1].strip()
        return ""

    def _local_url(self, url: str) -> str:
        """Normalize to the verified origin."""
        value = (url or "").strip()
        if value.startswith(("http://www.qiexs.cc", "https://www.qiexs.cc")):
            value = value.split("www.qiexs.cc", 1)[1]
        return urljoin(self.base_url, value)

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        """Parse the complete catalog block on the book page.

        The page also renders a reverse-ordered '最新章节' preview above it; only
        the ``#list-chapterAll`` block holds the full reading-order catalog.
        """
        toc_url = self._local_url(toc_url)
        html = await self._fetch(ctx, toc_url)
        soup = BeautifulSoup(html or "", "html.parser")
        block = soup.select_one("#list-chapterAll")
        chapters: list[dict] = []
        seen: set[str] = set()
        if block is None:
            return chapters
        for a in block.select("dd a[href]"):
            href = a.get("href", "").strip()
            if not re.search(r"/xiaoshuo/\d+/\d+\.html", href):
                continue
            chapter_url = self._local_url(href)
            title = ctx.clean_text(a.get("title", "")) or ctx.clean_text(a.get_text(" ", strip=True))
            if not title or chapter_url in seen:
                continue
            seen.add(chapter_url)
            chapters.append(
                {
                    "sourceId": self.id,
                    "index": len(chapters) + 1,
                    "title": title,
                    "chapterUrl": chapter_url,
                    "updateTime": "",
                    "isVip": False,
                    "isLocked": False,
                }
            )
        return chapters

    async def chapter(self, ctx, chapter_url: str) -> dict:
        """Read one chapter body."""
        chapter_url = self._local_url(chapter_url)
        html = await self._fetch(ctx, chapter_url)
        title = ctx.clean_text(ctx.text(html, "h1")) or ctx.clean_text(ctx.text(html, ".panel-heading"))
        return {
            "sourceId": self.id,
            "title": title,
            "chapterUrl": chapter_url,
            "content": self._chapter_content(ctx, html),
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _chapter_content(self, ctx, html: str) -> str:
        """Convert the paragraph layout into clean plain text."""
        soup = BeautifulSoup(html or "", "html.parser")
        container = soup.select_one("#htmlContent")
        if container is None:
            return ""
        for tag in container.find_all(["script", "style", "ins", "iframe", "div"]):
            tag.decompose()
        for br in container.find_all("br"):
            br.replace_with("\n")
        paragraphs = [ctx.clean_text(p.get_text(" ", strip=True)) for p in container.find_all("p")]
        paragraphs = [p for p in paragraphs if p and not self._is_noise(p)]
        if not paragraphs:
            text = ctx.clean_text(container.get_text("\n", strip=True))
            paragraphs = [line for line in text.splitlines() if line and not self._is_noise(line)]
        return "\n\n".join(paragraphs).strip()

    def _is_noise(self, line: str) -> bool:
        """Drop site navigation and promo lines."""
        if len(line) > 60:
            return False
        return any(
            marker in line
            for marker in ("企鹅小说", "最新网址", "加入书签", "返回目录", "手机阅读", "温馨提示")
        )
