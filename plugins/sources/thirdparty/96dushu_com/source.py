"""96dushu (96读书) source plugin.

JS base64 anti-scrape (same qsbs.bb as ranwen8); pagination via JS var.
"""

import base64
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "96dushu_com"
    name = "96读书"
    contract_version = "1.0"
    last_modified = "2026-06-10"
    base_url = "https://www.96dushu.com"

    async def search(self, ctx, keyword: str, page: int):
        items = []
        search_error = None
        try:
            html = await ctx.access.http.fetch_text(
                f"{self.base_url}/modules/article/search.php",
                method="POST",
                data={"searchkey": keyword},
            )
            results = ctx.select(html, "#nr > dl")
            for dl in results:
                name_a = ctx.select(dl, "dd:nth-child(2) > h3 > a")
                if not name_a:
                    continue
                name = ctx.clean_text(name_a[0].text_content())
                href = name_a[0].get("href", "")
                author = ctx.clean_text(ctx.text(dl, "dd:nth-child(3) > span:nth-child(1)"))
                cat = ctx.clean_text(ctx.text(dl, "dt > span"))
                latest = ctx.clean_text(ctx.text(dl, "dd:nth-child(5) > a"))
                status = ctx.clean_text(ctx.text(dl, "dd:nth-child(3) > span:nth-child(2)"))
                update_time = ctx.clean_text(ctx.text(dl, "dd:nth-child(2) > h3 > span"))
                items.append({
                    "sourceId": self.id,
                    "name": name,
                    "author": author,
                    "bookUrl": urljoin(self.base_url, href),
                    "kind": f"{cat}/{status}",
                    "lastChapter": latest,
                    "updateTime": update_time,
                })
        except Exception as exc:
            search_error = exc
            ctx.trace("search_error", url=f"{self.base_url}/modules/article/search.php", message=str(exc))
        if not items:
            items = await self._search_from_explore(ctx, keyword)
        if items:
            return await enrich_search_items_from_detail(self, ctx, items)
        if search_error is not None:
            raise search_error
        return []

    async def _search_from_explore(self, ctx, keyword: str) -> list[dict]:
        items = []
        try:
            html = await ctx.access.http.fetch_text(f"{self.base_url}/topallvisit/1.html")
            links = ctx.select(html, "#nr > dl dd:nth-child(2) > h3 > a")
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
        except Exception as exc:
            ctx.trace("search_explore_fallback_error", url=f"{self.base_url}/topallvisit/1.html", message=str(exc))
        return items

    async def detail(self, ctx, book_url: str):
        html = await ctx.access.http.fetch_text(book_url)
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
        html = await ctx.access.http.fetch_text(toc_url)
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
            html = await ctx.access.http.fetch_text(current_url)
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
