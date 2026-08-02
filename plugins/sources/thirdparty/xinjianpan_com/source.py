"""Plugin for 新键盘小说网 (xinjianpan.com)."""

from __future__ import annotations

import base64
import re
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup


BOOK_RE = re.compile(r"/txt/([^/]+)/?$")
LOCATION_RE = re.compile(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]")
PAYLOAD_RE = re.compile(r"\bvar\s+c\s*=\s*(['\"])(.*?)\1", re.S)


class Source:
    id = "xinjianpan_com"
    name = "新键盘小说网"
    contract_version = "1.0"
    last_modified = "2026-07-31"
    base_url = "https://www.xinjianpan.com"

    async def _fetch(self, ctx, url: str) -> str:
        return await ctx.access.http.fetch_text(self._local_url(url))

    async def search(self, ctx, keyword: str, page: int) -> list[dict]:
        keyword = ctx.clean_text(keyword or "")
        if not keyword or page < 1:
            return []
        suffix = "" if page == 1 else f"&page={page}"
        url = f"{self.base_url}/search/?searchkey={quote(keyword)}{suffix}"
        parsed = self._parse_search(ctx, await self._fetch(ctx, url))
        target = self._lookup_key(keyword)
        exact = [item for item in parsed if self._lookup_key(item["name"]) == target]
        trusted = exact or [
            item
            for item in parsed
            if target in self._lookup_key(item["name"])
            or self._lookup_key(item["name"]) in target
        ]
        if not trusted:
            return []
        best = max(trusted, key=lambda item: (self._word_count(item["wordCount"]), -item["rank"]))
        detail = await self.detail(ctx, best["bookUrl"])
        for field in ("wordCount", "kind", "bookStatus", "intro", "coverUrl"):
            if not detail.get(field) and best.get(field):
                detail[field] = best[field]
        detail["rank"] = 1
        return [detail]

    def _parse_search(self, ctx, html: str) -> list[dict]:
        soup = BeautifulSoup(html or "", "html.parser")
        items: list[dict] = []
        seen: set[str] = set()
        for row in soup.select("dl"):
            link = row.select_one('dt a[href^="/txt/"]')
            if link is None:
                continue
            book_url = self._book_url(link.get("href", ""))
            if not BOOK_RE.search(urlparse(book_url).path) or book_url in seen:
                continue
            seen.add(book_url)
            dds = row.select("dd")
            meta = dds[-1] if len(dds) > 1 else None
            spans = [ctx.clean_text(node.get_text(" ", strip=True)) for node in meta.select("span")] if meta else []
            author_node = meta.select_one("a") if meta else None
            cover = row.select_one("a.cover img")
            status = spans[0] if spans else ""
            category = spans[2] if len(spans) > 2 else ""
            items.append(
                {
                    "sourceId": self.id,
                    "name": ctx.clean_text(link.get_text("", strip=True)),
                    "author": ctx.clean_text(author_node.get_text(" ", strip=True)) if author_node else "",
                    "bookUrl": book_url,
                    "tocUrl": urljoin(book_url, "list-1.html"),
                    "coverUrl": self._local_url((cover.get("data-src") or cover.get("src") or "")) if cover else "",
                    "intro": ctx.clean_text(dds[0].get_text(" ", strip=True)) if dds else "",
                    "kind": " / ".join(part for part in (category, status) if part),
                    "bookStatus": status,
                    "lastChapter": "",
                    "wordCount": spans[1] if len(spans) > 1 else "",
                    "updateTime": "",
                    "chapterCount": 0,
                    "rank": len(items) + 1,
                }
            )
        return items

    async def detail(self, ctx, book_url: str) -> dict:
        book_url = self._book_url(book_url)
        html = await self._fetch(ctx, book_url)
        soup = BeautifulSoup(html or "", "html.parser")
        toc_link = soup.select_one('a[href*="list-1.html"]')
        toc_url = self._local_url(toc_link.get("href", "")) if toc_link else urljoin(book_url, "list-1.html")
        toc_html = await self._fetch(ctx, toc_url)
        status = self._meta(soup, "og:novel:status")
        category = self._meta(soup, "og:novel:category")
        return {
            "sourceId": self.id,
            "name": ctx.clean_text(self._meta(soup, "og:novel:book_name") or self._meta(soup, "og:title")),
            "author": ctx.clean_text(self._meta(soup, "og:novel:author")),
            "bookUrl": book_url,
            "tocUrl": toc_url,
            "coverUrl": self._local_url(self._meta(soup, "og:image")),
            "intro": ctx.clean_text(self._meta(soup, "og:description")),
            "kind": " / ".join(part for part in (category, status) if part),
            "bookStatus": status,
            "lastChapter": ctx.clean_text(self._meta(soup, "og:novel:latest_chapter_name")),
            "wordCount": "",
            "updateTime": ctx.clean_text(self._meta(soup, "og:novel:update_time")),
            "chapterCount": self._catalog_total(toc_html, toc_url),
            "authRequired": False,
        }

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        toc_url = self._toc_url(toc_url)
        first_html = await self._fetch(ctx, toc_url)
        pages = self._catalog_pages(first_html, toc_url)
        chapters: list[dict] = []
        seen: set[str] = set()
        book_slug = self._book_slug(toc_url)
        for index, page_url in enumerate(pages):
            html = first_html if index == 0 else await self._fetch(ctx, page_url)
            for title, chapter_url in self._parse_catalog_page(ctx, html, book_slug):
                if chapter_url in seen:
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
        chapter_url = self._local_url(chapter_url)
        html = await self._fetch(ctx, chapter_url)
        soup = BeautifulSoup(html or "", "html.parser")
        title_node = soup.select_one("h1")
        title = ctx.clean_text(title_node.get_text(" ", strip=True)) if title_node else ""
        container = soup.select_one("#chaptercontent")
        if container is None:
            content = ""
        else:
            placeholder = container.select_one("#morecontent")
            if placeholder is not None:
                placeholder.decompose()
            parts = self._paragraphs(ctx, container)
            payload = PAYLOAD_RE.search(html)
            if payload:
                decoded = BeautifulSoup(self._decode_payload(payload.group(2)), "html.parser")
                parts.extend(self._paragraphs(ctx, decoded))
            elif "更多内容加载中" in html:
                raise ValueError("encrypted chapter payload is missing")
            content = "\n\n".join(parts).strip()
        return {
            "sourceId": self.id,
            "title": title,
            "chapterUrl": chapter_url,
            "content": content,
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _decode_payload(self, ciphertext: str) -> str:
        try:
            outer = base64.b64decode(ciphertext, validate=True).decode("ascii")
            if len(outer) < 12 or not outer[8:11].isdigit():
                raise ValueError("invalid payload header")
            trim = int(outer[8:11])
            if trim < 0 or 11 + (trim * 2) >= len(outer):
                raise ValueError("invalid payload trim")
            encoded = outer[11 + trim : len(outer) - trim]
            encoded = encoded.replace("-", "PHA+").replace("_", "8L3A+")
            return base64.b64decode(encoded, validate=True).decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise ValueError("invalid encrypted chapter payload") from exc

    def _paragraphs(self, ctx, node) -> list[str]:
        parts: list[str] = []
        for paragraph in node.select("p"):
            text = ctx.clean_text(paragraph.get_text(" ", strip=True))
            if text and not self._is_noise(text):
                parts.append(text)
        return parts

    def _is_noise(self, text: str) -> bool:
        return any(
            marker in text
            for marker in (
                "天才一秒记住",
                "更多内容加载中",
                "转载请注明来源",
                "浏览器显示没有新章节",
            )
        )

    def _catalog_pages(self, html: str, toc_url: str) -> list[str]:
        soup = BeautifulSoup(html or "", "html.parser")
        book_slug = self._book_slug(toc_url)
        pages = {
            self._local_url(option.get("value", ""))
            for option in soup.select("select option[value]")
            if re.search(rf"/txt/{re.escape(book_slug)}/list-\d+\.html$", option.get("value", ""))
        }
        pages.add(toc_url)
        return sorted(pages, key=self._page_number)

    def _catalog_total(self, html: str, toc_url: str) -> int:
        soup = BeautifulSoup(html or "", "html.parser")
        totals = []
        for option in soup.select("select option[value]"):
            match = re.search(r"(\d+)\s*章", option.get_text(" ", strip=True))
            if match:
                totals.append(int(match.group(1)))
        if totals:
            return max(totals)
        return len(self._parse_catalog_page(None, html, self._book_slug(toc_url)))

    def _parse_catalog_page(self, ctx, html: str, book_slug: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html or "", "html.parser")
        rows: list[tuple[str, str]] = []
        for link in soup.select("a[onclick]"):
            match = LOCATION_RE.search(link.get("onclick", ""))
            if not match:
                continue
            chapter_url = self._local_url(match.group(1))
            if not re.search(rf"/txt/{re.escape(book_slug)}/(?!list-)[^/?#]+\.html$", chapter_url):
                continue
            raw_title = link.get("title") or link.get_text(" ", strip=True)
            title = ctx.clean_text(raw_title) if ctx is not None else raw_title.strip()
            if title:
                rows.append((title, chapter_url))
        return rows

    def _book_url(self, url: str) -> str:
        value = self._local_url(url)
        match = BOOK_RE.search(urlparse(value).path)
        return f"{self.base_url}/txt/{match.group(1)}/" if match else value

    def _toc_url(self, url: str) -> str:
        value = self._local_url(url)
        slug = self._book_slug(value)
        return f"{self.base_url}/txt/{slug}/list-1.html" if slug else value

    def _book_slug(self, url: str) -> str:
        match = re.search(r"/txt/([^/]+)/", urlparse(url).path)
        return match.group(1) if match else ""

    def _local_url(self, url: str) -> str:
        value = (url or "").strip()
        if not value:
            return ""
        parsed = urlparse(value)
        if parsed.netloc and parsed.netloc not in {"xinjianpan.com", "www.xinjianpan.com"}:
            raise ValueError(f"unexpected xinjianpan host: {parsed.netloc}")
        if parsed.netloc:
            value = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        return urljoin(self.base_url, value)

    def _meta(self, soup, prop: str) -> str:
        node = soup.select_one(f'meta[property="{prop}"]')
        return node.get("content", "").strip() if node else ""

    def _lookup_key(self, value: str) -> str:
        return re.sub(r"\W+", "", (value or "")).lower()

    def _word_count(self, value: str) -> float:
        match = re.search(r"([\d.]+)\s*([万亿]?)", value or "")
        if not match:
            return 0
        factor = {"": 1, "万": 10_000, "亿": 100_000_000}[match.group(2)]
        return float(match.group(1)) * factor

    def _page_number(self, url: str) -> int:
        match = re.search(r"/list-(\d+)\.html$", urlparse(url).path)
        return int(match.group(1)) if match else 1
