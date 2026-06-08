"""Tests for Legado CSS selector chain extraction."""

import pytest
from app.legado_engine.selectors import extract_list, extract_field, extract_fields_from_element


SAMPLE_HTML = """
<html><body>
<div class="list">
  <div class="item">
    <h3 class="title">Book One</h3>
    <span class="author">Author A</span>
    <a href="/book/1">link</a>
  </div>
  <div class="item">
    <h3 class="title">Book Two</h3>
    <span class="author">Author B</span>
    <a href="/book/2">link</a>
  </div>
</div>
</body></html>
"""


def test_extract_list():
    items = extract_list(SAMPLE_HTML, "class.list@class.item")
    assert len(items) == 2


def test_extract_field_text():
    text = extract_field(SAMPLE_HTML, "class.list@class.item.0@class.title@text")
    assert text == "Book One"


def test_extract_field_href():
    url = extract_field(SAMPLE_HTML, "class.list@class.item.0@tag.a@href", base_url="https://example.com")
    assert url == "https://example.com/book/1"


def test_extract_fields_from_element():
    import lxml.html
    doc = lxml.html.fromstring(SAMPLE_HTML)
    items = doc.cssselect(".item")
    fields, unsupported = extract_fields_from_element(items[0], {
        "name": "class.title@text",
        "author": "class.author@text",
    })
    assert fields["name"] == "Book One"
    assert fields["author"] == "Author A"
    assert not unsupported


def test_fallback_branch():
    html = '<html><body><div id="fallback">fallback text</div></body></html>'
    text = extract_field(html, "class.missing@text || id.fallback@text")
    assert text == "fallback text"


def test_unsupported_js():
    fields, unsupported = extract_fields_from_element(None, {"name": "@js:return 1"})
    assert "<js>" in unsupported or "@js:" in unsupported
