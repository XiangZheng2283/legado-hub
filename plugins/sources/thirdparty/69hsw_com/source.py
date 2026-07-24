"""Plugin for 69书屋 (69hsw.com)."""

import re
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from app.source_plugins.errors import BrowserRequired
from app.source_plugins.search_enrichment import enrich_search_items_from_detail


class Source:
    id = "69hsw_com"
    name = "69书屋"
    contract_version = "1.0"
    last_modified = "2026-07-25"

    _AD_LINE_RE = re.compile(
        r"(?m)^.*(?:"
        r"69书吧|69书屋|"
        r"无错版本在读|"
        r"首发本小说|"
        r"6\s*[=＝]\s*9\s*[+＋]?\s*书[_＿\s]*吧|"
        r"正确内.?容在|"
        r"[%％]\s*六九\s*[%％]|"
        r"书[''′]?\s*吧\s*读|"
        r"最新网址|返回目录|加入书签|推荐阅读|新书推荐|"
        r"请稍后重新尝试|报错|下载APP|无广告、完整阅读"
        r").*$"
    )
    _INLINE_AD_RE = re.compile(
        r"(?:"
        r"无错版本在读[！!]?\s*6\s*[=＝]\s*9\s*[+＋]?\s*书[_＿\s]*吧\s*首发本小说[。．.]?"
        r"|"
        r"正确内[（(]?\s*容在\s*[%％]?\s*六九\s*[%％]?\s*书[''′]?\s*吧\s*读[！!]?\s*[\{｛]?"
        r")"
    )

    @classmethod
    def get_ad_patterns(cls) -> list[str]:
        return [
            r"无错版本在读",
            r"首发本小说",
            r"6\s*[=＝]\s*9\s*[+＋]?\s*书[_＿\s]*吧",
            r"新?69\s*书\s*[吧屋]",
            r"正确内.?容在",
            r"[%％]\s*六九\s*[%％]",
            r"书[''′]?\s*吧\s*读",
            r"最新网址|返回目录|加入书签|推荐阅读|新书推荐",
        ]
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
        return await ctx.access.http.fetch_text(
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
        items = []
        try:
            html = await self._fetch(ctx, url)
            if self._is_search_captcha(html):
                solved = await self._solve_search_captcha(ctx, html, url)
                if solved:
                    html = solved
                else:
                    raise BrowserRequired("69hsw search requires numeric captcha verification", url=urljoin(self.base_url, url))
            items = self._parse_book_cards(ctx, html, "search", "搜索")
            if not items:
                items = self._parse_news_rows(ctx, html, "search", "搜索")
            exact = [item for item in items if keyword and keyword in item.get("name", "")]
            items = exact or items
        except BrowserRequired:
            raise
        except Exception as exc:
            ctx.trace("search_fallback", url=urljoin(self.base_url, url), message=str(exc))
        if not items:
            items = await self._search_from_explore(ctx, keyword)
        return await enrich_search_items_from_detail(self, ctx, items)

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
        update_time = ctx.attr(html, 'meta[property="og:novel:update_time"]', "content")
        if not update_time:
            for p in ctx.select(html, "#info p"):
                text = p.text_content().strip()
                if "更新" in text:
                    update_time = text.replace("更新时间：", "").strip()
                    break
        return {
            "sourceId": self.id,
            "name": name,
            "author": author,
            "bookUrl": urljoin(self.base_url, book_url),
            "coverUrl": urljoin(self.base_url, cover) if cover else "",
            "intro": intro,
            "kind": " / ".join(part for part in [kind, status] if part),
            "lastChapter": last,
            "wordCount": "",
            "updateTime": update_time,
            "tocUrl": urljoin(self.base_url, book_url),
            "authRequired": False,
        }

    async def toc(self, ctx, toc_url: str):
        html = await self._fetch(ctx, toc_url)
        chapters = []
        seen = set()
        soup = BeautifulSoup(html or "", "html.parser")
        list_dl = soup.select_one("#list dl")
        if list_dl:
            in_full_catalog = False
            for child in list_dl.find_all(["dt", "a"], recursive=False):
                if child.name == "dt":
                    in_full_catalog = "目录章节" in child.get_text(" ", strip=True)
                    continue
                if not in_full_catalog:
                    continue
                href = child.get("href", "")
                title_node = child.find("dd")
                title = ctx.clean_text(title_node.get_text(" ", strip=True) if title_node else child.get_text(" ", strip=True))
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
        if not chapters:
            for a in ctx.select(html, '#list a[rel="chapter"], #list a[href*=".html"]'):
                href = a.get("href", "")
                title = ctx.clean_text(a.text_content())
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

    def _chapter_stem(self, url: str) -> str:
        """Extract chapter stem from URL, e.g. /48/38642.html -> /48/38642"""
        path = url.split("?")[0].split("#")[0]
        if "_" in path:
            return path.rsplit("_", 1)[0]
        return path.rsplit(".", 1)[0] if "." in path else path

    async def chapter(self, ctx, chapter_url: str):
        parts: list[str] = []
        current_url = chapter_url
        title = ""
        original_stem = self._chapter_stem(chapter_url)
        while current_url and len(parts) < 10:
            html = await self._fetch(ctx, current_url)
            if not title:
                title = ctx.text(html, ".bookname") or ctx.text(html, "h1")
            content = self._clean_chapter_html(ctx, ctx.html(html, "#content") or ctx.html(html, "#booktxt"))
            if content:
                parts.append(content)
            next_href = ctx.attr(html, "#next_url", "href")
            if not next_href or next_href == "javascript:void(0);":
                break
            next_url = urljoin(current_url, next_href)
            if self._chapter_stem(next_url) != original_stem:
                break
            current_url = next_url
        title = re.sub(r"[（(][\d/]+[）)]", "", title).strip()
        return {
            "sourceId": self.id,
            "title": title,
            "content": "\n\n".join(parts),
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
        paragraphs = []
        for p in soup.find_all("p"):
            text = " ".join(p.get_text(" ", strip=True).split())
            if text:
                paragraphs.append(text)
        if paragraphs:
            content = "\n\n".join(paragraphs)
        else:
            for tag in soup.find_all("br"):
                tag.replace_with("\n")
            text = soup.get_text("\n", strip=True)
            lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
            content = "\n\n".join(lines)
        content = self._AD_LINE_RE.sub("", content)
        content = self._INLINE_AD_RE.sub("", content)
        content = re.sub(r"章节内容缺失或章节不存在.*", "", content)
        content = re.sub(r"\n{3,}", "\n\n", content)
        return content.strip()

    def _is_search_captcha(self, html: str) -> bool:
        return "请输入验证码" in html and "verifycode" in html

    async def _solve_search_captcha(self, ctx, html: str, url: str) -> str | None:
        """Auto-solve the numeric captcha shown in search results.

        The captcha page renders the code as plain text in
        ``<div class="modal-code">1234</div>`` and expects a POST
        with the hidden ``searchkey`` and the ``verifycode``.
        """
        code = ctx.regex(html, r'<div class="modal-code">(\d+)</div>')
        if not code:
            return None
        hidden_key = ctx.regex(html, r'<input type="hidden" name="searchkey" value="([^"]*)"')
        post_url = urljoin(self.base_url, url)
        return await ctx.access.http.fetch_text(
            post_url,
            method="POST",
            data={"searchkey": hidden_key or "", "verifycode": code},
            headers={"referer": post_url, **self.headers},
        )

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
