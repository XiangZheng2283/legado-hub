"""Execute Legado source rules: search, detail, toc, content."""

from __future__ import annotations

import base64
import json
from urllib.parse import urljoin, quote

import lxml.html

from app.engine.fetcher import Fetcher, build_search_url, parse_request_spec
from app.engine.extractor import extract_list, extract_field, extract_fields_from_element
from app.engine.proxy import ProxyConfig
from app.rules.models import SearchResultItem, BookDetail, ChapterItem, ChapterContent, SourceError


def encode_book_id(source_id: str, book_url: str) -> str:
    encoded = base64.urlsafe_b64encode(book_url.encode("utf-8")).decode("utf-8").rstrip("=")
    return f"{source_id}:{encoded}"


def decode_book_id(book_id: str) -> tuple[str, str]:
    source_id, encoded = book_id.split(":", 1)
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += "=" * padding
    book_url = base64.urlsafe_b64decode(encoded).decode("utf-8")
    return source_id, book_url


def encode_chapter_id(source_id: str, chapter_url: str) -> str:
    encoded = base64.urlsafe_b64encode(chapter_url.encode("utf-8")).decode("utf-8").rstrip("=")
    return f"{source_id}:{encoded}"


def decode_chapter_id(chapter_id: str) -> tuple[str, str]:
    source_id, encoded = chapter_id.split(":", 1)
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += "=" * padding
    chapter_url = base64.urlsafe_b64decode(encoded).decode("utf-8")
    return source_id, chapter_url


class LegadoExecutor:
    def __init__(self, fetcher: Fetcher, proxy_mode: str = "auto", proxy_config: ProxyConfig | None = None):
        self.fetcher = fetcher
        self.proxy_mode = proxy_mode
        self.proxy_config = proxy_config
        self._last_meta: dict = {}

    def get_last_meta(self) -> dict:
        return self._last_meta.copy()

    async def _fetch(self, spec: dict) -> tuple[str, str]:
        result = await self.fetcher.fetch_with_proxy(spec, self.proxy_mode, self.proxy_config)
        self._last_meta = {
            "proxyUsed": result.proxy_used,
            "attempts": result.attempts,
            "directError": result.direct_error,
            "proxyError": result.proxy_error,
        }
        if not result.success:
            raise Exception(result.direct_error or result.proxy_error)
        return result.text, result.final_url

    async def search(self, source: dict, source_id: str, keyword: str, page: int = 1) -> tuple[list[SearchResultItem], SourceError | None]:
        try:
            raw = source["raw"]
            base_url = raw.get("bookSourceUrl", "")
            search_url_template = raw.get("searchUrl", "")

            spec = parse_request_spec(search_url_template, base_url)
            charset = spec.get("charset", "utf-8")
            url_template = spec["url"]
            url_template = url_template.replace("{{key}}", quote(keyword, encoding=charset, safe=""))
            url_template = url_template.replace("{{page}}", str(page))
            spec["url"] = url_template

            html, final_url = await self._fetch(spec)

            rule_search = raw.get("ruleSearch", {})
            book_list_rule = rule_search.get("bookList", "")
            if not book_list_rule:
                return [], SourceError(sourceId=source_id, stage="search", url=spec["url"], proxyUsed=self._last_meta.get("proxyUsed", False), error="missing bookList rule")

            book_elements = extract_list(html, book_list_rule, final_url)

            results = []
            for el in book_elements:
                fields, unsupported = extract_fields_from_element(el, rule_search, final_url)
                if unsupported:
                    return [], SourceError(sourceId=source_id, stage="search", url=spec["url"], proxyUsed=self._last_meta.get("proxyUsed", False), error=f"unsupported syntax: {', '.join(unsupported)}")
                book_url = fields.get("bookUrl", "")
                if not book_url:
                    continue

                item = SearchResultItem(
                    bookId=encode_book_id(source_id, book_url),
                    name=fields.get("name", ""),
                    author=fields.get("author", ""),
                    coverUrl=fields.get("coverUrl", ""),
                    intro=fields.get("intro", ""),
                    kind=fields.get("kind", ""),
                    lastChapter=fields.get("lastChapter", ""),
                    wordCount=fields.get("wordCount", ""),
                    bookUrl=book_url,
                    sourceId=source_id,
                    sourceName=source.get("sourceName", ""),
                )
                results.append(item)

            return results, None

        except Exception as e:
            return [], SourceError(sourceId=source_id, stage="search", url="", proxyUsed=self._last_meta.get("proxyUsed", False), error=str(e))

    async def book_detail(self, source: dict, source_id: str, book_url: str) -> tuple[BookDetail | None, SourceError | None]:
        try:
            raw = source["raw"]
            base_url = raw.get("bookSourceUrl", "")

            spec = parse_request_spec(book_url, base_url)
            html, final_url = await self._fetch(spec)

            rule_book = raw.get("ruleBookInfo", {})
            fields, unsupported = extract_fields_from_element(lxml.html.fromstring(html), rule_book, final_url)
            if unsupported:
                return None, SourceError(sourceId=source_id, stage="detail", url=book_url, proxyUsed=self._last_meta.get("proxyUsed", False), error=f"unsupported syntax: {', '.join(unsupported)}")

            toc_url = fields.get("tocUrl", "")
            if not toc_url:
                toc_url = book_url

            detail = BookDetail(
                bookId=encode_book_id(source_id, book_url),
                name=fields.get("name", ""),
                author=fields.get("author", ""),
                coverUrl=fields.get("coverUrl", ""),
                intro=fields.get("intro", ""),
                kind=fields.get("kind", ""),
                lastChapter=fields.get("lastChapter", ""),
                wordCount=fields.get("wordCount", ""),
                tocUrl=toc_url,
                sourceId=source_id,
                sourceName=source.get("sourceName", ""),
            )
            return detail, None

        except Exception as e:
            return None, SourceError(sourceId=source_id, stage="detail", url=book_url, proxyUsed=self._last_meta.get("proxyUsed", False), error=str(e))

    async def toc(self, source: dict, source_id: str, toc_url: str) -> tuple[list[ChapterItem], SourceError | None]:
        try:
            raw = source["raw"]
            base_url = raw.get("bookSourceUrl", "")

            spec = parse_request_spec(toc_url, base_url)
            html, final_url = await self._fetch(spec)

            rule_toc = raw.get("ruleToc", {})
            chapter_list_rule = rule_toc.get("chapterList", "")
            if not chapter_list_rule:
                return [], SourceError(sourceId=source_id, stage="toc", url=toc_url, proxyUsed=self._last_meta.get("proxyUsed", False), error="missing chapterList rule")

            chapter_elements = extract_list(html, chapter_list_rule, final_url)

            chapters = []
            for el in chapter_elements:
                fields, unsupported = extract_fields_from_element(el, rule_toc, final_url)
                if unsupported:
                    return [], SourceError(sourceId=source_id, stage="toc", url=toc_url, proxyUsed=self._last_meta.get("proxyUsed", False), error=f"unsupported syntax: {', '.join(unsupported)}")
                chapter_url = fields.get("chapterUrl", "")
                if not chapter_url:
                    continue
                chapter = ChapterItem(
                    chapterId=encode_chapter_id(source_id, chapter_url),
                    title=fields.get("chapterName", ""),
                    chapterUrl=chapter_url,
                    updateTime=fields.get("updateTime", ""),
                    sourceId=source_id,
                )
                chapters.append(chapter)

            return chapters, None

        except Exception as e:
            return [], SourceError(sourceId=source_id, stage="toc", url=toc_url, proxyUsed=self._last_meta.get("proxyUsed", False), error=str(e))

    async def content(self, source: dict, source_id: str, chapter_url: str) -> tuple[ChapterContent | None, SourceError | None]:
        try:
            raw = source["raw"]
            base_url = raw.get("bookSourceUrl", "")

            spec = parse_request_spec(chapter_url, base_url)
            html, final_url = await self._fetch(spec)

            rule_content = raw.get("ruleContent", {})
            content_rule = rule_content.get("content", "")
            if not content_rule:
                return None, SourceError(sourceId=source_id, stage="content", url=chapter_url, proxyUsed=self._last_meta.get("proxyUsed", False), error="missing content rule")

            if "<js>" in content_rule or "@js" in content_rule:
                return None, SourceError(sourceId=source_id, stage="content", url=chapter_url, proxyUsed=self._last_meta.get("proxyUsed", False), error="unsupported rule syntax: js")

            text = extract_field(html, content_rule, final_url)

            title_rule = rule_content.get("title", "")
            title = ""
            if title_rule:
                title = extract_field(html, title_rule, final_url)

            return ChapterContent(
                chapterId=encode_chapter_id(source_id, chapter_url),
                title=title,
                content=text,
            ), None

        except Exception as e:
            return None, SourceError(sourceId=source_id, stage="content", url=chapter_url, proxyUsed=self._last_meta.get("proxyUsed", False), error=str(e))
