"""Integration tests for native-like Legado rule execution."""

import asyncio
import json
from unittest.mock import AsyncMock

from app.legado_engine.analyzer import LegadoAnalyzer
from app.legado_engine.http_runtime import HttpRuntime
from app.legado_engine.models import LegadoSource, RuleContext
from app.legado_engine.rule_executor import extract_field, extract_list


def test_rule_executor_supports_xpath_jsonpath_regex_and_safe_js():
    html = """
    <html><body>
      <div class="book" data-id="42"><a href="/book/42">凡人修仙传</a></div>
      <script>window.__DATA__ = {"author":"忘语"};</script>
    </body></html>
    """
    payload = {"data": {"items": [{"name": "凡人修仙传", "url": "/book/42"}]}}

    assert extract_list(payload, "$.data.items[*]") == [{"name": "凡人修仙传", "url": "/book/42"}]
    assert extract_field(html, "//div[@class='book']/a/text()") == "凡人修仙传"
    assert extract_field(html, r"regex:__DATA__\s*=\s*(\{.*?\});") == '{"author":"忘语"}'
    assert extract_field(html, "class.book@tag.a@text@js:result.replace(/修仙传/, '')") == "凡人"


def test_rule_executor_context_put_get_and_variable_replacement():
    context = RuleContext(base_url="https://example.com", variables={"key": "凡人修仙传"})
    assert extract_field("", "@put:lastKey={{key}}", context=context) == "凡人修仙传"
    assert context.get("lastKey") == "凡人修仙传"
    assert extract_field("", "@get:lastKey", context=context) == "凡人修仙传"


def test_json_search_pipeline_uses_jsonpath_rules(monkeypatch):
    http = HttpRuntime()
    body = json.dumps({
        "items": [
            {"name": "凡人修仙传", "author": "忘语", "url": "/book/1"},
            {"name": "凡人外传", "author": "忘语", "url": "/book/2"},
        ]
    }, ensure_ascii=False)
    monkeypatch.setattr(http, "fetch_with_proxy", AsyncMock(return_value=type("Result", (), {
        "text": body,
        "final_url": "https://example.com/api/search",
        "proxy_used": False,
        "attempts": 1,
        "direct_error": "",
        "proxy_error": "",
        "success": True,
    })()))

    source = LegadoSource(
        source_id="json-source",
        source_name="JSON Source",
        source_url="https://example.com",
        search_url="/api/search?key={{key}}",
        rule_search={
            "bookList": "$.items[*]",
            "name": "$.name",
            "author": "$.author",
            "bookUrl": "$.url",
        },
        raw={},
    )
    result = asyncio.run(LegadoAnalyzer(http=http).search(source, "凡人"))
    assert result.success is True
    assert len(result.data) == 2
    assert result.data[0]["name"] == "凡人修仙传"
    assert result.data[0]["bookUrl"] == "https://example.com/book/1"


def test_toc_and_content_follow_next_page_rules(monkeypatch):
    http = HttpRuntime()
    pages = {
        "https://example.com/toc/1": """
          <ul><li><a href="/c/1">第一章</a></li></ul>
          <a class="next" href="/toc/2">下一页</a>
        """,
        "https://example.com/toc/2": """
          <ul><li><a href="/c/2">第二章</a></li></ul>
        """,
        "https://example.com/c/1": """
          <h1>第一章</h1><div class="content">第一段</div>
          <a class="next" href="/c/1-2">下一页</a>
        """,
        "https://example.com/c/1-2": """
          <div class="content">第二段</div>
        """,
    }

    async def fake_fetch(spec, **_kwargs):
        return type("Result", (), {
            "text": pages[spec.url],
            "final_url": spec.url,
            "proxy_used": False,
            "attempts": 1,
            "direct_error": "",
            "proxy_error": "",
            "success": True,
        })()

    monkeypatch.setattr(http, "fetch_with_proxy", fake_fetch)
    source = LegadoSource(
        source_id="paged",
        source_name="Paged",
        source_url="https://example.com",
        rule_toc={
            "chapterList": "tag.li",
            "chapterName": "tag.a@text",
            "chapterUrl": "tag.a@href",
            "nextTocUrl": "class.next@href",
        },
        rule_content={
            "title": "tag.h1@text",
            "content": "class.content@text",
            "nextContentUrl": "class.next@href",
        },
        raw={},
    )

    analyzer = LegadoAnalyzer(http=http)
    toc = asyncio.run(analyzer.toc(source, "https://example.com/toc/1"))
    assert toc.success is True
    assert [item["title"] for item in toc.data] == ["第一章", "第二章"]

    content = asyncio.run(analyzer.content(source, "https://example.com/c/1"))
    assert content.success is True
    assert content.data["title"] == "第一章"
    assert content.data["content"] == "第一段\n第二段"
