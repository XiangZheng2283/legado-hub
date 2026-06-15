"""Plugin for 笔趣阁365 (biquge365.net) based on so-novel seed."""

from urllib.parse import urljoin
import re

from bs4 import BeautifulSoup

from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "biquge365_net"
    name = "笔趣阁365"
    contract_version = "1.0"
    last_modified = "2026-06-10"
    base_url = "https://m.biquge365.net"
    headers = {}
    explore_defs = [
        {"groupId": "top_xuanhuan", "title": "玄幻魔法排行", "url": "/top/1_{page}/", "kind": "rank"},
        {"groupId": "top_xianxia", "title": "仙侠修真排行", "url": "/top/2_{page}/", "kind": "rank"},
        {"groupId": "top_dushi", "title": "都市言情排行", "url": "/top/3_{page}/", "kind": "rank"},
        {"groupId": "sort_xuanhuan", "title": "玄幻魔法分类", "url": "/sort/1_{page}/", "kind": "category"},
        {"groupId": "full_xuanhuan", "title": "玄幻魔法全本", "url": "/full/1/", "kind": "full"},
    ]

    async def explore_groups(self, ctx):
        return [
            {
                "sourceId": self.id,
                "groupId": item["groupId"],
                "title": item["title"],
                "url": urljoin(self.base_url, item["url"].replace("{page}", "1")),
                "kind": item["kind"],
                "pageable": "{page}" in item["url"],
                "profile": "mobile",
            }
            for item in self.explore_defs
        ]

    async def explore(self, ctx, group_id: str | None = None, page: int = 1):
        group = next((item for item in self.explore_defs if item["groupId"] == group_id), self.explore_defs[0])
        url = urljoin(self.base_url, group["url"].replace("{page}", str(page)))
        html = await ctx.access.http.fetch_text(url, headers=self.headers)
        rows = ctx.select(html, ".liebiao2 li")
        items = []
        for index, row in enumerate(rows, start=1):
            link = ctx.select(row, ".ming a") or ctx.select(row, "a")
            if not link:
                continue
            name = ctx.clean_text(link[0].text_content())
            href = link[0].get("href", "")
            author = ctx.text(row, ".zuo")
            if not name:
                continue
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": author,
                "bookUrl": urljoin(self.base_url, href),
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
                f"{self.base_url}/waps.php",
                method="POST",
                data={"s": keyword, "submit": ""},
                headers=self.headers,
            )
            rows = ctx.select(html, ".liebiao2 li") or ctx.select(html, "ul li")
        except Exception:
            base_for_join = "https://www.biquge365.net"
            legacy_url = "https://www.biquge365.net/s.php"
            html = await ctx.access.http.fetch_text(legacy_url, method="POST", data={"type": "articlename", "s": keyword})
            rows = ctx.select(html, "body > div.menu > div > ul > li") or ctx.select(html, "ul li")
        items = []
        for row in rows:
            name_node = ctx.select(row, "span.name > a") or ctx.select(row, "a")
            name = name_node[0].text_content().strip() if name_node else ""
            href = name_node[0].get("href", "") if name_node else ""
            text = row.text_content()
            author = ctx.text(row, "span.zuo > a") or ctx.text(row, ".zuo") or (text.split(name, 1)[-1].strip() if name else "")
            latest = ctx.text(row, "span.jie > a") or ctx.text(row, ".jie")
            book_url = urljoin(base_for_join, href)
            if not name:
                continue
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": author,
                "bookUrl": book_url,
                "coverUrl": "",
                "intro": "",
                "kind": "",
                "lastChapter": latest,
                "wordCount": "",
                "updateTime": "",
            })
        if not items:
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
        html = await ctx.access.http.fetch_text(book_url, headers=self.headers)

        # OG meta tags (present on both mobile and desktop)
        name = ctx.attr(html, 'meta[property="og:novel:book_name"]', "content")
        author = ctx.attr(html, 'meta[property="og:novel:author"]', "content")
        kind = ctx.attr(html, 'meta[property="og:novel:category"]', "content")
        status = ctx.attr(html, 'meta[property="og:novel:status"]', "content")
        last = ctx.attr(html, 'meta[property="og:novel:latest_chapter_name"]', "content")
        intro = ctx.attr(html, 'meta[property="og:description"]', "content")
        cover = ctx.attr(html, 'meta[property="og:image"]', "content")

        # Desktop fallback (#info structure)
        if not name:
            name = ctx.text(html, "#info > h1")
        if not author:
            author = ctx.text(html, "#info > p:nth-child(2)").replace("作者：", "").strip()
        if not kind:
            kind = ctx.text(html, "#info > p:nth-child(3)").replace("类别：", "").strip()
        if not intro:
            intro = ctx.text(html, "#intro")
        if not cover:
            cover = ctx.attr(html, "#fmimg > img", "src")

        # Mobile fallback (.p2 structure)
        if not name:
            name = ctx.text(html, ".p2 h1")
        if not author:
            for li in ctx.select(html, ".p2 ul li"):
                text = ctx.clean_text(li.text_content())
                if text.startswith("作者："):
                    author = text.replace("作者：", "").strip()
                    break
        if not kind:
            for li in ctx.select(html, ".p2 ul li"):
                text = ctx.clean_text(li.text_content())
                if text.startswith("类型："):
                    kind = text.replace("类型：", "").strip()
                    break
        if not status:
            for li in ctx.select(html, ".p2 ul li"):
                text = ctx.clean_text(li.text_content())
                if text.startswith("状态："):
                    status = text.replace("状态：", "").strip()
                    break
        update_time = ""
        for li in ctx.select(html, ".p2 ul li"):
            text = ctx.clean_text(li.text_content())
            if text.startswith("更新："):
                update_time = text.replace("更新：", "").strip()
                break
        if not cover:
            cover = ctx.attr(html, ".p1 img", "src")
        if not intro:
            intro = ctx.text(html, ".jianjie p")

        # Generic fallback for lastChapter
        if not last:
            latest_links = ctx.select(html, "ul:nth-of-type(2) a")
            last = latest_links[0].text_content().strip() if latest_links else ""

        toc_url = book_url if "www.biquge365.net" in book_url else book_url.rstrip("/") + "_1/"
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": book_url,
            "coverUrl": urljoin(self.base_url, cover) if cover else "",
            "intro": intro,
            "kind": " / ".join([p for p in [kind, status] if p]),
            "lastChapter": last,
            "wordCount": "",
            "updateTime": update_time,
            "tocUrl": toc_url,
            "authRequired": False,
        }

    async def toc(self, ctx, toc_url: str):
        chapters = []
        seen: set[str] = set()
        page_url = toc_url
        for _ in range(120):
            html = await ctx.access.http.fetch_text(page_url, headers=self.headers)
            links = self._catalog_links(ctx, html)
            if not links:
                break
            new_count = 0
            for a in links:
                href = a.get("href", "")
                title = a.text_content().strip()
                chapter_url = urljoin(page_url, href)
                if not self._is_catalog_chapter_link(href, title, chapter_url) or chapter_url in seen:
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
                new_count += 1
            next_href = self._next_page_href(ctx, html)
            if not next_href or new_count == 0:
                break
            next_url = urljoin(page_url, next_href)
            if next_url == page_url:
                break
            page_url = next_url
        return chapters

    def _catalog_links(self, ctx, html: str):
        candidates = []
        for ul in ctx.select(html, "ul"):
            links = [a for a in ctx.select(ul, 'a[href*="/chapter/"]') if a.text_content().strip()]
            if links:
                candidates.append(links)
        if candidates:
            return candidates[-1]
        return ctx.select(html, "body > div.menu > div.border > ul > li > a")

    def _is_catalog_chapter_link(self, href: str, title: str, chapter_url: str) -> bool:
        if not href or not title:
            return False
        if href.startswith("javascript:") or not chapter_url.endswith(".html"):
            return False
        return "/chapter/" in chapter_url or "/book/" in chapter_url

    def _next_page_href(self, ctx, html: str) -> str:
        for a in ctx.select(html, "a"):
            text = ctx.clean_text(a.text_content())
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
        for p in soup.find_all("p"):
            text = p.get_text(" ", strip=True)
            if any(kw in text for kw in ["一秒记住", "biquge365.net", "更新快，无弹窗", "最快更新"]):
                p.decompose()
        for div in soup.find_all("div"):
            text = div.get_text(strip=True)
            if len(text) < 80 and any(kw in text for kw in ["广告", "声明", "本章结束", "返回目录", "加入书签", "推荐", "最新网址", "章节内容缺失", "章节不存在", "biquge365.net"]):
                div.decompose()
        for tag in soup.find_all("br"):
            tag.replace_with("\n")
        text = soup.get_text("\n", strip=True)
        lines = []
        for line in text.splitlines():
            line = re.sub(r"^\s*(?:&nbsp;|\u00a0|\s)+", "", line).strip()
            if not line:
                continue
            if any(kw in line for kw in ["一秒记住", "biquge365.net", "更新快，无弹窗", "最快更新", "下载APP，无广告"]):
                continue
            lines.append(line)
        return "\n\n".join(lines)

    async def chapter(self, ctx, chapter_url: str):
        parts: list[str] = []
        current_url = chapter_url
        title = ""
        original_stem = self._chapter_stem(chapter_url)
        while current_url and len(parts) < 10:
            html = await ctx.access.http.fetch_text(current_url, headers=self.headers)
            if not title:
                title = ctx.text(html, "#neirong > h1") or ctx.text(html, "h1") or ctx.text(html, ".bookname > h1")
            content_html = ctx.html(html, "#txt") or ctx.html(html, "#content") or ctx.html(html, ".content")
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
