"""Tests for XPath extraction."""

from app.legado_engine.xpath import extract_xpath, extract_xpath_text


SAMPLE_HTML = """
<html><body>
<div class="list">
  <div class="item"><h3>Book One</h3></div>
  <div class="item"><h3>Book Two</h3></div>
</div>
</body></html>
"""


def test_extract_xpath_elements():
    elements = extract_xpath(SAMPLE_HTML, "//div[@class='item']")
    assert len(elements) == 2


def test_extract_xpath_text():
    text = extract_xpath_text(SAMPLE_HTML, "//div[@class='item'][1]/h3")
    assert text == "Book One"
