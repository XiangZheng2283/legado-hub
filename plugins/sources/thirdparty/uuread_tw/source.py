"""Plugin for UU阅读 (uuread.tw)."""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    """Adapt the site's Traditional Chinese pages to the source contract."""

    id = "uuread_tw"
    name = "UU阅读"
    contract_version = "1.0"
    last_modified = "2026-07-25"
    base_url = "http://www.uuread.tw"
    headers = {"accept-language": "zh-TW,zh;q=0.9"}

    def _s(self, ctx, value: str) -> str:
        """Normalize user-facing Traditional Chinese text."""
        return ctx.to_simplified(ctx.clean_text(value or ""))

    async def _fetch(self, ctx, url: str, **kwargs) -> str:
        """Fetch a site page through the host-owned HTTP bridge."""
        return await ctx.access.http.fetch_text(
            urljoin(self.base_url, url),
            headers=self.headers,
            **kwargs,
        )

    async def search(self, ctx, keyword: str, page: int) -> list[dict]:
        """Search the site's form endpoint."""
        if page > 1 or not keyword.strip():
            return []
        html = await self._fetch(
            ctx,
            "/search",
            method="POST",
            data={"searchkey": keyword.strip(), "searchtype": "all"},
        )
        items = self._parse_search(ctx, html)
        exact = [item for item in items if item.get("name") == keyword.strip()]
        return await enrich_search_items_from_detail(self, ctx, exact or items)

    def _parse_search(self, ctx, html: str) -> list[dict]:
        """Parse one list item per search result."""
        soup = BeautifulSoup(html or "", "html.parser")
        items: list[dict] = []
        seen: set[str] = set()
        for card in soup.select("ul.newlist > li.text-more"):
            title_node = card.select_one(".newlist-title a[href]")
            if title_node is None:
                continue
            href = title_node.get("href", "")
            book_url = self._local_url(href)
            name = self._s(ctx, title_node.get_text(" ", strip=True))
            if not href or not name or book_url in seen:
                continue
            seen.add(book_url)
            author_node = card.select_one(".newlist-zz a")
            latest_node = card.select_one(".newlist-zj a")
            items.append(
                {
                    "sourceId": self.id,
                    "name": name,
                    "author": self._s(ctx, author_node.get_text(" ", strip=True) if author_node else ""),
                    "bookUrl": book_url,
                    "coverUrl": "",
                    "intro": "",
                    "kind": "",
                    "lastChapter": self._s(ctx, latest_node.get_text(" ", strip=True) if latest_node else ""),
                    "wordCount": "",
                    "rank": len(items) + 1,
                }
            )
        return items

    async def detail(self, ctx, book_url: str) -> dict:
        """Read the book metadata and reuse the detail page as the catalog."""
        book_url = self._local_url(book_url)
        html = await self._fetch(ctx, book_url)
        name = self._meta(ctx, html, "og:novel:book_name") or self._meta(ctx, html, "og:title")
        category = self._meta(ctx, html, "og:novel:category")
        status = self._meta(ctx, html, "og:novel:status")
        cover = self._meta(ctx, html, "og:image") or ctx.attr(html, ".detail-body-body-img img", "src")
        return {
            "sourceId": self.id,
            "name": self._s(ctx, name),
            "author": self._s(ctx, self._meta(ctx, html, "og:novel:author")),
            "bookUrl": book_url,
            "coverUrl": self._local_url(cover) if cover else "",
            "intro": self._s(ctx, ctx.text(html, "#bookintro")),
            "kind": self._s(ctx, " / ".join(part for part in [category, status] if part)),
            "lastChapter": self._s(ctx, self._meta(ctx, html, "og:novel:latest_chapter_name")),
            "wordCount": "",
            "updateTime": self._meta(ctx, html, "og:novel:update_time"),
            "tocUrl": book_url,
            "authRequired": False,
        }

    def _meta(self, ctx, html: str, property_name: str) -> str:
        """Return one OpenGraph property value."""
        return ctx.attr(html, f'meta[property="{property_name}"]', "content")

    def _local_url(self, url: str) -> str:
        """Keep malformed canonical URLs and HTTPS links on the verified origin."""
        value = (url or "").replace("https://www.uuread.twhttps://", "https://")
        if value.startswith(("http://www.uuread.tw", "https://www.uuread.tw")):
            value = value.split("www.uuread.tw", 1)[1]
        return urljoin(self.base_url, value)

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        """Parse and deduplicate the complete catalog embedded in the detail page."""
        toc_url = self._local_url(toc_url)
        html = await self._fetch(ctx, toc_url)
        chapters: list[dict] = []
        seen: set[str] = set()
        for link in ctx.select(html, '#newlist a[href*="/chapter/"]'):
            href = link.get("href", "")
            chapter_url = self._local_url(href)
            title = self._s(ctx, link.text_content())
            if not href or not title or "欢迎收藏" in title or chapter_url in seen:
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
        title = ctx.text(html, ".play-title h1.chatit")
        content = self._chapter_content(ctx, html, title)
        return {
            "sourceId": self.id,
            "title": self._s(ctx, title),
            "chapterUrl": chapter_url,
            "content": self._s(ctx, content),
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _chapter_content(self, ctx, html: str, title: str) -> str:
        """Convert the paragraph layout into clean plain text."""
        soup = BeautifulSoup(html or "", "html.parser")
        container = soup.select_one("#nr")
        if container is None:
            return ""
        for node in container.select("script, style, iframe, .bottominfo"):
            node.decompose()
        for separator in container.select("br"):
            separator.replace_with("\n")
        lines = [ctx.clean_text(line) for line in container.get_text("\n").splitlines()]
        lines = [line for line in lines if line]
        if lines and ctx.clean_text(lines[0]) == ctx.clean_text(title):
            lines.pop(0)
        return "\n\n".join(lines).strip()
