"""96dushu (96读书) source plugin.

JS base64 anti-scrape (same qsbs.bb as ranwen8); pagination via JS var.
"""

import base64
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from app.source_plugins.challenges import looks_like_browser_challenge, looks_like_cloudflare_challenge
from app.source_plugins.errors import BrowserRequired


class Source:
    id = "96dushu_com"
    name = "96读书"
    contract_version = "1.0"
    last_modified = "2026-07-31"
    base_url = "https://www.96dushu.com"
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.96dushu.com/",
        "Upgrade-Insecure-Requests": "1",
    }

    async def _fetch(self, ctx, url: str) -> str:
        try:
            return await ctx.access.stealth.fetch_text(url, headers=self.headers)
        except BrowserRequired as original_error:
            html = await ctx.access.browser.fetch_text(
                url,
                headers=self.headers,
                stage="page_fallback",
                wait_ms=5000,
                timeout_ms=45000,
            )
            if looks_like_cloudflare_challenge(html) or looks_like_browser_challenge(html):
                raise original_error
            return html

    async def search(self, ctx, keyword: str, page: int):
        if page > 1:
            return []
        hits = await ctx.access.search_provider(
            keyword,
            target_domain="www.96dushu.com",
            url_patterns=[r"/book/\d+/"],
            provider_order=["duckduckgo_ddgs", "bing_html", "google_html"],
            query_site_path="/book",
            timeout=15,
        )
        items = []
        seen_urls: set[str] = set()
        for hit in hits:
            book_url = hit.url
            if not book_url or book_url in seen_urls:
                continue
            seen_urls.add(book_url)
            hit_title = ctx.clean_text(hit.title or "")
            items.append({
                "sourceId": self.id,
                "name": keyword if keyword and keyword in hit_title else re.split(r"[-_|,，:：]", hit_title, maxsplit=1)[0].strip() or keyword,
                "author": "",
                "bookUrl": book_url,
                "coverUrl": "",
                "intro": (hit.snippet or "").strip(),
                "kind": "",
                "lastChapter": "",
                "extra": {
                    "searchProvider": "source_access_bridge",
                    "provider": hit.provider,
                    "matchedPattern": hit.matched_pattern,
                    "searchUrl": hit.url,
                },
            })
        return items

    async def detail(self, ctx, book_url: str):
        html = await self._fetch(ctx, book_url)
        name = ctx.text(html, ".novel_info_main > div > h1") or ctx.text(html, "h1") or ""
        author = ctx.text(html, ".novel_info_main > div > p:nth-child(2) > a")
        intro = ctx.text(html, ".intro") or ""
        cover = ctx.attr(html, ".novel_info_main > img", "src")
        latest = ctx.text(html, ".new_tips > a")
        status = ctx.text(html, ".novel_info_main > div > p:nth-child(2) > span:nth-child(3)")
        cat = ctx.text(html, ".novel_info_main > div > p:nth-child(2) > span:nth-child(1)")
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, cover) if cover else "",
            "intro": intro,
            "lastChapter": latest,
            "kind": f"{cat}/{status}" if cat or status else "",
            "tocUrl": book_url,
            "authRequired": False,
            "extra": {},
        }

    async def toc(self, ctx, toc_url: str):
        chapters = []
        seen = set()
        html = await self._fetch(ctx, toc_url)
        links = ctx.select(html, "#chapterList > li > a")
        for a in links:
            href = a.get("href", "")
            title = ctx.clean_text(a.text_content())
            if not href or not title or href in seen:
                continue
            seen.add(href)
            chapters.append({
                "sourceId": self.id,
                "index": len(chapters) + 1,
                "title": title,
                "chapterUrl": urljoin(toc_url, href),
                "isVip": False,
                "isLocked": False,
            })
        return chapters

    def _decode_base64_content(self, html: str) -> str:
        pattern = re.compile(r'<script>\s*document\.writeln\(qsbs\.bb\(\'([^\']+)\'\)\);\s*</script>', re.I)

        def _decode(match: re.Match) -> str:
            try:
                cleaned = re.sub(r"[^A-Za-z0-9+/=]", "", match.group(1))
                return base64.b64decode(cleaned).decode("utf-8", errors="replace")
            except Exception:
                return ""

        return pattern.sub(_decode, html)

    def _extract_nextpage_from_scripts(self, html: str) -> str | None:
        pattern = re.compile(r'nextpage\s*=\s*"([^"]+)"')
        for m in pattern.finditer(html):
            url = m.group(1)
            if url and url != "javascript:void(0);":
                return url
        return None

    def _chapter_stem(self, url: str) -> str:
        path = url.split("?")[0].split("#")[0]
        if "_" in path:
            return path.rsplit("_", 1)[0]
        return path.rsplit(".", 1)[0] if "." in path else path

    def _clean_chapter_content(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "iframe", "ins", "center"]):
            tag.decompose()
        for div in soup.find_all("div"):
            text = div.get_text(strip=True)
            if len(text) < 80 and any(kw in text for kw in ["广告", "声明", "本章结束", "返回目录", "加入书签", "推荐", "最新网址", "章节内容缺失", "章节不存在", "96读书", "96dushu"]):
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
        original_stem = self._chapter_stem(chapter_url)
        while current_url and len(parts) < 10:
            html = await self._fetch(ctx, current_url)
            if not title:
                title = ctx.text(html, "#mlfy_main_text > h1") or ctx.text(html, "h1")
            content_html = ctx.html(html, "#content") or ctx.html(html, ".content")
            decoded = self._decode_base64_content(content_html)
            content = self._clean_chapter_content(decoded)
            if content:
                parts.append(content)
            next_href = ctx.attr(html, "#readbg > div.mlfy_page > a:nth-child(4)", "href")
            if not next_href or next_href == "javascript:void(0);":
                next_href = self._extract_nextpage_from_scripts(html)
            if not next_href or next_href == "javascript:void(0);":
                break
            if self._chapter_stem(next_href) != original_stem:
                break
            current_url = urljoin(chapter_url, next_href)
        title = re.sub(r"[（(][\d/]+[）)]", "", title or "").strip()
        full_content = "\n\n".join(parts)
        # Apply text filters from so-novel rule
        full_content = re.sub(r"\(继续下一页|本章完\)", "", full_content)
        full_content = re.sub(r"最⊥新⊥小⊥说⊥在⊥六⊥9⊥⊥书⊥⊥吧⊥⊥首⊥发！", "", full_content)
        return {
            "sourceId": self.id,
            "title": title,
            "content": full_content,
            "chapterUrl": chapter_url,
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }
