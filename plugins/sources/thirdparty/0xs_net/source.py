"""0xs (零点小说) source plugin."""

import base64
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from app.source_plugins.errors import FetchHttp4xx


class Source:
    id = "0xs_net"
    name = "零点小说"
    contract_version = "1.0"
    last_modified = "2026-08-01"
    base_url = "https://www.0xs.net"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Upgrade-Insecure-Requests": "1",
    }
    page_continuation_pattern = re.compile(
        r"[（(]?本章未完[，,]?(?:请)?点击\s*\[?下一页\]?\s*继续阅读[）)]?(?:-+>>?)?"
    )

    @staticmethod
    def _is_error_page(html: str) -> bool:
        return 'class="error"' in html and "出错了" in html

    def _desktop_url(self, href: str) -> str:
        url = urljoin(self.base_url, href)
        if re.search(r"/(?:txt|la)_\d+/\d+(?:/\d+)?$", url):
            return f"{url}.html"
        return url

    async def _fetch(self, ctx, url: str, **kwargs) -> str:
        headers = {**self.headers, **kwargs.pop("headers", {})}
        try:
            html = await ctx.access.http.fetch_text(url, headers=headers, **kwargs)
        except FetchHttp4xx:
            html = ""
        if html and not self._is_error_page(html):
            return html
        browser_html = await ctx.access.browser.fetch_text(url, headers=headers, wait_ms=500)
        if browser_html and not self._is_error_page(browser_html):
            return browser_html
        return await ctx.access.http.fetch_text(url, headers=headers, **kwargs)

    async def search(self, ctx, keyword: str, page: int):
        items = []
        html = await self._fetch(
            ctx,
            f"{self.base_url}/search.html",
            params={"kw": keyword, "p": max(page, 1)},
        )
        result_nodes = ctx.select(html, ".result_list > ul > li")
        if not result_nodes:
            result_nodes = ctx.select(html, ".template-02 .show > ul > a[href]")
        for node in result_nodes:
            desktop_anchors = ctx.select(node, ".book .name > a[href]")
            anchor = desktop_anchors[0] if desktop_anchors else node
            href = anchor.get("href", "")
            name = ctx.clean_text(anchor.text_content()) if desktop_anchors else ctx.text(node, ".name")
            if not href or not name:
                continue
            status = ctx.text(node, ".serial")
            category = ctx.text(node, ".type")
            cover_url = ctx.attr(node, "img", "data-original") or ctx.attr(node, "img", "src")
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": ctx.text(node, ".author"),
                "bookUrl": self._desktop_url(href),
                "coverUrl": urljoin(self.base_url, cover_url) if cover_url else "",
                "intro": ctx.text(node, ".desc"),
                "kind": "/".join(part for part in [category, status] if part),
                "wordCount": ctx.text(node, ".count"),
            })
        return items

    async def detail(self, ctx, book_url: str):
        html = await self._fetch(ctx, book_url)
        name = ctx.text(html, ".book .name h1") or ctx.text(html, ".book .name") or ctx.text(html, "h1") or ""
        author = ctx.text(html, ".book .name > span") or ctx.text(html, ".book .author")
        author = re.sub(r"\s*[著作]\s*$", "", author).strip()
        intro = ctx.text(html, ".bookinfo .description") or ctx.text(html, ".book-intro .desc")
        cover = ctx.attr(html, ".book .image img", "data-original") or ctx.attr(html, ".book .image img", "src")
        latest = ctx.text(html, ".book .new + span a")
        toc_url = ctx.attr(html, ".catalog .title-right a", "href")
        match = re.search(r"/txt_(\d+)/(\d+)", book_url)
        if not toc_url and match:
            toc_url = f"{self.base_url}/la_{match.group(1)}/{match.group(2)}.html"
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, cover) if cover else "",
            "intro": intro,
            "lastChapter": latest,
            "tocUrl": urljoin(book_url, toc_url) if toc_url else book_url,
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
        book_url = f"{self.base_url}/txt_{kind}/{book_id}.html"
        first_html = await self._fetch(ctx, toc_url, headers={"Referer": book_url})
        page_values = [option.get("value", "") for option in ctx.select(first_html, ".pagelist option")]
        page_count = max([int(value) for value in page_values if value.isdigit()] or [1])
        for page in range(1, page_count + 1):
            html = first_html if page == 1 else await self._fetch(
                ctx,
                f"{toc_url.rstrip('/')}/{page}",
                headers={"Referer": book_url},
            )
            for anchor in ctx.select(html, f'a[href^="/txt_{kind}/{book_id}/"]'):
                href = anchor.get("href", "")
                title = ctx.clean_text(anchor.text_content())
                chapter_url = self._desktop_url(href)
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
            if len(text) < 120 and any(kw in text for kw in ["广告", "声明", "本章结束", "返回目录", "加入书签", "推荐", "最新网址", "章节内容缺失", "章节不存在", "加载更多", "无法显示本章节全部内容"]):
                div.decompose()
        for node in soup.select("#prompt"):
            node.decompose()
        for paragraph in soup.find_all("p"):
            text = paragraph.get_text(" ", strip=True)
            if len(text) < 100 and "零点小说" in text and "0xs.net" in text:
                paragraph.decompose()
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
        book_match = re.search(r"/txt_(\d+)/(\d+)/", chapter_url)
        referer = (
            f"{self.base_url}/la_{book_match.group(1)}/{book_match.group(2)}.html"
            if book_match
            else chapter_url
        )
        seen_urls = set()
        reached_last_page = False
        while current_url and len(parts) < 10:
            if current_url in seen_urls:
                break
            seen_urls.add(current_url)
            html = await self._fetch(ctx, current_url, headers={"Referer": referer})
            referer = current_url
            if not title:
                title = ctx.text(html, "h1") or ctx.text(html, ".title")
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
                reached_last_page = True
                break
            next_url = urljoin(chapter_url, next_href)
            if chapter_prefix not in next_url:
                reached_last_page = True
                break
            current_url = next_url
        title = re.sub(r"[（(][\d/]+[）)]", "", title or "").strip()
        full_content = "\n\n".join(parts)
        if reached_last_page:
            full_content = self.page_continuation_pattern.sub("", full_content)
            full_content = re.sub(r"\n{3,}", "\n\n", full_content).strip()
        return {
            "sourceId": self.id,
            "title": title,
            "content": full_content,
            "chapterUrl": chapter_url,
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }
