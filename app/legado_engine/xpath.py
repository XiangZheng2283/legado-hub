"""XPath extraction for Legado engine."""

from __future__ import annotations

import lxml.html


def extract_xpath(html: str | lxml.html.HtmlElement, xpath: str) -> list[lxml.html.HtmlElement]:
    """Extract elements using XPath."""
    if isinstance(html, str):
        doc = lxml.html.fromstring(html)
    else:
        doc = html
    try:
        return doc.xpath(xpath)
    except Exception:
        return []


def extract_xpath_text(html: str | lxml.html.HtmlElement, xpath: str, base_url: str = "") -> str:
    """Extract text using XPath, returning first non-empty result."""
    elements = extract_xpath(html, xpath)
    if not elements:
        return ""
    el = elements[0]
    if isinstance(el, str):
        return el.strip()
    text = el.text_content().strip() if el.text_content() else ""
    return text
