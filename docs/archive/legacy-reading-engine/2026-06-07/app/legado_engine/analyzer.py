"""Top-level execution pipeline for Legado engine stages."""

from __future__ import annotations

import base64
import json
import time
from urllib.parse import urljoin

from app.legado_engine.models import (
    LegadoSource,
    RequestSpec,
    TraceEvent,
    EngineResult,
    RuleContext,
)
from app.legado_engine.request_builder import build_search_request, parse_request_spec, apply_context_to_spec, merge_headers
from app.legado_engine.http_runtime import HttpRuntime
from app.legado_engine.rule_executor import extract_list, extract_field, extract_fields_from_element
from app.legado_engine.capabilities import detect_unsupported_syntax
from app.engine.proxy import ProxyConfig
from app.rules.models import SearchResultItem, BookDetail, ChapterItem, ChapterContent


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


class LegadoAnalyzer:
    def __init__(
        self,
        http: HttpRuntime | None = None,
        proxy_mode: str = "auto",
        proxy_config: ProxyConfig | None = None,
    ):
        self.http = http or HttpRuntime()
        self.proxy_mode = proxy_mode
        self.proxy_config = proxy_config or ProxyConfig()
        self._last_meta: dict = {}

    def get_last_meta(self) -> dict:
        return self._last_meta.copy()

    def _fetch(self, spec: RequestSpec, source_id: str, stage: str) -> tuple[str, str]:
        """Synchronous-style fetch for use in async contexts."""
        raise RuntimeError("Use async methods")

    async def _fetch_async(self, spec: RequestSpec, source_id: str, stage: str) -> tuple[str, str]:
        result = await self.http.fetch_with_proxy(
            spec,
            proxy_mode=self.proxy_mode,
            proxy_config=self.proxy_config,
            source_id=source_id,
            stage=stage,
        )
        self._last_meta = {
            "proxyUsed": result.proxy_used,
            "attempts": result.attempts,
            "directError": result.direct_error,
            "proxyError": result.proxy_error,
        }
        if not result.success:
            raise Exception(result.direct_error or result.proxy_error)
        return result.text, result.final_url

    async def search(
        self,
        source: LegadoSource,
        keyword: str,
        page: int = 1,
        context: RuleContext | None = None,
    ) -> EngineResult:
        unsupported = detect_unsupported_syntax(source.raw)
        if unsupported:
            return EngineResult(
                success=False,
                error=f"unsupported syntax: {', '.join(unsupported)}",
                unsupported_reasons=unsupported,
            )

        ctx = context or RuleContext(base_url=source.source_url)
        spec = build_search_request(source.search_url, keyword, page, source.source_url, ctx)
        spec.headers = merge_headers(source.header, spec.headers, ctx)

        t0 = time.perf_counter()
        try:
            html, final_url = await self._fetch_async(spec, source.source_id, "search")
        except Exception as e:
            return EngineResult(
                success=False,
                error=str(e),
                trace=self.http.trace,
            )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        rule_search = source.rule_search
        book_list_rule = rule_search.get("bookList", "")
        if not book_list_rule:
            return EngineResult(
                success=False,
                error="missing bookList rule",
                trace=self.http.trace,
            )

        document = self._parse_body(html)
        book_elements = extract_list(document, book_list_rule, final_url, ctx)
        results = []
        for el in book_elements:
            fields, field_unsupported = extract_fields_from_element(el, rule_search, final_url, ctx)
            if field_unsupported:
                return EngineResult(
                    success=False,
                    error=f"unsupported syntax: {', '.join(field_unsupported)}",
                    unsupported_reasons=field_unsupported,
                    trace=self.http.trace,
                )
            book_url = self._absolute_url(fields.get("bookUrl", ""), final_url)
            if not book_url:
                continue
            item = SearchResultItem(
                bookId=encode_book_id(source.source_id, book_url),
                name=fields.get("name", ""),
                author=fields.get("author", ""),
                coverUrl=self._absolute_url(fields.get("coverUrl", ""), final_url),
                intro=fields.get("intro", ""),
                kind=fields.get("kind", ""),
                lastChapter=fields.get("lastChapter", ""),
                wordCount=fields.get("wordCount", ""),
                bookUrl=book_url,
                sourceId=source.source_id,
                sourceName=source.source_name,
            )
            results.append(item)

        return EngineResult(
            success=True,
            data=[r.model_dump() for r in results],
            trace=self.http.trace,
        )

    async def book_detail(
        self,
        source: LegadoSource,
        book_url: str,
        context: RuleContext | None = None,
    ) -> EngineResult:
        ctx = context or RuleContext(base_url=source.source_url)
        spec = parse_request_spec(book_url, source.source_url)
        spec = apply_context_to_spec(spec, ctx)
        spec.headers = merge_headers(source.header, spec.headers, ctx)

        try:
            html, final_url = await self._fetch_async(spec, source.source_id, "detail")
        except Exception as e:
            return EngineResult(success=False, error=str(e), trace=self.http.trace)

        rule_book = source.rule_book_info
        fields, unsupported = extract_fields_from_element(self._parse_body(html), rule_book, final_url, ctx)
        if unsupported:
            return EngineResult(
                success=False,
                error=f"unsupported syntax: {', '.join(unsupported)}",
                unsupported_reasons=unsupported,
                trace=self.http.trace,
            )

        toc_url = self._absolute_url(fields.get("tocUrl", ""), final_url)
        if not toc_url:
            toc_url = book_url

        detail = BookDetail(
            bookId=encode_book_id(source.source_id, book_url),
            name=fields.get("name", ""),
            author=fields.get("author", ""),
            coverUrl=self._absolute_url(fields.get("coverUrl", ""), final_url),
            intro=fields.get("intro", ""),
            kind=fields.get("kind", ""),
            lastChapter=fields.get("lastChapter", ""),
            wordCount=fields.get("wordCount", ""),
            tocUrl=toc_url,
            sourceId=source.source_id,
            sourceName=source.source_name,
        )
        return EngineResult(success=True, data=detail.model_dump(), trace=self.http.trace)

    async def toc(
        self,
        source: LegadoSource,
        toc_url: str,
        context: RuleContext | None = None,
    ) -> EngineResult:
        ctx = context or RuleContext(base_url=source.source_url)
        spec = parse_request_spec(toc_url, source.source_url)
        spec = apply_context_to_spec(spec, ctx)
        spec.headers = merge_headers(source.header, spec.headers, ctx)

        try:
            html, final_url = await self._fetch_async(spec, source.source_id, "toc")
        except Exception as e:
            return EngineResult(success=False, error=str(e), trace=self.http.trace)

        rule_toc = source.rule_toc
        chapter_list_rule = rule_toc.get("chapterList", "")
        if not chapter_list_rule:
            return EngineResult(success=False, error="missing chapterList rule", trace=self.http.trace)

        chapters = []
        visited: set[str] = set()
        current_html = html
        current_url = final_url
        for _page_no in range(1, 11):
            if current_url in visited:
                break
            visited.add(current_url)
            document = self._parse_body(current_html)
            chapter_elements = extract_list(document, chapter_list_rule, current_url, ctx)
            for el in chapter_elements:
                fields, unsupported = extract_fields_from_element(el, rule_toc, current_url, ctx)
                if unsupported:
                    return EngineResult(
                        success=False,
                        error=f"unsupported syntax: {', '.join(unsupported)}",
                        unsupported_reasons=unsupported,
                        trace=self.http.trace,
                    )
                chapter_url = self._absolute_url(fields.get("chapterUrl", ""), current_url)
                if not chapter_url:
                    continue
                chapter = ChapterItem(
                    chapterId=encode_chapter_id(source.source_id, chapter_url),
                    title=fields.get("chapterName", ""),
                    chapterUrl=chapter_url,
                    updateTime=fields.get("updateTime", ""),
                    sourceId=source.source_id,
                )
                chapters.append(chapter)

            next_rule = rule_toc.get("nextTocUrl", "")
            next_url = extract_field(document, next_rule, current_url, ctx) if next_rule else ""
            if not next_url or next_url in visited:
                break
            next_spec = parse_request_spec(next_url, source.source_url)
            next_spec = apply_context_to_spec(next_spec, ctx)
            next_spec.headers = merge_headers(source.header, next_spec.headers, ctx)
            try:
                current_html, current_url = await self._fetch_async(next_spec, source.source_id, "toc")
            except Exception as e:
                return EngineResult(success=False, error=str(e), trace=self.http.trace)

        return EngineResult(
            success=True,
            data=[c.model_dump() for c in chapters],
            trace=self.http.trace,
        )

    async def content(
        self,
        source: LegadoSource,
        chapter_url: str,
        context: RuleContext | None = None,
    ) -> EngineResult:
        ctx = context or RuleContext(base_url=source.source_url)
        spec = parse_request_spec(chapter_url, source.source_url)
        spec = apply_context_to_spec(spec, ctx)
        spec.headers = merge_headers(source.header, spec.headers, ctx)

        try:
            html, final_url = await self._fetch_async(spec, source.source_id, "content")
        except Exception as e:
            return EngineResult(success=False, error=str(e), trace=self.http.trace)

        rule_content = source.rule_content
        content_rule = rule_content.get("content", "")
        if not content_rule:
            return EngineResult(success=False, error="missing content rule", trace=self.http.trace)

        texts: list[str] = []
        title = ""
        visited: set[str] = set()
        current_html = html
        current_url = final_url
        for page_no in range(1, 11):
            if current_url in visited:
                break
            visited.add(current_url)
            document = self._parse_body(current_html)
            page_text = extract_field(document, content_rule, current_url, ctx)
            if page_text:
                texts.append(page_text)
            title_rule = rule_content.get("title", "")
            if page_no == 1 and title_rule:
                title = extract_field(document, title_rule, current_url, ctx)
            next_rule = rule_content.get("nextContentUrl", "")
            next_url = extract_field(document, next_rule, current_url, ctx) if next_rule else ""
            if not next_url or next_url in visited:
                break
            next_spec = parse_request_spec(next_url, source.source_url)
            next_spec = apply_context_to_spec(next_spec, ctx)
            next_spec.headers = merge_headers(source.header, next_spec.headers, ctx)
            try:
                current_html, current_url = await self._fetch_async(next_spec, source.source_id, "content")
            except Exception as e:
                return EngineResult(success=False, error=str(e), trace=self.http.trace)

        text = "\n".join(texts)

        content = ChapterContent(
            chapterId=encode_chapter_id(source.source_id, chapter_url),
            title=title,
            content=text,
        )
        return EngineResult(success=True, data=content.model_dump(), trace=self.http.trace)

    def _parse_body(self, body: str):
        stripped = (body or "").strip()
        if stripped.startswith(("{", "[")):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                pass
        return body

    def _absolute_url(self, url: str, base_url: str) -> str:
        if not url:
            return ""
        return urljoin(base_url, url)
