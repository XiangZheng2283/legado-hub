"""Xhytd (黄易天地) mobile source plugin."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup


class Source:
    id = "xhytd_com"
    name = "黄易天地"
    contract_version = "1.0"
    last_modified = "2026-07-28"
    base_url = "http://wap.xhytd.com"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
        ),
    }

    async def _fetch(self, ctx, url: str, **kwargs) -> str:
        headers = {**self.headers, **kwargs.pop("headers", {})}
        return await ctx.access.http.fetch_text(url, headers=headers, **kwargs)

    async def search(self, ctx, keyword: str, page: int):
        html = await self._fetch(
            ctx,
            f"{self.base_url}/SearchBook.php",
            params={"keyword": keyword, "page": max(1, page)},
        )
        items = []
        seen_urls: set[str] = set()
        for box in ctx.select(html, ".hot_sale"):
            anchor = next(
                (
                    item for item in ctx.select(box, 'a[href]')
                    if re.fullmatch(r"/\d+/\d+/", item.get("href", ""))
                ),
                None,
            )
            if anchor is None:
                continue
            href = anchor.get("href", "")
            book_url = urljoin(self.base_url, href)
            name = ctx.text(anchor, ".title")
            if not name or book_url in seen_urls:
                continue
            seen_urls.add(book_url)
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": re.sub(r"^作者[：:]?", "", ctx.text(anchor, ".author")).strip(),
                "bookUrl": book_url,
                "coverUrl": "",
                "intro": "",
                "kind": "",
                "lastChapter": ctx.text(box, 'a[href$=".html"]'),
            })
        return items

    async def detail(self, ctx, book_url: str):
        html = await self._fetch(ctx, book_url)
        name = ctx.text(html, "header .title")
        author = re.sub(r"^作者[：:]?", "", ctx.text(html, "#book_detail .author")).strip()
        cover = ctx.attr(html, "#thumb img", "src")
        detail_lines = [ctx.clean_text(node.text_content()) for node in ctx.select(html, "#book_detail li")]
        status = next((line for line in detail_lines if line.startswith("状态")), "")
        latest = ctx.text(html, "#chapterlist a")
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, cover) if cover else "",
            "intro": "",
            "lastChapter": latest,
            "kind": status,
            "tocUrl": urljoin(book_url, "all.html"),
            "authRequired": False,
            "extra": {},
        }

    async def toc(self, ctx, toc_url: str):
        chapters = []
        seen = set()
        html = await self._fetch(ctx, toc_url)
        book_match = re.search(r"/(\d+)/(\d+)/", toc_url)
        if not book_match:
            return []
        chapter_pattern = re.compile(rf"/{book_match.group(1)}/{book_match.group(2)}/\d+\.html")
        links = ctx.select(html, "#chapterlist a[href]")
        for a in links:
            href = a.get("href", "")
            title = ctx.clean_text(a.text_content())
            if not chapter_pattern.fullmatch(href) or not title or href in seen:
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
        noise = [
            "广告", "声明", "本章结束", "返回目录", "加入书签", "推荐",
            "最新网址", "章节内容缺失", "章节不存在", "章节错误",
            "黄易天地", "xhytd",
        ]
        for tag in soup.find_all(["div", "p"]):
            if tag.get("id") == "chaptercontent":
                continue
            text = tag.get_text(strip=True)
            if len(text) < 160 and any(keyword in text for keyword in noise):
                tag.decompose()
        for br in soup.find_all("br"):
            br.replace_with("\n")
        text = soup.get_text("\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n\n".join(lines)

    async def chapter(self, ctx, chapter_url: str):
        parts = []
        current_url = chapter_url
        title = ""
        original_stem = self._chapter_stem(chapter_url)
        while current_url and len(parts) < 10:
            html = await self._fetch(ctx, current_url, headers={"Referer": chapter_url})
            if not title:
                title = ctx.text(html, "header .title") or ctx.text(html, ".title")
                title = title.split("  ", 1)[0].strip()
            content_html = ctx.html(html, "#chaptercontent")
            content = self._clean_chapter_content(content_html)
            if content:
                parts.append(content)
            next_href = next(
                (
                    anchor.get("href", "") for anchor in ctx.select(html, 'a[href]')
                    if "下一页" in ctx.clean_text(anchor.text_content())
                ),
                "",
            )
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
