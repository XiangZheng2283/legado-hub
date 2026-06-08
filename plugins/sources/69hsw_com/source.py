"""Plugin for 69书屋 (69hsw.com)."""

import re
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from app.source_plugins.errors import BrowserRequired


class Source:
    id = "69hsw_com"
    name = "69书屋"
    contract_version = "1.0"
    base_url = "https://www.69hsw.com"
    headers = {"accept-language": "zh-CN,zh;q=0.9"}
    explore_defs = [
        {"groupId": "home_hot", "title": "热门推荐", "url": "/", "kind": "rank"},
        {"groupId": "class_xuanhuan", "title": "玄幻", "url": "/class/1_{page}.html", "kind": "category"},
        {"groupId": "class_wuxia", "title": "武侠", "url": "/class/2_{page}.html", "kind": "category"},
        {"groupId": "class_dushi", "title": "都市", "url": "/class/3_{page}.html", "kind": "category"},
        {"groupId": "rank_allvisit", "title": "热门榜", "url": "/rank/allvisit/", "kind": "rank"},
    ]

    async def _fetch(self, ctx, url: str, **kwargs):
        return await ctx.fetch_text(
            urljoin(self.base_url, url),
            headers={**self.headers, **kwargs.pop("headers", {})},
            **kwargs,
        )

    async def explore_groups(self, ctx):
        return [
            {
                "sourceId": self.id,
                "groupId": item["groupId"],
                "title": item["title"],
                "url": urljoin(self.base_url, item["url"].replace("{page}", "1")),
                "kind": item["kind"],
                "pageable": "{page}" in item["url"],
                "profile": "primary",
            }
            for item in self.explore_defs
        ]

    async def explore(self, ctx, group_id: str | None = None, page: int = 1):
        group = next((item for item in self.explore_defs if item["groupId"] == group_id), self.explore_defs[0])
        url = group["url"].replace("{page}", str(page))
        html = await self._fetch(ctx, url)
        if group["groupId"] == "home_hot":
            return self._parse_home_hot(ctx, html, group["groupId"], group["title"])
        return self._parse_book_cards(ctx, html, group["groupId"], group["title"])

    async def search(self, ctx, keyword: str, page: int):
        url = f"/ss/?searchkey={quote_plus(keyword)}"
        try:
            html = await self._fetch(ctx, url)
            if self._is_search_captcha(html):
                fallback = await self._search_from_explore(ctx, keyword)
                if fallback:
                    return fallback
                raise BrowserRequired("69hsw search requires numeric captcha verification", url=urljoin(self.base_url, url))
            items = self._parse_book_cards(ctx, html, "search", "搜索")
            if not items:
                items = self._parse_news_rows(ctx, html, "search", "搜索")
            exact = [item for item in items if keyword and keyword in item.get("name", "")]
            return exact or items
        except BrowserRequired:
            raise
        except Exception as exc:
            ctx.trace("search_fallback", url=urljoin(self.base_url, url), message=str(exc))
            return await self._search_from_explore(ctx, keyword)

    async def _search_from_explore(self, ctx, keyword: str):
        matched = []
        for group in self.explore_defs[:4]:
            try:
                items = await self.explore(ctx, group["groupId"], 1)
            except Exception as exc:
                ctx.trace("search_explore_fallback_error", url=group["url"], message=str(exc))
                continue
            matched.extend(item for item in items if keyword and keyword in item.get("name", ""))
            if matched:
                break
        return matched

    def _parse_home_hot(self, ctx, html: str, group_id: str, group_title: str):
        hot = ctx.select(html, "#hotcontent .l")
        root = hot[0] if hot else html
        return self._parse_book_cards(ctx, root, group_id, group_title)

    def _parse_book_cards(self, ctx, html_or_node, group_id: str, group_title: str):
        items = []
        for index, row in enumerate(ctx.select(html_or_node, ".item"), start=1):
            title_node = ctx.select(row, "dt a")
            if not title_node:
                title_node = ctx.select(row, "a[title]")
            if not title_node:
                continue
            link = title_node[0]
            href = link.get("href", "")
            name = ctx.clean_text(link.text_content()) or link.get("title", "").strip()
            if not href or not name:
                continue
            cover = ctx.attr(row, "img", "data-original") or ctx.attr(row, "img", "src")
            intro = ctx.text(row, "dd")
            author = ctx.text(row, ".btm a") or self._author_from_btm(ctx.text(row, ".btm"))
            meta = ctx.text(row, ".btm")
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": author,
                "bookUrl": urljoin(self.base_url, href),
                "coverUrl": urljoin(self.base_url, cover) if cover else "",
                "intro": intro,
                "kind": group_title,
                "lastChapter": "",
                "wordCount": self._extract_word_count(meta),
                "groupId": group_id,
                "groupTitle": group_title,
                "rank": len(items) + 1,
            })
        if items:
            return self._dedupe(items)
        return self._parse_news_rows(ctx, html_or_node, group_id, group_title)

    def _parse_news_rows(self, ctx, html_or_node, group_id: str, group_title: str):
        items = []
        for row in ctx.select(html_or_node, "li"):
            link_nodes = ctx.select(row, ".s2 a")
            if not link_nodes:
                continue
            link = link_nodes[0]
            href = link.get("href", "")
            name = ctx.clean_text(link.text_content()) or link.get("title", "").strip()
            if not href or not name:
                continue
            items.append({
                "sourceId": self.id,
                "name": name,
                "author": ctx.text(row, ".s4") or ctx.text(row, ".s5"),
                "bookUrl": urljoin(self.base_url, href),
                "coverUrl": "",
                "intro": "",
                "kind": ctx.text(row, ".s1") or group_title,
                "lastChapter": ctx.text(row, ".s3 a"),
                "groupId": group_id,
                "groupTitle": group_title,
                "rank": len(items) + 1,
            })
        return self._dedupe(items)

    async def detail(self, ctx, book_url: str):
        html = await self._fetch(ctx, book_url)
        name = ctx.attr(html, 'meta[property="og:novel:book_name"]', "content") or ctx.attr(html, 'meta[property="og:title"]', "content") or ctx.text(html, "#info h1")
        author = ctx.attr(html, 'meta[property="og:novel:author"]', "content") or ctx.text(html, "#info p:nth-of-type(1)").replace("作者：", "").strip()
        intro = ctx.attr(html, 'meta[property="og:description"]', "content") or ctx.text(html, "#intro")
        cover = ctx.attr(html, 'meta[property="og:image"]', "content") or ctx.attr(html, "#fmimg img", "data-original") or ctx.attr(html, "#fmimg img", "src")
        kind = ctx.attr(html, 'meta[property="og:novel:category"]', "content")
        status = ctx.attr(html, 'meta[property="og:novel:status"]', "content")
        last = ctx.attr(html, 'meta[property="og:novel:latest_chapter_name"]', "content")
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": urljoin(self.base_url, book_url),
            "coverUrl": urljoin(self.base_url, cover) if cover else "",
            "intro": intro,
            "kind": " / ".join(part for part in [kind, status] if part),
            "lastChapter": last,
            "tocUrl": urljoin(self.base_url, book_url),
            "authRequired": False,
        }

    async def toc(self, ctx, toc_url: str):
        html = await self._fetch(ctx, toc_url)
        chapters = []
        seen = set()
        for a in ctx.select(html, '#list a[rel="chapter"], #list dl a[href*=".html"]'):
            href = a.get("href", "")
            title = ctx.clean_text(a.text_content())
            if not href or not title or href in seen:
                continue
            seen.add(href)
            chapters.append({
                "sourceId": self.id,
                "index": len(chapters) + 1,
                "title": title,
                "chapterUrl": urljoin(self.base_url, href),
                "isVip": False,
                "isLocked": False,
            })
        return chapters

    async def chapter(self, ctx, chapter_url: str):
        html = await self._fetch(ctx, chapter_url)
        title = ctx.text(html, ".bookname") or ctx.text(html, "h1")
        content = self._clean_chapter_html(ctx, ctx.html(html, "#content") or ctx.html(html, "#booktxt"))
        return {
            "sourceId": self.id,
            "title": title,
            "content": content,
            "chapterUrl": urljoin(self.base_url, chapter_url),
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _clean_chapter_html(self, ctx, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for selector in [
            "script",
            "style",
            ".readtj",
            ".bottem1",
            ".bottem2",
            "#content_1",
            "#content_2",
            "#content_3",
        ]:
            for node in soup.select(selector):
                node.decompose()
        content = ctx.clean_html(str(soup))
        content = re.sub(r"(?m)^.*(?:69书吧|最新网址|返回目录|加入书签|推荐阅读|新书推荐).*$", "", content)
        content = re.sub(r"章节内容缺失或章节不存在.*", "", content)
        content = re.sub(r"\n{3,}", "\n\n", content)
        return content.strip()

    def _is_search_captcha(self, html: str) -> bool:
        return "请输入验证码" in html and "verifycode" in html

    def _author_from_btm(self, text: str) -> str:
        text = text or ""
        text = re.sub(r"\d+万字.*$", "", text).strip()
        return text

    def _extract_word_count(self, text: str) -> str:
        match = re.search(r"(\d+(?:\.\d+)?万字)", text or "")
        return match.group(1) if match else ""

    def _dedupe(self, items):
        seen = set()
        result = []
        for item in items:
            key = item.get("bookUrl") or item.get("name")
            if not key or key in seen:
                continue
            seen.add(key)
            item["rank"] = len(result) + 1
            result.append(item)
        return result
