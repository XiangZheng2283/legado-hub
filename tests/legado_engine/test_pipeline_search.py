"""Tests for search pipeline with mocked HTTP."""

import asyncio
from unittest.mock import AsyncMock

from app.legado_engine.models import LegadoSource
from app.legado_engine.analyzer import LegadoAnalyzer
from app.legado_engine.http_runtime import HttpRuntime


SAMPLE_SEARCH_HTML = """
<html><body>
<div class="result">
  <div class="book">
    <h3 class="name">凡人修仙传</h3>
    <span class="author">忘语</span>
    <a href="/book/1">link</a>
  </div>
</div>
</body></html>
"""


def test_search_pipeline_mock(monkeypatch):
    http = HttpRuntime()
    mock_fetch = AsyncMock(return_value=type('Result', (), {
        'text': SAMPLE_SEARCH_HTML,
        'final_url': 'https://example.com/search',
        'proxy_used': False,
        'attempts': 1,
        'direct_error': '',
        'proxy_error': '',
        'success': True,
    })())
    monkeypatch.setattr(http, 'fetch_with_proxy', mock_fetch)

    analyzer = LegadoAnalyzer(http=http)
    source = LegadoSource(
        source_id="test-source",
        source_name="Test",
        source_url="https://example.com",
        search_url="https://example.com/search?key={{key}}",
        rule_search={
            "bookList": "class.result@class.book",
            "name": "class.name@text",
            "author": "class.author@text",
            "bookUrl": "tag.a@href",
        },
        raw={},
    )
    result = asyncio.run(analyzer.search(source, "凡人修仙传"))
    assert result.success is True
    assert len(result.data) == 1
    assert result.data[0]["name"] == "凡人修仙传"
    assert result.data[0]["author"] == "忘语"
