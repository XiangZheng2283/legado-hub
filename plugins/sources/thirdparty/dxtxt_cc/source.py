"""Plugin for 独行txt小说站 (www.dxtxt.cc)."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.source_plugins.search_enrichment import enrich_search_items_from_detail

MAX_CHAPTER_PAGES = 12


class Source:
    """Adapt the site to the source contract."""

    id = "dxtxt_cc"
    name = "独行小说"
    contract_version = "1.0"
    last_modified = "2026-07-27"
    base_url = "http://www.dxtxt.cc"

    async def _fetch(self, ctx, url: str, **kwargs) -> str:
        """Fetch a site page through the host-owned HTTP bridge."""
        return await ctx.access.http.fetch_text(urljoin(self.base_url, url), **kwargs)

    async def search(self, ctx, keyword: str, page: int) -> list[dict]:
        """Search the site's CSRF-protected POST endpoint."""
        keyword = (keyword or "").strip()
        if page > 1 or not keyword:
            return []
        home = await self._fetch(ctx, "/")
        token = ctx.attr(home, 'input[name="_token"]', "value")
        if not token:
            ctx.trace("search_token_missing", url=self.base_url, message="no _token on home page")
            return []
        html = await self._fetch(
            ctx,
            "/search",
            method="POST",
            data={"_token": token, "keyword": keyword, "searchtype": "articlename"},
            headers={"Referer": self.base_url},
        )
        items = self._parse_search(ctx, html)
        exact = [item for item in items if item.get("name") == keyword]
        return await enrich_search_items_from_detail(self, ctx, exact or items)

    def _parse_search(self, ctx, html: str) -> list[dict]:
        """Parse one ``dl`` block per book."""
        soup = BeautifulSoup(html or "", "html.parser")
        items: list[dict] = []
        seen: set[str] = set()
        for block in soup.select("#sitebox dl"):
            title_node = block.select_one("dd h3 a[href]")
            if title_node is None:
                continue
            href = title_node.get("href", "").strip()
            if not re.search(r"/noveltxt/[^/]+\.html$", href):
                continue
            book_url = self._local_url(href)
            if book_url in seen:
                continue
            seen.add(book_url)
            # The keyword is wrapped in <em>, so read the text instead of @title.
            name = ctx.clean_text(title_node.get_text("", strip=True))
            cover = ""
            img = block.select_one("dt img")
            if img is not None:
                cover = img.get("_src", "") or img.get("src", "")
            intro = ""
            intro_node = block.select_one("dd.book_des")
            if intro_node is not None:
                intro = ctx.clean_text(intro_node.get_text(" ", strip=True))
            kind, word_count = self._other_fields(ctx, block)
            last = ""
            for other in block.select("dd.book_other a[href]"):
                last = ctx.clean_text(other.get_text(" ", strip=True))
            items.append(
                {
                    "sourceId": self.id,
                    "name": name,
                    "author": "",
                    "bookUrl": book_url,
                    "coverUrl": self._local_url(cover) if cover else "",
                    "intro": intro,
                    "kind": kind,
                    "lastChapter": last,
                    "wordCount": word_count,
                    "rank": len(items) + 1,
                }
            )
        return items

    def _other_fields(self, ctx, block) -> tuple[str, str]:
        """Read '子类/状态/字数' from the first ``dd.book_other`` row."""
        row = block.select_one("dd.book_other")
        if row is None:
            return "", ""
        text = ctx.clean_text(row.get_text(" ", strip=True))
        kind_parts = []
        for label in ("子类", "状态"):
            m = re.search(rf"{label}[:：]\s*(\S+)", text)
            if m:
                kind_parts.append(m.group(1))
        m = re.search(r"字数[:：]\s*(\S+)", text)
        return " / ".join(kind_parts), (m.group(1) if m else "")

    async def detail(self, ctx, book_url: str) -> dict:
        """Read the book metadata from the detail page."""
        book_url = self._local_url(book_url)
        html = await self._fetch(ctx, book_url)
        name = self._meta(ctx, html, "og:novel:book_name") or ctx.text(html, "h1")
        category = self._meta(ctx, html, "og:novel:category")
        status = self._meta(ctx, html, "og:novel:status")
        cover = self._meta(ctx, html, "og:image")
        return {
            "sourceId": self.id,
            "name": name,
            "author": self._meta(ctx, html, "og:novel:author"),
            "bookUrl": book_url,
            "coverUrl": self._local_url(cover) if cover else "",
            "intro": ctx.clean_text(self._meta(ctx, html, "og:description")),
            "kind": " / ".join(part for part in [category, status] if part),
            "lastChapter": self._meta(ctx, html, "og:novel:latest_chapter_name"),
            "wordCount": "",
            "updateTime": self._meta(ctx, html, "og:novel:update_time"),
            "tocUrl": book_url,
            "authRequired": False,
        }

    def _meta(self, ctx, html: str, property_name: str) -> str:
        """Return one OpenGraph property value."""
        return ctx.attr(html, f'meta[property="{property_name}"]', "content")

    def _local_url(self, url: str) -> str:
        """Normalize to the verified origin."""
        value = (url or "").strip()
        if value.startswith(("http://www.dxtxt.cc", "https://www.dxtxt.cc")):
            value = value.split("www.dxtxt.cc", 1)[1]
        return urljoin(self.base_url, value)

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        """Parse the complete catalog list on the book page.

        ``#chapterList`` is the full reading-order catalog; the list above it is
        a reverse-ordered '最新章节' preview.
        """
        toc_url = self._local_url(toc_url)
        html = await self._fetch(ctx, toc_url)
        soup = BeautifulSoup(html or "", "html.parser")
        block = soup.select_one("#chapterList")
        chapters: list[dict] = []
        if block is None:
            return chapters
        seen: set[str] = set()
        for a in block.select("li a[href]"):
            href = a.get("href", "").strip()
            if not re.search(r"/noveltxt/[^/]+/\d+\.html$", href):
                continue
            chapter_url = self._local_url(href)
            title = ctx.clean_text(a.get_text(" ", strip=True))
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
        """Read one chapter body, merging the site's same-chapter pagination.

        The '下一页' button carries no href (it is written by an obfuscated
        script), and the last page keeps advertising a next page while serving
        the same text. Pages are therefore walked by URL pattern and stopped on
        repeated content.
        """
        chapter_url = self._local_url(chapter_url)
        stem = re.sub(r"(_\d+)?\.html$", "", chapter_url)
        html = await self._fetch(ctx, chapter_url)
        title = ctx.clean_text(ctx.text(html, "#mlfy_main_text h1")) or ctx.clean_text(ctx.text(html, "h1"))
        first = self._page_content(ctx, html)
        parts = [first]
        previous = first
        page = 2
        while page <= MAX_CHAPTER_PAGES and self._has_next_page(html):
            page_url = f"{stem}_{page}.html"
            try:
                html = await self._fetch(ctx, page_url)
            except Exception as exc:
                ctx.trace("chapter_pagination_error", url=page_url, message=str(exc))
                break
            content = self._page_content(ctx, html)
            if not content or content == previous:
                break
            parts.append(content)
            previous = content
            page += 1
        return {
            "sourceId": self.id,
            "title": self._strip_page_marker(title),
            "chapterUrl": chapter_url,
            "content": "\n\n".join(part for part in parts if part).strip(),
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _has_next_page(self, html: str) -> bool:
        """True while the pager still shows a '下一页' control."""
        soup = BeautifulSoup(html or "", "html.parser")
        pager = soup.select_one("#nr_page")
        if pager is None:
            return False
        return "下一页" in pager.get_text(" ", strip=True)

    def _strip_page_marker(self, title: str) -> str:
        """Drop trailing page markers such as '(2/3)'."""
        return re.sub(r"[（(]\s*\d+\s*/\s*\d+\s*[)）]\s*$", "", title or "").strip()

    def _page_content(self, ctx, html: str) -> str:
        """Extract clean text from one chapter page."""
        soup = BeautifulSoup(html or "", "html.parser")
        container = soup.select_one("#TextContent")
        if container is None:
            return ""
        for tag in container.find_all(["script", "style", "ins", "iframe", "dt"]):
            tag.decompose()
        for br in container.find_all("br"):
            br.replace_with("\n")
        paragraphs = [ctx.clean_text(p.get_text(" ", strip=True)) for p in container.find_all("p")]
        paragraphs = [p for p in paragraphs if p and not self._is_noise(p)]
        if not paragraphs:
            text = ctx.clean_text(container.get_text("\n", strip=True))
            paragraphs = [line for line in text.splitlines() if line and not self._is_noise(line)]
        return "\n\n".join(paragraphs)

    def _is_noise(self, line: str) -> bool:
        """Drop site navigation and reading-mode warnings."""
        stripped = line.replace("#", "")
        if len(stripped) > 60:
            return False
        return any(
            marker in stripped
            for marker in ("独行", "阅读模式", "浏览器", "最新网址", "加入书签", "章节目录", "手机阅读")
        )
