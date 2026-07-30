"""Plugin for the reachable 零点看书 IP endpoint."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "lingdiankanshu_com"
    name = "零点看书"
    contract_version = "1.0"
    last_modified = "2026-07-30"
    base_url = "http://23.225.143.226"

    async def _fetch(self, ctx, url: str, **kwargs) -> str:
        return await ctx.access.http.fetch_text(self._local_url(url), **kwargs)

    def _local_url(self, url: str) -> str:
        value = (url or "").strip()
        for origin in (
            "http://www.23txti.com",
            "https://www.23txti.com",
            "http://23.225.143.226",
        ):
            if value.startswith(origin):
                value = value[len(origin):]
                break
        return urljoin(self.base_url, value)

    async def search(self, ctx, keyword: str, page: int) -> list[dict]:
        keyword = (keyword or "").strip()
        if page > 1 or not keyword:
            return []
        html = await self._fetch(ctx, "/ar.php", params={"keyWord": keyword})
        soup = BeautifulSoup(html or "", "html.parser")
        items: list[dict] = []
        seen: set[str] = set()
        for row in soup.select("ul.txt-list li"):
            link = row.select_one('.s2 a[href*="/ldks/"]')
            if link is None:
                continue
            book_url = self._local_url(link.get("href", ""))
            if not re.search(r"/ldks/\d+/$", book_url) or book_url in seen:
                continue
            seen.add(book_url)
            items.append({
                "sourceId": self.id,
                "name": ctx.clean_text(link.get_text(" ", strip=True)),
                "author": ctx.clean_text(self._text(row, ".s4")),
                "bookUrl": book_url,
                "coverUrl": "",
                "intro": "",
                "kind": ctx.clean_text(self._text(row, ".s1")).strip("[]"),
                "lastChapter": ctx.clean_text(self._text(row, ".s3 a")),
                "wordCount": "",
                "updateTime": ctx.clean_text(self._text(row, ".s5")),
                "rank": len(items) + 1,
            })
        exact = [item for item in items if item["name"] == keyword]
        return await enrich_search_items_from_detail(self, ctx, exact or items, limit=2)

    def _text(self, node, selector: str) -> str:
        found = node.select_one(selector)
        return found.get_text(" ", strip=True) if found is not None else ""

    def _meta(self, soup, name: str) -> str:
        node = soup.select_one(f'meta[property="{name}"]')
        return node.get("content", "").strip() if node is not None else ""

    async def detail(self, ctx, book_url: str) -> dict:
        book_url = self._local_url(book_url)
        soup = BeautifulSoup(await self._fetch(ctx, book_url), "html.parser")
        cover = self._meta(soup, "og:image")
        if not cover:
            image = soup.select_one(".imgbox img[src]")
            cover = image.get("src", "") if image is not None else ""
        category = self._meta(soup, "og:novel:category")
        status = self._meta(soup, "og:novel:status")
        return {
            "sourceId": self.id,
            "name": self._meta(soup, "og:novel:book_name") or self._text(soup, ".info h1"),
            "author": self._meta(soup, "og:novel:author"),
            "bookUrl": book_url,
            "coverUrl": self._local_url(cover) if cover else "",
            "intro": self._meta(soup, "og:description") or self._text(soup, ".desc"),
            "kind": " / ".join(part for part in (category, status) if part),
            "lastChapter": self._meta(soup, "og:novel:latest_chapter_name") or self._text(soup, '.info p a[rel="nofollow"]'),
            "wordCount": "",
            "updateTime": self._meta(soup, "og:novel:update_time"),
            "tocUrl": book_url,
            "authRequired": False,
        }

    def _book_id(self, url: str) -> str:
        match = re.search(r"/ldks/(\d+)/", url)
        return match.group(1) if match else ""

    def _catalog_urls(self, soup, toc_url: str) -> list[str]:
        urls = [toc_url]
        for option in soup.select('select[name="pageselect"] option[value]'):
            url = self._local_url(option.get("value", ""))
            if url not in urls:
                urls.append(url)
        return urls

    def _parse_chapters(self, ctx, html: str, book_id: str, seen: set[str]) -> list[dict]:
        soup = BeautifulSoup(html or "", "html.parser")
        block = None
        for heading in soup.select("h2"):
            if "正文" in heading.get_text(" ", strip=True):
                block = heading.find_next_sibling("div", class_="section-box")
                break
        chapters: list[dict] = []
        if block is None:
            return chapters
        for link in block.select("a[href]"):
            chapter_url = self._local_url(link.get("href", ""))
            if not re.search(rf"/ldks/{book_id}/\d+\.html$", chapter_url) or chapter_url in seen:
                continue
            title = ctx.clean_text(link.get_text(" ", strip=True))
            if not title:
                continue
            seen.add(chapter_url)
            chapters.append({
                "sourceId": self.id,
                "index": len(seen),
                "title": title,
                "chapterUrl": chapter_url,
                "updateTime": "",
                "isVip": False,
                "isLocked": False,
            })
        return chapters

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        toc_url = self._local_url(toc_url)
        book_id = self._book_id(toc_url)
        if not book_id:
            return []
        first_html = await self._fetch(ctx, toc_url)
        urls = self._catalog_urls(BeautifulSoup(first_html, "html.parser"), toc_url)
        chapters: list[dict] = []
        seen: set[str] = set()
        for index, url in enumerate(urls):
            html = first_html if index == 0 else await self._fetch(ctx, url, headers={"Referer": toc_url})
            chapters.extend(self._parse_chapters(ctx, html, book_id, seen))
        return chapters

    def _chapter_stem(self, url: str) -> str:
        return re.sub(r"_\d+(?=\.html$)", "", url)

    def _chapter_content(self, ctx, html: str, title: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        container = soup.select_one("#content")
        if container is None:
            return ""
        for tag in container.select("script, style, h1"):
            tag.decompose()
        paragraphs: list[str] = []
        for raw_line in container.get_text("\n").splitlines():
            text = re.sub(r"\(第\d+/\d+页\)", "", raw_line)
            text = text.replace("（本章未完，请点击下一页继续阅读）", "")
            text = ctx.clean_text(text)
            if not text or (title and text == title):
                continue
            paragraphs.append(text)
        return "\n\n".join(paragraphs)

    async def chapter(self, ctx, chapter_url: str) -> dict:
        chapter_url = self._local_url(chapter_url)
        stem = self._chapter_stem(chapter_url)
        current_url = chapter_url
        title = ""
        parts: list[str] = []
        seen: set[str] = set()
        while current_url and current_url not in seen:
            seen.add(current_url)
            html = await self._fetch(ctx, current_url, headers={"Referer": chapter_url})
            if not title:
                soup = BeautifulSoup(html or "", "html.parser")
                title = ctx.clean_text(self._text(soup, "#content h1.title"))
            content = self._chapter_content(ctx, html, title)
            if content:
                parts.append(content)
            soup = BeautifulSoup(html or "", "html.parser")
            next_url = ""
            for link in soup.select('a[href]'):
                if "下一页" in link.get_text(" ", strip=True):
                    candidate = self._local_url(link.get("href", ""))
                    if self._chapter_stem(candidate) == stem:
                        next_url = candidate
                    break
            current_url = next_url
        return {
            "sourceId": self.id,
            "title": title,
            "chapterUrl": chapter_url,
            "content": "\n\n".join(parts),
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }
