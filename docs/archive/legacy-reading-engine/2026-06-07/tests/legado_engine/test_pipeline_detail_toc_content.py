"""Tests for detail, toc, and content pipelines with mocked HTTP."""

import asyncio
from unittest.mock import AsyncMock

from app.legado_engine.models import LegadoSource
from app.legado_engine.analyzer import LegadoAnalyzer
from app.legado_engine.http_runtime import HttpRuntime


DETAIL_HTML = """
<html><body>
<h1 class="title">凡人修仙传</h1>
<p class="author">忘语</p>
<div class="intro">一个凡人的修仙故事</div>
<a class="toc-link" href="/toc/1">目录</a>
</body></html>
"""

TOC_HTML = """
<html><body>
<ul class="chapters">
  <li><a href="/chapter/1">第一章</a></li>
  <li><a href="/chapter/2">第二章</a></li>
</ul>
</body></html>
"""

CONTENT_HTML = """
<html><body>
<h1 class="chapter-title">第一章</h1>
<div class="content">这是第一章的内容。</div>
</body></html>
"""


def test_detail_pipeline_mock(monkeypatch):
    http = HttpRuntime()
    mock_fetch = AsyncMock(return_value=type('Result', (), {
        'text': DETAIL_HTML,
        'final_url': 'https://example.com/book/1',
        'proxy_used': False,
        'attempts': 1,
        'direct_error': '',
        'proxy_error': '',
        'success': True,
    })())
    monkeypatch.setattr(http, 'fetch_with_proxy', mock_fetch)

    analyzer = LegadoAnalyzer(http=http)
    source = LegadoSource(
        source_id="test",
        source_name="Test",
        source_url="https://example.com",
        rule_book_info={
            "name": "class.title@text",
            "author": "class.author@text",
            "intro": "class.intro@text",
            "tocUrl": "class.toc-link@href",
        },
        raw={},
    )
    result = asyncio.run(analyzer.book_detail(source, "https://example.com/book/1"))
    assert result.success is True
    assert result.data["name"] == "凡人修仙传"
    assert result.data["author"] == "忘语"


def test_toc_pipeline_mock(monkeypatch):
    http = HttpRuntime()
    mock_fetch = AsyncMock(return_value=type('Result', (), {
        'text': TOC_HTML,
        'final_url': 'https://example.com/toc/1',
        'proxy_used': False,
        'attempts': 1,
        'direct_error': '',
        'proxy_error': '',
        'success': True,
    })())
    monkeypatch.setattr(http, 'fetch_with_proxy', mock_fetch)

    analyzer = LegadoAnalyzer(http=http)
    source = LegadoSource(
        source_id="test",
        source_name="Test",
        source_url="https://example.com",
        rule_toc={
            "chapterList": "class.chapters@tag.li",
            "chapterName": "tag.a@text",
            "chapterUrl": "tag.a@href",
        },
        raw={},
    )
    result = asyncio.run(analyzer.toc(source, "https://example.com/toc/1"))
    assert result.success is True
    assert len(result.data) == 2
    assert result.data[0]["title"] == "第一章"


def test_content_pipeline_mock(monkeypatch):
    http = HttpRuntime()
    mock_fetch = AsyncMock(return_value=type('Result', (), {
        'text': CONTENT_HTML,
        'final_url': 'https://example.com/chapter/1',
        'proxy_used': False,
        'attempts': 1,
        'direct_error': '',
        'proxy_error': '',
        'success': True,
    })())
    monkeypatch.setattr(http, 'fetch_with_proxy', mock_fetch)

    analyzer = LegadoAnalyzer(http=http)
    source = LegadoSource(
        source_id="test",
        source_name="Test",
        source_url="https://example.com",
        rule_content={
            "content": "class.content@text",
            "title": "class.chapter-title@text",
        },
        raw={},
    )
    result = asyncio.run(analyzer.content(source, "https://example.com/chapter/1"))
    assert result.success is True
    assert "第一章的内容" in result.data["content"]
