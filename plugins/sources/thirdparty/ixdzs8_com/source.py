"""爱下电子书 source plugin."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


class Source:
    id = "ixdzs8_com"
    name = "爱下电子书"
    contract_version = "1.0"
    last_modified = "2026-07-31"
    base_url = "https://ixdzs8.com"

    def _url(self, value: str) -> str:
        return urljoin(self.base_url, value or "")

    def _meta(self, soup: BeautifulSoup, name: str) -> str:
        node = soup.select_one(f'meta[property="{name}"]')
        return node.get("content", "").strip() if node is not None else ""

    def _text(self, node, selector: str) -> str:
        found = node.select_one(selector)
        return found.get_text(" ", strip=True) if found is not None else ""

    async def search(self, ctx, keyword: str, page: int) -> list[dict]:
        keyword = (keyword or "").strip()
        if not keyword:
            return []
        html = await ctx.access.http.fetch_text(
            f"{self.base_url}/bsearch",
            params={"q": keyword, "page": max(page, 1)},
        )
        items: list[dict] = []
        for node in BeautifulSoup(html or "", "html.parser").select("ul.u-list > li"):
            link = node.select_one("h3.bname a[href]")
            if link is None:
                continue
            name = ctx.clean_text(link.get_text(" ", strip=True))
            book_url = self._url(link.get("href", ""))
            if not name or not re.search(r"/read/\d+/$", book_url):
                continue
            image = node.select_one("img[src]")
            status = self._text(node, ".l-p1 .end, .l-p1 .lz")
            latest_link = node.select_one(".l-last a[href]")
            latest_href = latest_link.get("href", "") if latest_link is not None else ""
            chapter_match = re.search(r"/p(\d+)\.html$", latest_href)
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": self._text(node, ".bauthor"),
                "bookUrl": book_url,
                "tocUrl": book_url,
                "coverUrl": self._url(image.get("src", "")) if image is not None else "",
                "intro": self._text(node, ".l-p2"),
                "kind": status,
                "bookStatus": status,
                "lastChapter": self._text(node, ".l-chapter"),
                "wordCount": self._text(node, ".size"),
                "updateTime": self._text(node, ".l-time"),
                "chapterCount": int(chapter_match.group(1)) if chapter_match else 0,
                "rank": len(items) + 1,
            })
        exact = [item for item in items if item["name"] == keyword]
        return exact or items

    async def detail(self, ctx, book_url: str) -> dict:
        book_url = self._url(book_url)
        soup = BeautifulSoup(await ctx.access.http.fetch_text(book_url), "html.parser")
        category = self._meta(soup, "og:novel:category")
        status = self._meta(soup, "og:novel:status")
        chapter_match = re.search(r"\d+", self._text(soup, "h2.catalog .sub-text-r"))
        intro = self._text(soup, "#intro")
        if not intro:
            intro = BeautifulSoup(self._meta(soup, "og:description"), "html.parser").get_text(" ", strip=True)
        return {
            "sourceId": self.id,
            "name": self._meta(soup, "og:novel:book_name") or self._text(soup, "h1"),
            "author": self._meta(soup, "og:novel:author") or self._text(soup, "a.bauthor"),
            "bookUrl": book_url,
            "coverUrl": self._meta(soup, "og:image"),
            "intro": ctx.clean_text(intro),
            "kind": " / ".join(value for value in (category, status) if value),
            "bookStatus": status,
            "lastChapter": self._meta(soup, "og:novel:latest_chapter_name"),
            "wordCount": self._text(soup, ".nsize"),
            "updateTime": self._meta(soup, "og:novel:update_time"),
            "tocUrl": book_url,
            "chapterCount": int(chapter_match.group(0)) if chapter_match else 0,
            "authRequired": False,
        }

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        toc_url = self._url(toc_url)
        match = re.search(r"/read/(\d+)/", urlparse(toc_url).path)
        if not match:
            return []
        book_id = match.group(1)
        payload = await ctx.access.http.fetch_json(
            f"{self.base_url}/novel/clist/",
            method="POST",
            data={"bid": book_id},
            headers={"Referer": toc_url},
        )
        chapters: list[dict] = []
        for item in payload.get("data", []):
            order = str(item.get("ordernum", ""))
            title = ctx.clean_text(str(item.get("title", "")))
            if not order.isdigit() or not title:
                continue
            chapters.append({
                "sourceId": self.id,
                "index": len(chapters) + 1,
                "title": title,
                "chapterUrl": f"{self.base_url}/read/{book_id}/p{order}.html",
                "isVip": False,
                "isLocked": False,
            })
        return chapters

    def _chapter_content(self, ctx, html: str, title: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        content = soup.select_one("article.page-content")
        if content is None:
            return ""
        for tag in content.select("script, style, h3"):
            tag.decompose()
        paragraphs = [ctx.clean_text(node.get_text(" ", strip=True)) for node in content.select("p")]
        if paragraphs and re.sub(r"\s+", "", paragraphs[0]) == re.sub(r"\s+", "", title):
            paragraphs.pop(0)
        return "\n\n".join(text for text in paragraphs if text)

    async def chapter(self, ctx, chapter_url: str) -> dict:
        chapter_url = self._url(chapter_url)
        html = await ctx.access.http.fetch_text(chapter_url, headers={"Referer": chapter_url})
        if "正在验证浏览器" in html or "正在進行安全驗證" in html:
            html = await ctx.access.browser.fetch_text(chapter_url, wait_ms=2500, timeout_ms=60000)
        title = ctx.text(html, "h1.page-d-name") or ctx.text(html, "article.page-content h3")
        return {
            "sourceId": self.id,
            "title": title,
            "chapterUrl": chapter_url,
            "content": self._chapter_content(ctx, html, title),
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }
