"""Xhytd (黄易天地) source plugin.

Cloudflare protection, JS anti-scrape; search uses provider fallback.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "xhytd_com"
    name = "黄易天地"
    contract_version = "1.0"
    last_modified = "2026-06-10"
    base_url = "https://www.xhytd.com"

    async def search(self, ctx, keyword: str, page: int):
        if page > 1:
            return []
        hits = await ctx.access.search_provider(
            keyword,
            target_domain="www.xhytd.com",
            url_patterns=[r"/book/\d+/"],
            provider_order=["bing_html", "google_html"],
            query_site_path="/book",
            timeout=15,
            proxy=False,
        )
        items = []
        seen_urls: set[str] = set()
        for hit in hits:
            book_url = hit.url
            if not book_url or book_url in seen_urls:
                continue
            seen_urls.add(book_url)
            items.append({
                "sourceId": self.id,
                "name": re.split(r"[-_|,，:：]", hit.title or "", maxsplit=1)[0].strip() or keyword,
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
        return await enrich_search_items_from_detail(self, ctx, items)

    async def _search_from_explore(self, ctx, keyword: str) -> list[dict]:
        items = []
        try:
            html = await ctx.access.http.fetch_text(f"{self.base_url}/topallvisit/1.html")
            links = ctx.select(html, ".result_list > ul > li .s2 > a")
            seen = set()
            for a in links:
                href = a.get("href", "")
                name = ctx.clean_text(a.text_content())
                if not href or not name or name in seen:
                    continue
                if keyword.lower() in name.lower():
                    seen.add(name)
                    items.append({
                        "sourceId": self.id,
                        "name": name,
                        "bookUrl": urljoin(self.base_url, href),
                    })
        except Exception:
            pass
        return items

    async def detail(self, ctx, book_url: str):
        html = await ctx.access.http.fetch_text(book_url)
        name = ctx.text(html, ".title > h1") or ctx.text(html, "h1") or ""
        author = ctx.text(html, ".small > span:nth-child(1)")
        intro = ctx.text(html, ".intro") or ""
        cover = ctx.attr(html, ".img_in > img", "src")
        latest = ctx.text(html, ".new_tips > a")
        status = ctx.text(html, ".small > span:nth-child(3)")
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, cover) if cover else "",
            "intro": intro,
            "lastChapter": latest,
            "kind": status,
            "tocUrl": book_url,
            "authRequired": False,
            "extra": {},
        }

    async def toc(self, ctx, toc_url: str):
        chapters = []
        seen = set()
        html = await ctx.access.http.fetch_text(toc_url)
        links = ctx.select(html, "#list > dl > dd > a")
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
            if len(text) < 80 and any(kw in text for kw in ["广告", "声明", "本章结束", "返回目录", "加入书签", "推荐", "最新网址", "章节内容缺失", "章节不存在", "黄易天地", "xhytd"]):
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
            html = await ctx.access.http.fetch_text(current_url)
            if not title:
                title = ctx.text(html, ".title > h1") or ctx.text(html, "h1")
            content_html = ctx.html(html, "#content") or ctx.html(html, ".content")
            content = self._clean_chapter_content(content_html)
            if content:
                parts.append(content)
            next_href = ctx.attr(html, ".bottem2 > a:nth-child(3)", "href")
            if not next_href or next_href == "javascript:void(0);":
                break
            if self._chapter_stem(next_href) != original_stem:
                break
            current_url = urljoin(chapter_url, next_href)
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
