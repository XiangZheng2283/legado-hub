"""Template source plugin."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "example_com"
    name = "示例书源"
    contract_version = "1.0"
    base_url = "https://example.com"

    async def search(self, ctx, keyword: str, page: int):
        html = await ctx.access.http.fetch_text(
            f"{self.base_url}/search",
            params={"q": keyword, "page": page},
        )
        items = []
        for row in ctx.select(html, ".result-item"):
            href = ctx.attr(row, "a", "href")
            name = ctx.text(row, ".title") or ctx.text(row, "a")
            if not href or not name:
                continue
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": ctx.text(row, ".author"),
                "bookUrl": urljoin(self.base_url, href),
                "coverUrl": urljoin(self.base_url, ctx.attr(row, "img", "src")),
                "intro": ctx.text(row, ".intro"),
                "kind": ctx.text(row, ".kind"),
                "lastChapter": ctx.text(row, ".latest"),
                "wordCount": ctx.text(row, ".word-count"),
                "updateTime": ctx.text(row, ".update-time"),
            })
        # If search results omit author/latest/kind/wordCount, enrich here.
        return await enrich_search_items_from_detail(self, ctx, items)

    async def detail(self, ctx, book_url: str):
        html = await ctx.access.http.fetch_text(book_url)
        kind = ctx.attr(html, 'meta[property="og:novel:category"]', "content") or ctx.text(html, ".kind")
        status = ctx.attr(html, 'meta[property="og:novel:status"]', "content") or ctx.text(html, ".status")
        return {
            "sourceId": self.id,
            "name": ctx.attr(html, 'meta[property="og:novel:book_name"]', "content") or ctx.text(html, "h1"),
            "author": ctx.attr(html, 'meta[property="og:novel:author"]', "content") or ctx.text(html, ".author").replace("作者：", "").strip(),
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, ctx.attr(html, 'meta[property="og:image"]', "content") or ctx.attr(html, ".cover img", "src")),
            "intro": ctx.attr(html, 'meta[property="og:description"]', "content") or ctx.text(html, ".intro"),
            "kind": " / ".join(part for part in [kind, status] if part),
            "lastChapter": ctx.attr(html, 'meta[property="og:novel:latest_chapter_name"]', "content") or ctx.text(html, ".latest"),
            "wordCount": ctx.text(html, ".word-count"),
            "updateTime": ctx.attr(html, 'meta[property="og:novel:update_time"]', "content") or ctx.text(html, ".update-time"),
            "tocUrl": book_url,
            "authRequired": False,
            "extra": {
                "status": status,
            },
        }

    async def toc(self, ctx, toc_url: str):
        html = await self._fetch_complete_toc_html(ctx, toc_url)
        chapters = []
        seen: set[str] = set()
        for a in ctx.select(html, "#list dd a, .catalog a, .chapter-list a"):
            href = a.get("href", "")
            title = ctx.clean_text(a.text_content())
            chapter_url = urljoin(toc_url, href)
            if not href or not title or chapter_url in seen:
                continue
            seen.add(chapter_url)
            chapters.append({
                "sourceId": self.id,
                "index": len(chapters) + 1,
                "title": title,
                "chapterUrl": chapter_url,
                "isVip": False,
                "isLocked": False,
            })
        return chapters

    async def _fetch_complete_toc_html(self, ctx, toc_url: str) -> str:
        """Prefer complete AJAX/API chapter lists; fall back to detail HTML."""
        api_url = self._chapterlist_api_url(toc_url)
        api_html = ""
        if api_url:
            try:
                api_html = await ctx.access.http.fetch_text(api_url, headers={"referer": toc_url})
            except Exception as exc:
                ctx.trace("toc_api_fallback", url=api_url, message=str(exc))
        try:
            html = await ctx.access.http.fetch_text(toc_url)
        except Exception as exc:
            if api_html and ctx.select(api_html, "a"):
                ctx.trace("toc_static_fallback_to_api", url=toc_url, message=str(exc))
                return api_html
            raise
        if not api_url:
            return html
        if api_html and len(ctx.select(api_html, "a")) > len(ctx.select(html, "a")):
            return api_html
        return html

    def _chapterlist_api_url(self, toc_url: str) -> str:
        """Return site-specific chapter list API URL when one exists."""
        return ""

    async def chapter(self, ctx, chapter_url: str):
        parts: list[str] = []
        current_url = chapter_url
        title = ""
        original_stem = self._chapter_stem(chapter_url)
        while current_url and len(parts) < 10:
            html = await ctx.access.http.fetch_text(current_url)
            if not title:
                title = ctx.text(html, "h1") or ctx.text(html, ".title")
            content_html = ctx.html(html, "#content") or ctx.html(html, ".content") or ctx.html(html, "#txt")
            content = self._clean_chapter_content(content_html)
            if content:
                parts.append(content)
            next_href = ctx.attr(html, "#next_url", "href") or ctx.attr(html, "a:contains('下一页')", "href")
            if not next_href or next_href.startswith("javascript:"):
                break
            next_url = urljoin(current_url, next_href)
            if self._chapter_stem(next_url) != original_stem:
                break
            current_url = next_url
        return {
            "sourceId": self.id,
            "chapterUrl": chapter_url,
            "title": re.sub(r"[（(](?:\d+/\d+|第?\d+页)[）)]", "", title or "").strip(),
            "content": "\n\n".join(parts),
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _chapter_stem(self, url: str) -> str:
        path = url.split("?", 1)[0].split("#", 1)[0]
        if "_" in path:
            return path.rsplit("_", 1)[0]
        return path.rsplit(".", 1)[0] if "." in path else path

    def _clean_chapter_content(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "iframe", "ins", "center"]):
            tag.decompose()
        for tag in soup.find_all("br"):
            tag.replace_with("\n")
        text = soup.get_text("\n", strip=True)
        lines = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if any(kw in line for kw in ["最新网址", "加入书签", "返回目录", "推荐阅读", "章节内容缺失", "下载APP"]):
                continue
            lines.append(line)
        return "\n\n".join(lines)
