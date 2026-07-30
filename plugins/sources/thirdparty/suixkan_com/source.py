"""Plugin for 随心看 (m.suixkan.com)."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.source_plugins.search_enrichment import enrich_search_items_from_detail

# Book links are opened by an onclick handler instead of an href.
WEBVIEW_RE = re.compile(r"newWebView\(\s*'([^']+)'")


class Source:
    """Adapt the mobile site to the source contract."""

    id = "suixkan_com"
    name = "随心看"
    contract_version = "1.0"
    last_modified = "2026-07-27"
    base_url = "https://m.suixkan.com"

    async def _fetch(self, ctx, url: str, **kwargs) -> str:
        """Fetch a site page through the host-owned HTTP bridge."""
        return await ctx.access.http.fetch_text(urljoin(self.base_url, url), **kwargs)

    async def search(self, ctx, keyword: str, page: int) -> list[dict]:
        """Search the site's result list."""
        keyword = (keyword or "").strip()
        if page > 1 or not keyword:
            return []
        html = await self._fetch(ctx, "/s/1.html", params={"keyword": keyword})
        items = self._parse_search(ctx, html)
        exact = [item for item in items if item.get("name") == keyword]
        return await enrich_search_items_from_detail(self, ctx, exact or items)

    def _parse_search(self, ctx, html: str) -> list[dict]:
        """Parse one list item per book."""
        soup = BeautifulSoup(html or "", "html.parser")
        items: list[dict] = []
        seen: set[str] = set()
        for node in soup.select(".v-list-item"):
            match = WEBVIEW_RE.search(node.get("onclick", "") or "")
            if match is None:
                continue
            href = match.group(1)
            if not re.match(r"^/b/\d+\.html$", href):
                continue
            book_url = self._local_url(href)
            if book_url in seen:
                continue
            seen.add(book_url)
            cover_node = node.select_one("img.v-cover-img")
            items.append(
                {
                    "sourceId": self.id,
                    "name": ctx.clean_text(self._text(node, ".v-title")),
                    "author": ctx.clean_text(self._text(node, ".v-author")),
                    "bookUrl": book_url,
                    "coverUrl": (cover_node.get("src", "").strip() if cover_node else ""),
                    "intro": ctx.clean_text(self._text(node, ".v-intro")),
                    "kind": ctx.clean_text(self._text(node, ".base-label")),
                    "lastChapter": "",
                    "wordCount": ctx.clean_text(self._text(node, ".v-words")),
                    "rank": len(items) + 1,
                }
            )
        return items

    def _text(self, node, selector: str) -> str:
        """Return the text of the first matching child, or an empty string."""
        found = node.select_one(selector)
        return found.get_text(" ", strip=True) if found is not None else ""

    async def detail(self, ctx, book_url: str) -> dict:
        """Read the book metadata from the detail page."""
        book_url = self._local_url(book_url)
        html = await self._fetch(ctx, book_url)
        soup = BeautifulSoup(html or "", "html.parser")
        labels = self._info_labels(soup)
        cover_node = soup.select_one("img.face-cover-img")
        intro_node = soup.select_one(".content-intro")
        book_id = self._book_id(book_url)
        return {
            "sourceId": self.id,
            "name": ctx.clean_text(self._text(soup, ".face-info-title")),
            "author": ctx.clean_text(labels.get("作者", "")),
            "bookUrl": book_url,
            "coverUrl": (cover_node.get("src", "").strip() if cover_node else ""),
            "intro": ctx.clean_text(intro_node.get_text(" ", strip=True)) if intro_node else "",
            "kind": ctx.clean_text(labels.get("分类", "")),
            "lastChapter": "",
            "wordCount": ctx.clean_text(labels.get("字数", "")),
            "updateTime": "",
            "tocUrl": self._local_url(f"/c/{book_id}.html") if book_id else book_url,
            "authRequired": False,
        }

    def _info_labels(self, soup) -> dict[str, str]:
        """Parse the '作者：/分类：/字数：' rows of the info block."""
        labels: dict[str, str] = {}
        for span in soup.select(".face-info .v-words span"):
            text = span.get_text(" ", strip=True)
            if "：" in text:
                key, value = text.split("：", 1)
                labels[key.strip()] = value.strip()
        return labels

    def _book_id(self, url: str) -> str:
        """Extract the numeric book id from a /b/ or /c/ URL."""
        match = re.search(r"/[bc]/(\d+)\.html", url or "")
        return match.group(1) if match else ""

    def _local_url(self, url: str) -> str:
        """Normalize to the verified origin."""
        value = (url or "").strip()
        for host in ("m.suixkan.com", "www.suixkan.com"):
            if value.startswith((f"http://{host}", f"https://{host}")):
                value = value.split(host, 1)[1]
                break
        return urljoin(self.base_url, value)

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        """Parse the single-page complete catalog."""
        toc_url = self._local_url(toc_url)
        book_id = self._book_id(toc_url)
        if book_id and "/c/" not in toc_url:
            toc_url = self._local_url(f"/c/{book_id}.html")
        html = await self._fetch(ctx, toc_url)
        soup = BeautifulSoup(html or "", "html.parser")
        chapters: list[dict] = []
        seen: set[str] = set()
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            if not re.match(rf"^/r/{book_id or r'\d+'}/\d+\.html$", href):
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
        """Read one chapter body.

        The whole chapter ships in a single page, split into ``div.section``
        blocks titled '第一章：…(1/5)', '(2/5)' …; only the first block is
        visible without JavaScript, but all of them are in the HTML.
        """
        chapter_url = self._local_url(chapter_url)
        html = await self._fetch(ctx, chapter_url)
        soup = BeautifulSoup(html or "", "html.parser")
        title = ctx.clean_text(self._text(soup, ".section h2"))
        parts: list[str] = []
        for section in soup.select(".book .section"):
            container = section.select_one(".con")
            if container is None:
                continue
            for tag in container.find_all(["script", "style", "ins", "iframe"]):
                tag.decompose()
            for br in container.find_all("br"):
                br.replace_with("\n")
            for p in container.find_all("p"):
                line = ctx.clean_text(p.get_text(" ", strip=True))
                if line and not self._is_noise(line):
                    parts.append(line)
        return {
            "sourceId": self.id,
            "title": self._strip_page_marker(title),
            "chapterUrl": chapter_url,
            "content": "\n\n".join(parts).strip(),
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _strip_page_marker(self, title: str) -> str:
        """Drop the '(1/5)' page marker from the chapter title."""
        return re.sub(r"[（(]\s*\d+\s*/\s*\d+\s*[)）]\s*$", "", title or "").strip()

    def _is_noise(self, line: str) -> bool:
        """Drop the site's page-break markers and navigation lines."""
        if len(line) > 40:
            return False
        return any(
            marker in line
            for marker in ("本章未完", "请翻页", "本章完", "随心看", "加入书签", "下一章", "上一章")
        )
