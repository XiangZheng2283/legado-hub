"""Plugin for 天天看小说 (ttkan.co)."""

import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "ttkan_co"
    name = "天天看书网"
    contract_version = "1.0"
    last_modified = "2026-06-10"
    base_url = "https://www.ttkan.co"

    def _s(self, ctx, value: str) -> str:
        """Convert Traditional Chinese output text to Simplified Chinese."""
        return ctx.to_simplified(value)

    async def _search_from_explore(self, ctx, keyword: str):
        matched = []
        for group in getattr(self, "explore_defs", [])[:4]:
            try:
                items = await self.explore(ctx, group["groupId"], 1)
            except Exception:
                continue
            matched.extend(item for item in items if keyword and keyword in item.get("name", ""))
            if matched:
                break
        return matched

    async def search(self, ctx, keyword: str, page: int):
        search_keyword = ctx.to_traditional(keyword)
        try:
            html = await ctx.access.http.fetch_text(
                f"{self.base_url}/novel/search",
                params={"q": search_keyword},
            )
        except Exception:
            html = await ctx.access.http.fetch_text(
                f"{self.base_url}/search",
                params={"q": search_keyword},
            )
        rows = ctx.select(html, ".novel_cell") or ctx.select(html, ".search_result li") or ctx.select(html, ".novel_list li")
        items = []
        for row in rows:
            link_node = ctx.select(row, "li a h3") or ctx.select(row, "a h3")
            if link_node:
                anchor = link_node[0].getparent()
            else:
                anchor_nodes = ctx.select(row, "li a") or ctx.select(row, "a")
                anchor = anchor_nodes[0] if anchor_nodes else None
            if anchor is None:
                continue
            name = ctx.clean_text(anchor.text_content())
            href = anchor.get("href", "")
            author_text = ctx.text(row, "li:nth-of-type(2)")
            author = re.sub(r"^作者：", "", author_text).strip() if author_text else ""
            intro = ctx.text(row, "li:nth-of-type(3)")
            cover = ctx.attr(row, "amp-img", "src")
            items.append({
                "sourceId": self.id,
                "name": self._s(ctx, name),
                "author": self._s(ctx, author),
                "bookUrl": urljoin(self.base_url, href),
                "coverUrl": urljoin(self.base_url, cover) if cover else "",
                "intro": self._s(ctx, intro),
                "kind": "",
                "lastChapter": "",
            })
        matched = [item for item in items if keyword in item.get("name", "")]
        if not matched and search_keyword != keyword:
            matched = [item for item in items if search_keyword in ctx.to_traditional(item.get("name", ""))]
        if not matched:
            keyword_s = self._s(ctx, keyword)
            matched = [item for item in items if keyword_s and keyword_s in item.get("name", "")]
        if matched:
            return await enrich_search_items_from_detail(self, ctx, matched)
        items = await self._search_from_explore(ctx, keyword)
        return await enrich_search_items_from_detail(self, ctx, items)

    def _meta(self, ctx, html: str, key: str) -> str:
        return (
            ctx.attr(html, f'meta[name="{key}"]', "content")
            or ctx.attr(html, f'meta[property="{key}"]', "content")
            or ""
        )

    async def detail(self, ctx, book_url: str):
        html = await ctx.access.http.fetch_text(book_url)
        name = self._meta(ctx, html, "og:novel:book_name")

        # 若详情页返回资料载入失败，尝试从第一章页获取 meta
        if not name or "資料載入失敗" in html or "小說資訊暫時載入失敗" in html:
            m = re.search(r"/novel/chapters/([^/?#]+)", book_url)
            if m:
                novel_id = m.group(1)
                try:
                    first_html = await ctx.access.http.fetch_text(
                        f"{self.base_url}/novel/pagea/{novel_id}_1.html"
                    )
                    name = self._meta(ctx, first_html, "og:novel:book_name")
                    if not html or "資料載入失敗" in html:
                        html = first_html
                except Exception:
                    pass

        author = self._meta(ctx, html, "og:novel:author")
        cover = self._meta(ctx, html, "og:image")
        kind = self._meta(ctx, html, "og:novel:category")
        status = self._meta(ctx, html, "og:novel:status")
        last = self._meta(ctx, html, "og:novel:latest_chapter_name")
        intro = self._meta(ctx, html, "og:description")

        # 从 DOM 补充缺失字段
        if not author:
            author_text = ctx.text(html, ".novel_info li:nth-of-type(2)")
            author = re.sub(r"^作者：", "", author_text).strip()
        if not kind:
            kind_text = ctx.text(html, ".novel_info li:nth-of-type(3)")
            kind = re.sub(r"^類別：", "", kind_text).strip()
        if not status:
            status_text = ctx.text(html, ".novel_info li:nth-of-type(4)")
            status = re.sub(r"^狀態：", "", status_text).strip()
        if not cover:
            cover = ctx.attr(html, ".novel_info amp-img", "src")

        # 兜底封面
        if not cover:
            m = re.search(r"/novel/chapters/([^/?#]+)", book_url)
            if m:
                cover = f"https://static.ttkan.co/cover/{m.group(1)}.jpg"

        # 清理简介中的站点前缀
        intro = re.sub(r"^天天看小說：\s*", "", intro).strip()
        intro = re.sub(r"\n{3,}", "\n\n", intro).strip()

        return {
            "sourceId": self.id,
            "name": self._s(ctx, name) or self._s(ctx, "資料載入失敗"),
            "author": self._s(ctx, author),
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, cover) if cover else "",
            "intro": self._s(ctx, intro),
            "kind": self._s(ctx, " / ".join([p for p in [kind, status] if p])),
            "lastChapter": self._s(ctx, last),
            "wordCount": "",
            "updateTime": "",
            "tocUrl": book_url,
            "authRequired": False,
            "extra": {
                "status": status,
            },
        }

    async def toc(self, ctx, toc_url: str):
        m = re.search(r"/novel/chapters/([^/?#]+)", toc_url)
        novel_id = m.group(1) if m else ""

        # 优先使用 API 获取完整章节列表
        if novel_id:
            try:
                api_url = f"{self.base_url}/api/nq/amp_novel_chapters?language=tw&novel_id={novel_id}"
                api_data = await ctx.access.http.fetch_json(api_url)
                items = api_data.get("items", [])
                chapters = []
                for item in items:
                    chapter_id = item.get("chapter_id")
                    chapter_name = item.get("chapter_name", "")
                    if chapter_id and chapter_name:
                        chapters.append({
                            "sourceId": self.id,
                            "index": len(chapters) + 1,
                            "title": self._s(ctx, chapter_name),
                            "chapterUrl": f"{self.base_url}/novel/pagea/{novel_id}_{chapter_id}.html",
                            "isVip": False,
                            "isLocked": False,
                        })
                if chapters:
                    return chapters
            except Exception:
                pass

        # API 失败时回退到 HTML 解析
        html = await ctx.access.http.fetch_text(toc_url)
        links = ctx.select(html, ".full_chapters a")
        chapters = []
        for a in links:
            href = a.get("href", "")
            title = ctx.clean_text(a.text_content())
            if not href or not title:
                continue
            chapters.append({
                "sourceId": self.id,
                "index": len(chapters) + 1,
                "title": self._s(ctx, title),
                "chapterUrl": urljoin(toc_url, href),
                "isVip": False,
                "isLocked": False,
            })
        return chapters

    async def chapter(self, ctx, chapter_url: str):
        html = await ctx.access.http.fetch_text(chapter_url)
        title = ctx.text(html, "h1")
        content = ctx.html(html, ".content")
        content = self._clean_chapter_content(content)
        # 清洗站点广告与导航
        content = re.sub(r'<center>\s*<div class="mobadsq"></div>\s*</center>', "", content)
        content = re.sub(r'<div class="mobadsq"></div>', "", content)
        content = re.sub(r'<div id="div_content_end"></div>.*$', "", content, flags=re.DOTALL)
        content = re.sub(r'\n{3,}', "\n\n", content).strip()
        return {
            "sourceId": self.id,
            "title": self._s(ctx, title),
            "content": self._s(ctx, content),
            "chapterUrl": chapter_url,
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _clean_chapter_content(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "iframe", "ins", "center"]):
            tag.decompose()
        for div in soup.find_all("div"):
            text = div.get_text(strip=True)
            if len(text) < 80 and any(kw in text for kw in ["廣告", "广告", "本章完", "天天看小說", "天天看书", "返回目錄", "返回目录"]):
                div.decompose()
        for tag in soup.find_all("br"):
            tag.replace_with("\n")
        paragraphs = []
        for p in soup.find_all("p"):
            text = p.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)
        if paragraphs:
            return "\n\n".join(paragraphs)
        text = soup.get_text("\n", strip=True)
        lines = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            if any(kw in line for kw in ["天天看小說", "天天看书", "返回目錄", "返回目录", "本章完", "廣告", "广告"]):
                continue
            lines.append(line)
        return "\n\n".join(lines)
