"""Plugin for 小说路上 (xs63e.com)."""

from __future__ import annotations

import base64
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


BOOK_PATH_RE = re.compile(r"^/([a-z0-9_-]+)/([a-z0-9_-]+)/?$", re.I)
CHAPTER_PATH_RE = re.compile(r"^/([a-z0-9_-]+)/([a-z0-9_-]+)/\d+\.html$", re.I)
JSSTR_RE = re.compile(r"var\s+jsstr\s*=\s*['\"]([^'\"]+)['\"]")
JSARR_RE = re.compile(r"var\s+jsarr\s*=\s*\[([^]]+)\]")
LASTREAD_RE = re.compile(
    r"lastread\.set\([^,]+,\s*['\"][^'\"]*['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]",
    re.S,
)


class Source:
    id = "xs63b_com"
    name = "小说路上"
    contract_version = "1.0"
    last_modified = "2026-07-31"
    base_url = "https://m.xs63e.com"

    async def _fetch(self, ctx, url: str, **kwargs) -> str:
        return await ctx.access.http.fetch_text(self._local_url(url), **kwargs)

    async def search(self, ctx, keyword: str, page: int) -> list[dict]:
        keyword = ctx.clean_text(keyword or "")
        if not keyword or page != 1:
            return []
        home = await self._fetch(ctx, self.base_url + "/")
        token_node = BeautifulSoup(home or "", "html.parser").select_one('input[name="_token"]')
        token = token_node.get("value", "").strip() if token_node else ""
        if not token:
            raise ValueError("xs63b search token is missing")
        html = await self._fetch(
            ctx,
            self.base_url + "/search",
            method="POST",
            data={"_token": token, "kw": keyword},
            headers={"Referer": self.base_url + "/"},
        )
        parsed = self._parse_search(ctx, html)
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
        detail = await self.detail(ctx, trusted[0]["bookUrl"])
        detail["rank"] = 1
        return [detail]

    def _parse_search(self, ctx, html: str) -> list[dict]:
        soup = BeautifulSoup(html or "", "html.parser")
        items: list[dict] = []
        seen: set[str] = set()
        for row in soup.select("li"):
            link = row.select_one(".s2 a[href]")
            if link is None:
                continue
            book_url = self._book_url(link.get("href", ""))
            if not BOOK_PATH_RE.fullmatch(urlparse(book_url).path) or book_url in seen:
                continue
            seen.add(book_url)
            category = ctx.clean_text(self._text(row, ".s1")).strip("[]【】")
            items.append(
                {
                    "sourceId": self.id,
                    "name": ctx.clean_text(link.get_text("", strip=True)),
                    "author": ctx.clean_text(self._text(row, ".s3")),
                    "bookUrl": book_url,
                    "tocUrl": book_url,
                    "coverUrl": "",
                    "intro": "",
                    "kind": category,
                    "bookStatus": "",
                    "lastChapter": "",
                    "wordCount": "",
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
        chapters = self._catalog_links(ctx, soup, book_url)
        status = ctx.clean_text(self._meta(soup, "og:novel:status"))
        category = ctx.clean_text(self._meta(soup, "og:novel:category"))
        intro = re.sub(
            r"^简介\s*[:：]\s*",
            "",
            ctx.clean_text(self._meta(soup, "og:description")),
        )
        return {
            "sourceId": self.id,
            "name": ctx.clean_text(self._meta(soup, "og:novel:book_name")),
            "author": ctx.clean_text(self._meta(soup, "og:novel:author")),
            "bookUrl": book_url,
            "tocUrl": book_url,
            "coverUrl": self._meta(soup, "og:image"),
            "intro": intro,
            "kind": " / ".join(part for part in (category, status) if part),
            "bookStatus": status,
            "lastChapter": ctx.clean_text(self._meta(soup, "og:novel:latest_chapter_name")),
            "wordCount": "",
            "updateTime": ctx.clean_text(self._meta(soup, "og:novel:update_time")),
            "chapterCount": len(chapters),
            "authRequired": False,
        }

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        book_url = self._book_url(toc_url)
        soup = BeautifulSoup(await self._fetch(ctx, book_url), "html.parser")
        return [
            {
                "sourceId": self.id,
                "index": index,
                "title": title,
                "chapterUrl": chapter_url,
                "updateTime": "",
                "isVip": False,
                "isLocked": False,
            }
            for index, (title, chapter_url) in enumerate(
                self._catalog_links(ctx, soup, book_url),
                start=1,
            )
        ]

    async def chapter(self, ctx, chapter_url: str) -> dict:
        chapter_url = self._chapter_url(chapter_url)
        current_url = chapter_url
        title = ""
        parts: list[str] = []
        seen: set[str] = set()
        for _ in range(10):
            if current_url in seen:
                raise ValueError("xs63b chapter pagination loop")
            seen.add(current_url)
            html = await self._fetch(ctx, current_url)
            soup = BeautifulSoup(html or "", "html.parser")
            if not title:
                title = self._chapter_title(ctx, soup, html)
            content, incomplete = self._chapter_content(ctx, soup)
            if content:
                parts.append(content)
            next_control = soup.select_one("#pb_next")
            next_chapter = next_control.get("href", "").strip() if next_control else ""
            if next_chapter:
                break
            next_page = self._generated_next_page(html, current_url)
            if not next_page:
                if incomplete:
                    raise ValueError("xs63b chapter continuation is missing")
                break
            current_url = next_page
        else:
            raise ValueError("xs63b chapter pagination exceeded 10 pages")
        return {
            "sourceId": self.id,
            "title": title,
            "chapterUrl": chapter_url,
            "content": "\n\n".join(parts).strip(),
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _catalog_links(self, ctx, soup, book_url: str) -> list[tuple[str, str]]:
        block = None
        for heading in soup.select("div.intro"):
            if ctx.clean_text(heading.get_text(" ", strip=True)) == "正文":
                block = heading.find_next_sibling("ul", class_="chapter")
                break
        if block is None:
            return []
        rows: list[tuple[str, str]] = []
        seen: set[str] = set()
        book_path = urlparse(book_url).path.rstrip("/") + "/"
        for link in block.select("a[href]"):
            chapter_url = self._local_url(link.get("href", ""))
            path = urlparse(chapter_url).path
            if not CHAPTER_PATH_RE.fullmatch(path) or not path.startswith(book_path) or chapter_url in seen:
                continue
            title = ctx.clean_text(link.get("title") or link.get_text(" ", strip=True))
            if not title:
                continue
            seen.add(chapter_url)
            rows.append((title, chapter_url))
        return rows

    def _chapter_content(self, ctx, soup) -> tuple[str, bool]:
        container = soup.select_one("#nr1")
        if container is None:
            return "", False
        for tag in container.select("script, style"):
            tag.decompose()
        raw = container.get_text("\n", strip=True)
        incomplete = "本章未完" in raw or "中#间#有#缺失" in raw
        lines = []
        for line in raw.splitlines():
            text = ctx.clean_text(line)
            if text and not self._is_noise(text):
                lines.append(text)
        return "\n\n".join(lines), incomplete

    def _generated_next_page(self, html: str, current_url: str) -> str:
        encoded_match = JSSTR_RE.search(html or "")
        order_match = JSARR_RE.search(html or "")
        if not encoded_match or not order_match:
            return ""
        try:
            decoded = base64.b64decode(encoded_match.group(1), validate=True).decode("ascii")
            order = [int(value.strip()) for value in order_match.group(1).split(",")]
        except (ValueError, UnicodeError) as exc:
            raise ValueError("invalid xs63b continuation payload") from exc
        if not order or len(order) != len(decoded) or len(set(order)) != len(order):
            raise ValueError("invalid xs63b continuation order")
        if any(index < 0 or index >= len(decoded) for index in order):
            raise ValueError("xs63b continuation index is out of range")
        slug = "".join(decoded[index] for index in order)
        if not re.fullmatch(r"[A-Za-z0-9]+", slug):
            raise ValueError("invalid xs63b continuation slug")
        return current_url.rsplit("/", 1)[0] + "/" + slug + ".html"

    def _chapter_title(self, ctx, soup, html: str) -> str:
        match = LASTREAD_RE.search(html or "")
        if match:
            return ctx.clean_text(match.group(2))
        heading = ctx.clean_text(self._text(soup, "h1"))
        document_title = ctx.clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
        title_parts = document_title.split("_")
        if len(title_parts) > 1 and title_parts[1] and title_parts[0].startswith(title_parts[1]):
            return title_parts[0][len(title_parts[1]) :].strip()
        return heading

    def _is_noise(self, text: str) -> bool:
        return any(
            marker in text
            for marker in (
                "如章节缺失请退#出#阅#读#模#式",
                "中#间#有#缺失",
                "本章未完，点下一页继续阅读",
            )
        )

    def _book_url(self, url: str) -> str:
        value = self._local_url(url)
        match = BOOK_PATH_RE.fullmatch(urlparse(value).path)
        if not match:
            raise ValueError("invalid xs63b book URL")
        return f"{self.base_url}/{match.group(1)}/{match.group(2)}/"

    def _chapter_url(self, url: str) -> str:
        value = self._local_url(url)
        if not re.fullmatch(r"/[a-z0-9_-]+/[a-z0-9_-]+/[A-Za-z0-9]+\.html", urlparse(value).path, re.I):
            raise ValueError("invalid xs63b chapter URL")
        return value

    def _local_url(self, url: str) -> str:
        value = (url or "").strip()
        if not value:
            return ""
        parsed = urlparse(value)
        if parsed.netloc and parsed.netloc not in {
            "xs63b.com",
            "m.xs63b.com",
            "xs63e.com",
            "m.xs63e.com",
        }:
            raise ValueError(f"unexpected xs63b host: {parsed.netloc}")
        if parsed.netloc:
            value = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        return urljoin(self.base_url, value)

    def _meta(self, soup, prop: str) -> str:
        node = soup.select_one(f'meta[property="{prop}"]')
        return node.get("content", "").strip() if node else ""

    def _text(self, node, selector: str) -> str:
        found = node.select_one(selector)
        return found.get_text(" ", strip=True) if found is not None else ""

    def _lookup_key(self, value: str) -> str:
        return re.sub(r"\W+", "", (value or "")).lower()
