"""Explore / ranking / discover parsing for Legado engine."""

from __future__ import annotations

import json
from urllib.parse import urljoin

from app.legado_engine.models import LegadoSource, RequestSpec, EngineResult, RuleContext
from app.legado_engine.request_builder import parse_request_spec, apply_context_to_spec
from app.legado_engine.http_runtime import HttpRuntime
from app.legado_engine.selectors import extract_list, extract_field, extract_fields_from_element
from app.legado_engine.analyzer import encode_book_id
from app.rules.models import SearchResultItem
from app.engine.proxy import ProxyConfig


class ExploreExecutor:
    def __init__(
        self,
        http: HttpRuntime | None = None,
        proxy_mode: str = "auto",
        proxy_config: ProxyConfig | None = None,
    ):
        self.http = http or HttpRuntime()
        self.proxy_mode = proxy_mode
        self.proxy_config = proxy_config or ProxyConfig()

    def parse_explore_groups(self, source: LegadoSource) -> list[dict]:
        """Parse exploreUrl into groups/items.

        exploreUrl can be:
        - Simple URL string
        - JSON array of {title, url}
        - JSON object with nested groups
        """
        explore_url = source.explore_url
        if not explore_url:
            return []

        # Try JSON parse first
        if explore_url.strip().startswith(("[", "{")):
            try:
                data = json.loads(explore_url)
                if isinstance(data, list):
                    return [{"title": item.get("title", ""), "url": item.get("url", ""), "style": item.get("style", {})} for item in data if isinstance(item, dict)]
                if isinstance(data, dict):
                    groups = []
                    for key, value in data.items():
                        if isinstance(value, list):
                            groups.append({
                                "title": key,
                                "items": [{"title": v.get("title", ""), "url": v.get("url", "")} for v in value if isinstance(v, dict)]
                            })
                        elif isinstance(value, dict):
                            groups.append({"title": key, "items": [{"title": value.get("title", ""), "url": value.get("url", "")}]})
                    return groups
            except json.JSONDecodeError:
                pass

        # Fallback: treat as single URL
        return [{"title": "默认", "url": explore_url}]

    async def execute_explore(
        self,
        source: LegadoSource,
        explore_url: str,
        page: int = 1,
        context: RuleContext | None = None,
    ) -> EngineResult:
        ctx = context or RuleContext(base_url=source.source_url)
        spec = parse_request_spec(explore_url, source.source_url)
        spec.url = spec.url.replace("{{page}}", str(page))
        spec = apply_context_to_spec(spec, ctx)

        try:
            result = await self.http.fetch_with_proxy(
                spec,
                proxy_mode=self.proxy_mode,
                proxy_config=self.proxy_config,
                source_id=source.source_id,
                stage="explore",
            )
            if not result.success:
                return EngineResult(
                    success=False,
                    error=result.direct_error or result.proxy_error,
                    trace=self.http.trace,
                )
        except Exception as e:
            return EngineResult(success=False, error=str(e), trace=self.http.trace)

        html = result.text
        final_url = result.final_url

        rule_search = source.rule_search
        book_list_rule = rule_search.get("bookList", "")
        if not book_list_rule:
            return EngineResult(success=False, error="missing bookList rule for explore", trace=self.http.trace)

        book_elements = extract_list(html, book_list_rule, final_url)
        results = []
        for el in book_elements:
            fields, unsupported = extract_fields_from_element(el, rule_search, final_url)
            if unsupported:
                continue
            book_url = fields.get("bookUrl", "")
            if not book_url:
                continue
            item = SearchResultItem(
                bookId=encode_book_id(source.source_id, book_url),
                name=fields.get("name", ""),
                author=fields.get("author", ""),
                coverUrl=fields.get("coverUrl", ""),
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
