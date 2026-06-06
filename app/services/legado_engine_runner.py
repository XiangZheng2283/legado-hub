"""Adapter that makes the independent Legado engine usable by services."""

from __future__ import annotations

from app.legado_engine.analyzer import LegadoAnalyzer
from app.legado_engine.http_runtime import HttpRuntime
from app.legado_engine.source_adapter import adapt_source_dict
from app.engine.proxy import ProxyConfig
from app.rules.models import SearchResultItem, BookDetail, ChapterItem, ChapterContent, SourceError


class LegadoEngineRunner:
    """Run LegadoSource stages and return the legacy service response shapes."""

    def __init__(
        self,
        user_agent: str = "",
        timeout: float = 8.0,
        proxy_url: str = "",
        proxy_mode: str = "auto",
        proxy_config: ProxyConfig | None = None,
    ):
        self.http = HttpRuntime(user_agent=user_agent, timeout=timeout, proxy_url=proxy_url)
        self.analyzer = LegadoAnalyzer(
            http=self.http,
            proxy_mode=proxy_mode,
            proxy_config=proxy_config or ProxyConfig(),
        )

    def get_last_meta(self) -> dict:
        return self.analyzer.get_last_meta()

    async def close(self) -> None:
        await self.http.close()

    async def search(self, source: dict, source_id: str, keyword: str, page: int = 1) -> tuple[list[SearchResultItem], SourceError | None]:
        legado_source = self._source(source, source_id)
        result = await self.analyzer.search(legado_source, keyword, page)
        if not result.success:
            return [], self._error(source_id, "search", result.error, result)
        return [SearchResultItem(**item) for item in result.data or []], None

    async def book_detail(self, source: dict, source_id: str, book_url: str) -> tuple[BookDetail | None, SourceError | None]:
        legado_source = self._source(source, source_id)
        result = await self.analyzer.book_detail(legado_source, book_url)
        if not result.success:
            return None, self._error(source_id, "detail", result.error, result, book_url)
        return BookDetail(**(result.data or {})), None

    async def toc(self, source: dict, source_id: str, toc_url: str) -> tuple[list[ChapterItem], SourceError | None]:
        legado_source = self._source(source, source_id)
        result = await self.analyzer.toc(legado_source, toc_url)
        if not result.success:
            return [], self._error(source_id, "toc", result.error, result, toc_url)
        return [ChapterItem(**item) for item in result.data or []], None

    async def content(self, source: dict, source_id: str, chapter_url: str) -> tuple[ChapterContent | None, SourceError | None]:
        legado_source = self._source(source, source_id)
        result = await self.analyzer.content(legado_source, chapter_url)
        if not result.success:
            return None, self._error(source_id, "content", result.error, result, chapter_url)
        return ChapterContent(**(result.data or {})), None

    def _source(self, source: dict, source_id: str):
        raw = source.get("raw", source)
        adapted_raw = dict(raw)
        adapted_raw["configId"] = source_id
        legado_source = adapt_source_dict(adapted_raw)
        self.http.cookie_jar_enabled = bool(legado_source.enabled_cookie_jar)
        return legado_source

    def _error(self, source_id: str, stage: str, error: str, result, url: str = "") -> SourceError:
        trace_url = url
        proxy_used = False
        if result.trace:
            last = result.trace[-1]
            trace_url = trace_url or last.url
            proxy_used = last.proxy_used
        return SourceError(
            sourceId=source_id,
            stage=stage,
            url=trace_url,
            proxyUsed=proxy_used,
            error=error or "engine failure",
        )
