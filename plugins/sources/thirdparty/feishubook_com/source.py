"""Plugin for the current myfeishu.com endpoint of feishubook_com."""

from __future__ import annotations

import base64
import hashlib
import re
import unicodedata
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad


BOOK_RE = re.compile(r"/book/\d+/?$")
CATALOG_PAGE_RE = re.compile(r"/catalog/(?:d_)?(\d+)\.html")
CHAPTER_RE = re.compile(r"/book/\d+/\d+\.html$")
DECRYPT_RE = re.compile(
    r'(?:decryptFunc|d)\(\s*"((?:\\.|[^"\\])*)"\s*,\s*"([^"\\]+)"\s*\)',
    re.S,
)


class Source:
    id = "feishubook_com"
    name = "飞书小说网"
    contract_version = "1.0"
    last_modified = "2026-07-31"
    base_url = "https://www.myfeishu.com"

    async def _fetch(self, ctx, url: str) -> str:
        return await ctx.access.http.fetch_text(url)

    async def search(self, ctx, keyword: str, page: int) -> list[dict]:
        keyword = self._clean(keyword)
        if not keyword or page < 1:
            return []
        search_url = f"{self.base_url}/search/{quote(keyword)}/{page}"
        html = await self._fetch(ctx, search_url)
        target = self._lookup_key(keyword)
        matches = [
            item
            for item in self._parse_search(html, search_url)
            if target in self._lookup_key(item["name"])
            or target in self._lookup_key(item["author"])
        ]
        results: list[dict] = []
        for item in matches[:3]:
            detail = await self.detail(ctx, item["bookUrl"])
            detail["rank"] = len(results) + 1
            results.append(detail)
        return results

    def _parse_search(self, html: str, search_url: str) -> list[dict]:
        soup = BeautifulSoup(html or "", "html.parser")
        items: list[dict] = []
        seen: set[str] = set()
        for row in soup.select(".SHsectionThree-middle p"):
            links = row.select("a[href]")
            book = next((a for a in links if BOOK_RE.search(a.get("href", ""))), None)
            if book is None:
                continue
            book_url = urljoin(search_url, book.get("href", ""))
            if book_url in seen:
                continue
            seen.add(book_url)
            author = next((a for a in links if "/writer/" in a.get("href", "")), None)
            items.append(
                {
                    "name": self._clean(book.get_text("", strip=True)),
                    "author": self._clean(author.get_text("", strip=True)) if author else "",
                    "bookUrl": book_url,
                }
            )
        return items

    async def detail(self, ctx, book_url: str) -> dict:
        book_url = self._book_url(book_url)
        html = await self._fetch(ctx, book_url)
        soup = BeautifulSoup(html or "", "html.parser")
        toc_link = next(
            (a for a in soup.select("a[href]") if "章节目录" in a.get_text("", strip=True)),
            None,
        )
        toc_url = urljoin(book_url, toc_link.get("href", "")) if toc_link else f"{book_url}catalog/"
        chapters = await self._catalog(ctx, toc_url)
        status = self._status(self._meta(soup, "og:novel:status"))
        category = self._meta(soup, "og:novel:category")
        return {
            "sourceId": self.id,
            "name": self._clean(self._meta(soup, "og:title") or self._text(soup, ".title")),
            "author": self._clean(self._meta(soup, "og:novel:author") or self._text(soup, ".author a")),
            "bookUrl": book_url,
            "tocUrl": toc_url,
            "coverUrl": urljoin(book_url, self._meta(soup, "og:image")),
            "intro": self._clean(self._meta(soup, "og:description") or self._text(soup, ".BGsectionTwo-bottom")),
            "kind": " / ".join(part for part in (category, status) if part),
            "bookStatus": status or "状态未知",
            "lastChapter": chapters[-1]["title"] if chapters else "",
            "wordCount": "",
            "updateTime": self._clean(self._meta(soup, "og:novel:update_time")),
            "chapterCount": len(chapters),
            "authRequired": False,
        }

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        return await self._catalog(ctx, self._toc_url(toc_url))

    async def _catalog(self, ctx, toc_url: str) -> list[dict]:
        first_html = await self._fetch(ctx, toc_url)
        pages = self._page_count(first_html)
        rows = self._catalog_page(first_html, toc_url)
        for page in range(2, pages + 1):
            page_url = f"{toc_url.rstrip('/')}/{page}.html"
            rows.extend(self._catalog_page(await self._fetch(ctx, page_url), page_url))
        chapters: list[dict] = []
        seen: set[str] = set()
        for title, chapter_url in rows:
            if not title or not chapter_url or chapter_url in seen:
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

    def _catalog_page(self, html: str, page_url: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html or "", "html.parser")
        rows: list[tuple[int, str, str]] = []
        for fallback, node in enumerate(soup.select("li.BCsectionTwo-top-chapter")):
            link = node.select_one("a[href]")
            if link is None:
                continue
            order = next(
                (
                    int(str(value))
                    for key, value in node.attrs.items()
                    if key != "data-id" and str(value).isdigit()
                ),
                fallback,
            )
            href = link.get("href", "")
            title = self._clean(link.get("data-real", ""))
            for key, value in link.attrs.items():
                if not key.startswith("data-"):
                    continue
                decoded = self._decode_chapter_url(str(value))
                if decoded:
                    href = decoded
                elif not title and not str(value).isdigit():
                    title = self._clean(str(value))
            if not title:
                title = self._clean(link.get_text("", strip=True))
            chapter_url = urljoin(page_url, href)
            if CHAPTER_RE.search(chapter_url):
                rows.append((order, title, chapter_url))
        rows.sort(key=lambda item: item[0])
        return [(title, url) for _order, title, url in rows]

    def _decode_chapter_url(self, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return ""
        return decoded if CHAPTER_RE.search(decoded) else ""

    def _page_count(self, html: str) -> int:
        pages = [int(value) for value in CATALOG_PAGE_RE.findall(html or "")]
        return max(pages, default=1)

    async def chapter(self, ctx, chapter_url: str) -> dict:
        html = await self._fetch(ctx, chapter_url)
        soup = BeautifulSoup(html or "", "html.parser")
        match = DECRYPT_RE.search(html)
        content_html = self._decrypt(match.group(1), match.group(2)) if match else ""
        if not content_html:
            node = soup.select_one(".RBGsectionThree-content")
            content_html = str(node) if node else ""
        return {
            "sourceId": self.id,
            "title": self._clean(self._text(soup, "#chapterTitle")),
            "chapterUrl": chapter_url,
            "content": self._content(content_html),
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _decrypt(self, encoded: str, secret: str) -> str:
        cipher = base64.b64decode(encoded.replace(r"\/", "/"))
        digest = hashlib.md5(secret.encode("utf-8")).hexdigest()
        plain = AES.new(
            digest[16:].encode("ascii"),
            AES.MODE_CBC,
            digest[:16].encode("ascii"),
        ).decrypt(cipher)
        return unpad(plain, AES.block_size).decode("utf-8")

    def _content(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for node in soup.select("script, style"):
            node.decompose()
        lines = [self._clean(node.get_text(" ", strip=True)) for node in soup.select("p")]
        if not lines:
            lines = [self._clean(line) for line in soup.get_text("\n").splitlines()]
        return "\n\n".join(line for line in lines if line and not self._noise(line))

    def _noise(self, text: str) -> bool:
        return any(
            marker in text
            for marker in ("Loading...", "未加载完", "尝试【刷新】", "收藏网址：", "移动流量偶尔")
        )

    def _meta(self, soup: BeautifulSoup, key: str) -> str:
        node = soup.select_one(f'meta[property="{key}"]')
        return node.get("content", "") if node else ""

    def _text(self, soup: BeautifulSoup, selector: str) -> str:
        node = soup.select_one(selector)
        return node.get_text(" ", strip=True) if node else ""

    def _status(self, value: str) -> str:
        if "完结" in (value or "") or "完本" in (value or ""):
            return "已完结"
        if "连载" in (value or ""):
            return "连载中"
        return self._clean(value)

    def _clean(self, value: str) -> str:
        visible = "".join(char for char in str(value or "") if unicodedata.category(char) != "Cf")
        return " ".join(visible.split())

    def _lookup_key(self, value: str) -> str:
        return re.sub(r"\s+", "", self._clean(value)).casefold()

    def _book_url(self, value: str) -> str:
        url = urljoin(self.base_url, value or "")
        match = re.search(r"(https?://[^/]+/book/\d+/)", url)
        return match.group(1) if match else url

    def _toc_url(self, value: str) -> str:
        url = urljoin(self.base_url, value or "")
        match = re.search(r"(https?://[^/]+/book/\d+/catalog/)", url)
        return match.group(1) if match else f"{self._book_url(url)}catalog/"
