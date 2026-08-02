"""Plugin for 爱书网 (asw227.com)."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlencode, urldefrag, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup


CHAPTER_RE = re.compile(r"^第\s*([0-9零〇一二三四五六七八九十百千两]+)\s*章")
SPECIAL_CHAPTER_RE = re.compile(r"^(?:.{0,12}番外|序章|序言|楔子|前言|后记|尾声|终章).{0,24}$")
SEPARATOR_RE = re.compile(r"^[=*_\-]{3,}$")
HASH_RE = re.compile(r"(?<![a-f0-9])[a-f0-9]{32}(?![a-f0-9])", re.I)
LINES_PER_READER_PAGE = 150
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


class Source:
    """Adapt the site's uploaded TXT files to chapter-based reading."""

    id = "aishu99_com"
    name = "爱书网"
    contract_version = "1.0"
    last_modified = "2026-07-31"
    base_url = "https://www.asw227.com"
    download_base = "https://dm.downshu123.com"
    reader_base = "https://dm.downshu321.shop"

    async def _fetch(self, ctx, url: str) -> str:
        return await ctx.access.http.fetch_text(url, headers=REQUEST_HEADERS)

    async def search(self, ctx, keyword: str, page: int) -> list[dict]:
        """Return complete subscription-ready results for the first search page."""
        keyword = (keyword or "").strip()
        if page > 1 or not keyword:
            return []
        query_url = f"{self.base_url}/search.php?{urlencode({'kw': keyword})}"
        html = await self._fetch(ctx, query_url)
        items = self._parse_search(ctx, html)
        exact = [item for item in items if item.get("name", "").casefold() == keyword.casefold()]
        completed: list[dict] = []
        for item in (exact or items[:3]):
            text = await self._fetch(ctx, item["tocUrl"])
            snapshot = self._snapshot(ctx, text, item["fileName"])
            if not snapshot["chapters"]:
                continue
            item.update(self._subscription_fields(snapshot))
            item["rank"] = len(completed) + 1
            item.pop("fileName", None)
            completed.append(item)
        return completed

    def _parse_search(self, ctx, html: str) -> list[dict]:
        soup = BeautifulSoup(html or "", "html.parser")
        items: list[dict] = []
        seen: set[str] = set()
        for card in soup.select(".file-card"):
            link = card.select_one("a.file-card-link[href]")
            name_node = card.select_one(".file-name")
            if link is None or name_node is None:
                continue
            book_url = urljoin(self.base_url, link.get("href", ""))
            file_hash = self._hash(book_url)
            if not file_hash or book_url in seen:
                continue
            seen.add(book_url)
            file_name = ctx.clean_text(name_node.get_text(" ", strip=True))
            meta = self._filename_meta(file_name)
            detail_text = ctx.clean_text(card.get_text(" ", strip=True))
            updated = re.search(r"20\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", detail_text)
            size = re.search(r"\d+(?:\.\d+)?\s*(?:KB|MB|GB)", detail_text, re.I)
            items.append(
                {
                    "sourceId": self.id,
                    "name": meta["name"],
                    "author": meta["author"],
                    "bookUrl": book_url,
                    "tocUrl": self._download_url(file_hash),
                    "coverUrl": "",
                    "intro": "",
                    "kind": meta["status"],
                    "bookStatus": meta["status"],
                    "lastChapter": "",
                    "wordCount": size.group(0) if size else "",
                    "updateTime": updated.group(0) if updated else "",
                    "chapterCount": 0,
                    "fileName": file_name,
                }
            )
        return items

    async def detail(self, ctx, book_url: str) -> dict:
        book_url = self._book_url(book_url)
        html = await self._fetch(ctx, book_url)
        soup = BeautifulSoup(html or "", "html.parser")
        file_hash = self._hash(book_url) or self._hash((soup.select_one("#hash") or {}).get("value", ""))
        display = soup.select_one(".elsetext span")
        file_name = ctx.clean_text(display.get_text(" ", strip=True)) if display else ""
        toc_url = self._download_url(file_hash)
        text = await self._fetch(ctx, toc_url)
        snapshot = self._snapshot(ctx, text, file_name)
        info = self._info_rows(ctx, soup)
        fields = self._subscription_fields(snapshot)
        return {
            "sourceId": self.id,
            "name": snapshot["name"],
            "author": snapshot["author"],
            "bookUrl": book_url,
            "tocUrl": toc_url,
            "coverUrl": "",
            "intro": snapshot["intro"],
            "kind": " / ".join(part for part in (snapshot["tags"], fields["bookStatus"]) if part),
            "bookStatus": fields["bookStatus"],
            "lastChapter": fields["lastChapter"],
            "wordCount": info.get("文件大小", f"{len(text)} 字"),
            "updateTime": info.get("上传时间", ""),
            "chapterCount": fields["chapterCount"],
            "authRequired": False,
        }

    def _info_rows(self, ctx, soup) -> dict[str, str]:
        rows: dict[str, str] = {}
        for node in soup.select(".info-item"):
            label = node.select_one(".info-label")
            value = node.select_one(".info-value")
            if label is None or value is None:
                continue
            key = ctx.clean_text(label.get_text(" ", strip=True)).rstrip("：:")
            rows[key] = ctx.clean_text(value.get_text(" ", strip=True))
        return rows

    async def toc(self, ctx, toc_url: str) -> list[dict]:
        toc_url = self._download_url(self._hash(toc_url))
        text = await self._fetch(ctx, toc_url)
        snapshot = self._snapshot(ctx, text, "")
        file_hash = self._hash(toc_url)
        lines = snapshot["lines"]
        page_count = max(1, (len(lines) + LINES_PER_READER_PAGE - 1) // LINES_PER_READER_PAGE)
        chapters: list[dict] = []
        for index, (position, title, _key) in enumerate(snapshot["chapters"], 1):
            page = position // LINES_PER_READER_PAGE + 1
            page_url = self._reader_url(file_hash, snapshot["name"], page)
            fragment = urlencode({"chapter": index, "title": title, "pages": page_count})
            chapters.append(
                {
                    "sourceId": self.id,
                    "index": index,
                    "title": title,
                    "chapterUrl": f"{page_url}#{fragment}",
                    "updateTime": "",
                    "isVip": False,
                    "isLocked": False,
                }
            )
        return chapters

    async def chapter(self, ctx, chapter_url: str) -> dict:
        page_url, fragment = urldefrag(chapter_url)
        args = parse_qs(fragment)
        title = (args.get("title") or [""])[0]
        chapter_index = int((args.get("chapter") or ["0"])[0] or 0)
        page_count = int((args.get("pages") or ["1"])[0] or 1)
        content = await self._reader_chapter(ctx, page_url, title, page_count)
        if not content:
            title, content = await self._download_chapter(ctx, page_url, chapter_index, title)
        return {
            "sourceId": self.id,
            "title": title,
            "chapterUrl": chapter_url,
            "content": content,
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    async def _reader_chapter(self, ctx, page_url: str, title: str, page_count: int) -> str:
        key = self._chapter_key(title)
        start_page = self._page_number(page_url)
        parts: list[str] = []
        found = False
        for page in range(start_page, page_count + 1):
            html = await self._fetch(ctx, self._set_page(page_url, page))
            lines = self._reader_lines(ctx, html)
            start = 0
            if not found:
                start = next((i + 1 for i, line in enumerate(lines) if line == title), -1)
                if start < 0:
                    return ""
                found = True
            stop = len(lines)
            for i in range(start, len(lines)):
                next_key = self._heading_key_at(lines, i)
                if next_key and next_key != key:
                    stop = i
                    break
            parts.extend(self._body_lines(lines[start:stop], key))
            if stop < len(lines):
                break
        return "\n\n".join(parts).strip()

    async def _download_chapter(self, ctx, page_url: str, index: int, title: str) -> tuple[str, str]:
        text = await self._fetch(ctx, self._download_url(self._hash(page_url)))
        snapshot = self._snapshot(ctx, text, "")
        chapters = snapshot["chapters"]
        if index <= 0 or index > len(chapters):
            return title, ""
        start, parsed_title, key = chapters[index - 1]
        end = chapters[index][0] if index < len(chapters) else len(snapshot["lines"])
        content = "\n\n".join(self._body_lines(snapshot["lines"][start + 1 : end], key)).strip()
        return parsed_title, content

    def _snapshot(self, ctx, text: str, file_name: str) -> dict:
        lines = self._lines(ctx, text)
        chapters = self._chapter_markers(lines)
        file_meta = self._filename_meta(file_name)
        name = self._prefixed_value(lines, "书名") or file_meta["name"]
        author = self._prefixed_value(lines, "作者") or file_meta["author"]
        tags = self._prefixed_value(lines, "Tag列表为") or self._prefixed_value(lines, "标签")
        status = file_meta["status"] or self._status(tags)
        return {
            "name": name or "未知书名",
            "author": author or "佚名",
            "tags": tags,
            "status": status or "状态未知",
            "intro": self._intro(lines, chapters[0][0] if chapters else len(lines)),
            "lines": lines,
            "chapters": chapters,
        }

    def _subscription_fields(self, snapshot: dict) -> dict:
        chapters = snapshot["chapters"]
        return {
            "intro": snapshot["intro"],
            "kind": " / ".join(part for part in (snapshot["tags"], snapshot["status"]) if part),
            "bookStatus": snapshot["status"],
            "lastChapter": chapters[-1][1] if chapters else "",
            "chapterCount": len(chapters),
        }

    def _chapter_markers(self, lines: list[str]) -> list[tuple[int, str, str]]:
        candidates: list[tuple[int, str, str]] = []
        for i, line in enumerate(lines):
            key = self._marker_key(lines, i)
            if key:
                candidates.append((i, line, key))
        marked: list[tuple[int, str, str]] = []
        for candidate in candidates:
            if marked and candidate[2] == marked[-1][2] and candidate[0] - marked[-1][0] <= 3:
                previous = marked[-1]
                previous_has_separator = previous[0] + 1 < len(lines) and self._is_separator(lines[previous[0] + 1])
                if not previous_has_separator:
                    marked[-1] = candidate
                continue
            marked.append(candidate)
        return marked

    def _reader_lines(self, ctx, html: str) -> list[str]:
        soup = BeautifulSoup(html or "", "html.parser")
        box = soup.select_one(".content-box")
        return self._lines(ctx, box.get_text("\n") if box else "")

    def _lines(self, ctx, text: str) -> list[str]:
        return [cleaned for line in (text or "").splitlines() if (cleaned := ctx.clean_text(line))]

    def _body_lines(self, lines: list[str], current_key: str) -> list[str]:
        return [
            line
            for line in lines
            if not self._is_separator(line)
            and line != "*"
            and (self._chapter_key(line) or self._special_chapter_key(line)) != current_key
        ]

    def _heading_key_at(self, lines: list[str], index: int) -> str:
        return self._marker_key(lines, index)

    def _marker_key(self, lines: list[str], index: int) -> str:
        key = self._chapter_key(lines[index])
        if key:
            return key
        if index + 1 < len(lines) and self._is_separator(lines[index + 1]):
            return self._special_chapter_key(lines[index])
        return ""

    def _chapter_key(self, line: str) -> str:
        match = CHAPTER_RE.match(line or "")
        if match:
            return re.sub(r"\s+", "", match.group(1))
        return ""

    def _special_chapter_key(self, line: str) -> str:
        if SPECIAL_CHAPTER_RE.match(line or ""):
            return "special:" + re.sub(r"\s+", "", line or "").removesuffix("点")
        return ""

    def _is_separator(self, line: str) -> bool:
        return bool(SEPARATOR_RE.fullmatch(re.sub(r"\s+", "", line or "")))

    def _intro(self, lines: list[str], end: int) -> str:
        for i, line in enumerate(lines[:end]):
            match = re.match(r"^简介[：:]\s*(.*)$", line)
            if not match:
                continue
            parts = [match.group(1).strip()] if match.group(1).strip() else []
            for extra in lines[i + 1 : end]:
                if self._is_separator(extra) or extra == "*" or extra.startswith(("附：", "Tag列表", "标签")):
                    break
                parts.append(extra)
            return "\n".join(parts).strip()
        return ""

    def _prefixed_value(self, lines: list[str], label: str) -> str:
        match = next((re.match(rf"^{re.escape(label)}[：:]\s*(.*)$", line) for line in lines[:30] if re.match(rf"^{re.escape(label)}[：:]", line)), None)
        return match.group(1).strip() if match else ""

    def _filename_meta(self, file_name: str) -> dict[str, str]:
        stem = re.sub(r"\.txt$", "", (file_name or "").strip(), flags=re.I)
        status = self._status(stem)
        quoted = re.search(r"《([^》]+)》", stem)
        name = quoted.group(1).strip() if quoted else re.sub(r"^[\[【][^\]】]*[\]】]\s*", "", stem)
        name = re.sub(r"(?:作者[：:]|\bby\s*)[^\[【]+$", "", name, flags=re.I).strip(" -_：:")
        author_match = re.search(r"作者[：:]\s*([^\[【]+)$", stem)
        if author_match is None:
            author_match = re.search(r"\bby\s*([^\[【]+)$", stem, re.I)
        author = author_match.group(1).strip() if author_match else ""
        return {"name": name, "author": author, "status": status}

    def _status(self, text: str) -> str:
        value = text or ""
        if re.search(r"完结|完本|全本|番全|全文完|番外完", value):
            return "已完结"
        if re.search(r"连载|未完|更\s*\d+\s*章", value):
            return "连载中"
        return ""

    def _hash(self, value: str) -> str:
        match = HASH_RE.search(unquote(value or ""))
        return match.group(0).lower() if match else ""

    def _book_url(self, value: str) -> str:
        file_hash = self._hash(value)
        return f"{self.base_url}/file.php?hash={file_hash}" if file_hash else urljoin(self.base_url, value)

    def _download_url(self, file_hash: str) -> str:
        return f"{self.download_base}/down.php/{file_hash}.txt" if file_hash else ""

    def _reader_url(self, file_hash: str, name: str, page: int) -> str:
        query = urlencode({"name": f"{name}.txt", "file": f"file/{file_hash}", "encoding": "UTF-8", "page": page})
        return f"{self.reader_base}/read.php?{query}"

    def _page_number(self, url: str) -> int:
        return int((parse_qs(urlsplit(url).query).get("page") or ["1"])[0])

    def _set_page(self, url: str, page: int) -> str:
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        query["page"] = [str(page)]
        return urlunsplit(parsed._replace(query=urlencode(query, doseq=True), fragment=""))
