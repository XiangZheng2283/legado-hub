"""0xs (零点小说) source plugin."""

import base64
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from app.source_plugins.errors import FetchHttp4xx
from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "0xs_net"
    name = "零点小说"
    contract_version = "1.0"
    last_modified = "2026-07-28"
    base_url = "https://m.0xs.net"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
        ),
    }

    async def _fetch(self, ctx, url: str, **kwargs) -> str:
        headers = {**self.headers, **kwargs.pop("headers", {})}
        try:
            return await ctx.access.http.fetch_text(url, headers=headers, **kwargs)
        except FetchHttp4xx:
            # The mobile site occasionally requires one browser visit to mint
            # its session cookies; subsequent pages remain plain HTTP.
            await ctx.access.browser.fetch_text(url, headers=headers, wait_ms=500)
            return await ctx.access.http.fetch_text(url, headers=headers, **kwargs)

    async def search(self, ctx, keyword: str, page: int):
        items = []
        html = await self._fetch(
            ctx,
            f"{self.base_url}/search",
            params={"kw": keyword},
        )
        for anchor in ctx.select(html, ".template-02 .show > ul > a[href]"):
            href = anchor.get("href", "")
            name = ctx.text(anchor, ".name")
            if not href or not name:
                continue
            status = ctx.text(anchor, ".serial")
            category = ctx.text(anchor, ".type")
            cover_url = ctx.attr(anchor, "img", "data-original")
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": ctx.text(anchor, ".author"),
                "bookUrl": urljoin(self.base_url, href),
                "coverUrl": urljoin(self.base_url, cover_url) if cover_url else "",
                "intro": ctx.text(anchor, ".desc"),
                "kind": "/".join(part for part in [category, status] if part),
                "wordCount": ctx.text(anchor, ".count"),
            })
        return await enrich_search_items_from_detail(self, ctx, items)

    async def detail(self, ctx, book_url: str):
        html = await self._fetch(ctx, book_url)
        name = ctx.text(html, ".book .name") or ctx.text(html, "h1") or ""
        author = ctx.text(html, ".book .author")
        intro = ctx.text(html, ".book-intro .desc")
        match = re.search(r"/txt_(\d+)/(\d+)", book_url)
        toc_url = f"{self.base_url}/la_{match.group(1)}/{match.group(2)}" if match else book_url
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "intro": intro,
            "tocUrl": toc_url,
            "authRequired": False,
            "extra": {},
        }

    async def toc(self, ctx, toc_url: str):
        chapters = []
        seen = set()
        match = re.search(r"/la_(\d+)/(\d+)", toc_url)
        if not match:
            return []
        kind, book_id = match.groups()
        book_url = f"{self.base_url}/txt_{kind}/{book_id}"
        await self._fetch(ctx, book_url)
        first_html = await self._fetch(ctx, toc_url, headers={"Referer": book_url})
        page_values = [option.get("value", "") for option in ctx.select(first_html, ".pagelist option")]
        page_count = max([int(value) for value in page_values if value.isdigit()] or [1])
        for page in range(1, page_count + 1):
            html = first_html if page == 1 else await self._fetch(
                ctx,
                f"{toc_url}/{page}",
                headers={"Referer": book_url},
            )
            for anchor in ctx.select(html, f'a[href^="/txt_{kind}/{book_id}/"]'):
                href = anchor.get("href", "")
                title = ctx.clean_text(anchor.text_content())
                chapter_url = urljoin(self.base_url, href)
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

    def _clean_chapter_content(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "iframe", "ins", "center"]):
            tag.decompose()
        for div in soup.find_all("div"):
            text = div.get_text(strip=True)
            if len(text) < 120 and any(kw in text for kw in ["广告", "声明", "本章结束", "返回目录", "加入书签", "推荐", "最新网址", "章节内容缺失", "章节不存在", "零点小说", "0xs", "加载更多", "无法显示本章节全部内容"]):
                div.decompose()
        for br in soup.find_all("br"):
            br.replace_with("\n")
        paragraphs = []
        for p in soup.find_all("p"):
            text = p.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)
        if paragraphs:
            return "\n\n".join(paragraphs)
        text = soup.get_text("\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n\n".join(lines)

    async def chapter(self, ctx, chapter_url: str):
        parts = []
        current_url = chapter_url
        title = ""
        chapter_match = re.search(r"(/txt_\d+/\d+/\d+)", chapter_url)
        chapter_prefix = chapter_match.group(1) if chapter_match else chapter_url
        seen_urls = set()
        while current_url and len(parts) < 10:
            if current_url in seen_urls:
                break
            seen_urls.add(current_url)
            html = await self._fetch(ctx, current_url, headers={"Referer": chapter_url})
            if not title:
                title = ctx.text(html, ".title") or ctx.text(html, "h1")
            content_html = ctx.html(html, ".content") or ctx.html(html, "#content")
            encoded = re.search(r"p_key\s*=\s*'([^']+)'", html)
            if encoded:
                try:
                    content_html += base64.b64decode(encoded.group(1)).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    pass
            content = self._clean_chapter_content(content_html)
            if content:
                parts.append(content)
            next_href = ""
            for anchor in ctx.select(html, ".page a[href]"):
                if "下一页" in ctx.clean_text(anchor.text_content()):
                    next_href = anchor.get("href", "")
                    break
            if not next_href or next_href == "javascript:void(0);":
                break
            next_url = urljoin(chapter_url, next_href)
            if chapter_prefix not in next_url:
                break
            current_url = next_url
        title = re.sub(r"[（(][\d/]+[）)]", "", title or "").strip()
        full_content = "\n\n".join(parts)
        return {
            "sourceId": self.id,
            "title": title,
            "content": full_content,
            "chapterUrl": chapter_url,
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }
