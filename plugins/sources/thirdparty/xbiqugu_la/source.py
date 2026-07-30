"""Plugin for 香书小说 (xbiqugu.la) based on so-novel seed."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "xbiqugu_la"
    name = "香书小说"
    contract_version = "1.0"
    last_modified = "2026-06-10"
    base_url = "https://www.xbiqugu.com"

    @classmethod
    def get_ad_patterns(cls) -> list[str]:
        """香书小说常见广告水印模式（占位，待采集脚本收敛）。"""
        return [
            r"最新章节地址",
            r"请收藏.*xbiqugu",
            r"手机用户请浏览",
        ]

    explore_defs = [
        {"groupId": "xuanhuan", "title": "玄幻", "url": "/fenlei/1_{page}.html", "kind": "category"},
        {"groupId": "xiuzhen", "title": "修真", "url": "/fenlei/2_{page}.html", "kind": "category"},
        {"groupId": "dushi", "title": "都市", "url": "/fenlei/3_{page}.html", "kind": "category"},
        {"groupId": "chuanyue", "title": "穿越", "url": "/fenlei/4_{page}.html", "kind": "category"},
        {"groupId": "wangyou", "title": "网游", "url": "/fenlei/5_{page}.html", "kind": "category"},
    ]

    async def explore_groups(self, ctx):
        return [
            {
                "sourceId": self.id,
                "groupId": item["groupId"],
                "title": item["title"],
                "url": urljoin(self.base_url, item["url"].replace("{page}", "1")),
                "kind": item["kind"],
                "pageable": True,
                "profile": "current",
            }
            for item in self.explore_defs
        ]

    async def explore(self, ctx, group_id: str | None = None, page: int = 1):
        group = next((item for item in self.explore_defs if item["groupId"] == group_id), self.explore_defs[0])
        url = urljoin(self.base_url, group["url"].replace("{page}", str(page)))
        html = await ctx.access.http.fetch_text(url)
        rows = ctx.select(html, ".item")
        items = []
        for index, row in enumerate(rows, start=1):
            links = ctx.select(row, 'a[href*="/wapbook/"]')
            if not links:
                continue
            href = links[0].get("href", "")
            named_links = [a for a in links if ctx.clean_text(a.text_content())]
            name = ctx.clean_text(named_links[0].text_content()) if named_links else ""
            text = ctx.clean_text(row.text_content())
            author = text.split(name, 1)[0].strip() if name and name in text else ""
            intro = text.split(name, 1)[-1].strip() if name and name in text else text
            if not name:
                continue
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": author,
                "bookUrl": urljoin(self.base_url, href),
                "intro": intro,
                "kind": group["title"],
                "groupId": group["groupId"],
                "groupTitle": group["title"],
                "rank": index,
            })
        return items

    async def search(self, ctx, keyword: str, page: int):
        try:
            base_for_join = self.base_url
            html = await ctx.access.http.fetch_text(
                f"{self.base_url}/so/",
                method="POST",
                data={"searchkey": keyword, "Submit": "搜索"},
            )
            rows = ctx.select(html, ".txt-list-row5 > li")
        except Exception:
            base_for_join = "http://www.xbiqugu.la"
            legacy_url = "http://www.xbiqugu.la/modules/article/waps.php"
            html = await ctx.access.http.fetch_text(legacy_url, method="POST", data={"searchkey": keyword})
            rows = ctx.select(html, "#checkform > table > tbody > tr")
        items = []
        for row in rows:
            name_node = ctx.select(row, "span.s2 > a")
            if not name_node:
                name_node = ctx.select(row, "td.even > a")
            name = name_node[0].text_content().strip() if name_node else ""
            href = name_node[0].get("href", "") if name_node else ""
            author = ctx.text(row, "span.s4") or ctx.text(row, "td:nth-of-type(3)")
            latest = ctx.text(row, "span.s3 > a") or ctx.text(row, "td.odd > a")
            book_url = urljoin(base_for_join, href)
            if not name:
                continue
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": author,
                "bookUrl": book_url,
                "lastChapter": latest,
            })
        matched = [item for item in items if keyword in item.get("name", "")]
        if matched:
            return await enrich_search_items_from_detail(self, ctx, matched)
        if items:
            return await enrich_search_items_from_detail(self, ctx, items)
        items = await self._search_from_explore(ctx, keyword)
        return await enrich_search_items_from_detail(self, ctx, items)

    async def _search_from_explore(self, ctx, keyword: str):
        matched = []
        for group in self.explore_defs[:4]:
            try:
                items = await self.explore(ctx, group["groupId"], 1)
            except Exception:
                continue
            matched.extend(item for item in items if keyword and keyword in item.get("name", ""))
            if matched:
                break
        return matched

    async def detail(self, ctx, book_url: str):
        html = await ctx.access.http.fetch_text(book_url)
        name = ctx.attr(html, 'meta[property="og:novel:book_name"]', "content") or ctx.text(html, "#info > h1")
        author = ctx.attr(html, 'meta[property="og:novel:author"]', "content") or ctx.text(html, "#info > p:nth-child(2)").replace("作者：", "").strip()
        intro = ctx.attr(html, 'meta[property="og:description"]', "content") or ctx.text(html, "#intro")
        cover = ctx.attr(html, 'meta[property="og:image"]', "content") or ctx.attr(html, "#fmimg > img", "src")
        kind = ctx.attr(html, 'meta[property="og:novel:category"]', "content") or ""
        status = ctx.attr(html, 'meta[property="og:novel:status"]', "content") or ""
        last = ctx.attr(html, 'meta[property="og:novel:lastest_chapter_name"]', "content") or ctx.text(html, "#info > p:nth-child(4) > a")
        update_time = ctx.attr(html, 'meta[property="og:novel:update_time"]', "content") or ""
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": urljoin(book_url, cover) if cover else "",
            "intro": intro,
            "kind": " / ".join([p for p in [kind, status] if p]),
            "lastChapter": last,
            "wordCount": "",
            "updateTime": update_time,
            "tocUrl": book_url,
            "authRequired": False,
        }

    _CN_NUMS = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
        "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
    }

    def _extract_chapter_num(self, title: str, href: str) -> int:
        import re
        m = re.search(r"第(\d+)章", title)
        if m:
            return int(m.group(1))
        m = re.search(r"第([一二三四五六七八九十]+)章", title)
        if m:
            return self._CN_NUMS.get(m.group(1), 0)
        url_m = re.search(r"/\d+/(\d+)\.html", href)
        if url_m:
            return int(url_m.group(1))
        return 0

    async def toc(self, ctx, toc_url: str):
        chapters = []
        seen: set[str] = set()
        seen_pages: set[str] = set()
        page_url = toc_url
        while page_url and page_url not in seen_pages:
            seen_pages.add(page_url)
            try:
                html = await ctx.access.http.fetch_text(page_url)
            except Exception:
                break
            links = self._toc_links_from_full_section(ctx, html)
            if not links:
                break
            new_count = 0
            for a in links:
                href = a.get("href", "")
                title = ctx.clean_text(a.get_text(" ", strip=True) if hasattr(a, "get_text") else a.text_content())
                chapter_url = urljoin(page_url, href)
                if not href or not title or not href.endswith(".html"):
                    continue
                if chapter_url in seen:
                    continue
                seen.add(chapter_url)
                chapters.append({
                    "sourceId": self.id,
                    "title": title,
                    "chapterUrl": chapter_url,
                    "isVip": False,
                    "isLocked": False,
                })
                new_count += 1
            next_href = self._next_toc_page_href(ctx, html)
            if not next_href or new_count == 0:
                break
            next_url = urljoin(page_url, next_href)
            if next_url == page_url:
                break
            page_url = next_url
        for index, c in enumerate(chapters, start=1):
            c["index"] = index
        return chapters

    def _toc_links_from_full_section(self, ctx, html: str):
        soup = BeautifulSoup(html or "", "html.parser")
        for h2 in soup.find_all("h2"):
            if "正文" not in h2.get_text(" ", strip=True):
                continue
            section = h2.find_next_sibling("div", class_="section-box")
            if section:
                return section.select('a[href*="/wapbook/"][href$=".html"]')
        legacy_links = soup.select("#list dd a[href$='.html']")
        if legacy_links:
            return legacy_links
        return soup.select('a[href*="/wapbook/"][href$=".html"]')

    def _next_toc_page_href(self, ctx, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for a in soup.find_all("a"):
            text = ctx.clean_text(a.get_text(" ", strip=True))
            href = a.get("href", "")
            if text == "下一页" and href:
                return href
        return ""

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
            if len(text) < 80 and any(kw in text for kw in ["广告", "声明", "本章结束", "返回目录", "加入书签", "推荐", "最新网址", "章节内容缺失", "章节不存在", "香书小说", "xbiqugu"]):
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
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n\n".join(lines)

    async def chapter(self, ctx, chapter_url: str):
        parts: list[str] = []
        current_url = chapter_url
        title = ""
        original_stem = self._chapter_stem(chapter_url)
        while current_url and len(parts) < 10:
            html = await ctx.access.http.fetch_text(current_url)
            if not title:
                title = ctx.text(html, ".title") or ctx.text(html, ".bookname > h1") or ctx.text(html, "h1")
            content_html = ctx.html(html, "#content") or ctx.html(html, "#txt") or ctx.html(html, ".content")
            content = self._clean_chapter_content(content_html)
            if content:
                parts.append(content)
            next_href = ctx.attr(html, "#next_url", "href") or ctx.attr(html, "a:contains('下一章')", "href")
            if not next_href or next_href == "javascript:void(0);":
                break
            next_url = urljoin(current_url, next_href)
            if self._chapter_stem(next_url) != original_stem:
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
