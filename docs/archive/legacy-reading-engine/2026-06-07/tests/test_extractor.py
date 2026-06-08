"""Tests for Legado rule extractor."""

from app.engine.extractor import extract_field, extract_list


SAMPLE_HTML = """
<html><body>
<div class="list">
    <li class="item"><a href="/book/1">Book One</a><span class="author">A1</span></li>
    <li class="item"><a href="/book/2">Book Two</a><span class="author">A2</span></li>
</div>
<div id="info"><h1>Title</h1><p class="intro">Hello world</p></div>
</body></html>
"""


def test_extract_field_class_text() -> None:
    val = extract_field(SAMPLE_HTML, "class.intro@text")
    assert val == "Hello world"


def test_extract_field_id_text() -> None:
    val = extract_field(SAMPLE_HTML, "id.info@tag.h1@text")
    assert val == "Title"


def test_extract_field_href() -> None:
    val = extract_field(SAMPLE_HTML, "class.item@tag.a@href")
    assert val == "/book/1"


def test_extract_list() -> None:
    els = extract_list(SAMPLE_HTML, "class.list@tag.li")
    assert len(els) == 2


def test_extract_field_with_replace_regex() -> None:
    val = extract_field(SAMPLE_HTML, "class.intro@text##world##universe")
    assert val == "Hello universe"
