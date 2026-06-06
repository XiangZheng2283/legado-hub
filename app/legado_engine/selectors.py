"""CSS/JSoup-like selector chains with index and exclusion support."""

from __future__ import annotations

import re
from urllib.parse import urljoin

import lxml.html


def _parse_segment(segment: str) -> tuple[str, int | None]:
    """Parse a Legado selector segment into (css_selector, index)."""
    m = re.match(r'^(class|id|tag)\.(.+?)(?:\.(\d+))?$', segment)
    if m:
        prefix, name, idx = m.group(1), m.group(2), m.group(3)
        index = int(idx) if idx is not None else None
        if prefix == "class":
            return f".{name}", index
        elif prefix == "id":
            return f"#{name}", index
        else:
            return name, index
    return segment, None


def _resolve_index(elements: list, idx: int | None, exclude: bool = False) -> list:
    if idx is None:
        return elements
    if exclude:
        return [el for i, el in enumerate(elements) if i != idx]
    if idx < 0:
        real_idx = len(elements) + idx
    else:
        real_idx = idx
    if 0 <= real_idx < len(elements):
        return [elements[real_idx]]
    return []


def apply_selector_chain(doc: lxml.html.HtmlElement, segments: list[str]) -> list[lxml.html.HtmlElement]:
    """Apply a chain of CSS selector segments."""
    current_elements = [doc]
    for seg in segments:
        exclude = False
        if seg.endswith("!0"):
            seg = seg[:-2]
            exclude = True
            idx = 0
        elif seg.endswith("!1"):
            seg = seg[:-2]
            exclude = True
            idx = 1
        else:
            sel, idx = _parse_segment(seg)
        next_elements = []
        for el in current_elements:
            found = el.cssselect(sel)
            resolved = _resolve_index(found, idx, exclude)
            next_elements.extend(resolved)
        current_elements = next_elements
        if not current_elements:
            break
    return current_elements


def extract_list(html: str | lxml.html.HtmlElement, rule: str, base_url: str = "") -> list[lxml.html.HtmlElement]:
    """Extract a list of elements using a Legado rule (for bookList/chapterList)."""
    if isinstance(html, str):
        doc = lxml.html.fromstring(html)
    else:
        doc = html
    branches = [b.strip() for b in rule.split("||")]
    for branch in branches:
        selector_segments = [s.strip() for s in branch.split("@")]
        if not selector_segments:
            continue
        result = apply_selector_chain(doc, selector_segments)
        if result:
            return result
    return []


def _extract_value(element, method: str, base_url: str = "") -> str:
    if method == "text":
        return element.text_content().strip() if element.text_content() else ""
    elif method == "textNodes":
        return element.text_content().strip() if element.text_content() else ""
    elif method == "html":
        return lxml.html.tostring(element, encoding="unicode").strip()
    elif method == "href":
        val = element.get("href", "")
        return urljoin(base_url, val) if val else ""
    elif method == "src":
        val = element.get("src", "")
        return urljoin(base_url, val) if val else ""
    elif method == "title":
        return element.get("title", "")
    else:
        val = element.get(method, "")
        return urljoin(base_url, val) if val and method in ("href", "src") else val


def _apply_replace_regex(text: str, pattern: str) -> str:
    if not pattern:
        return text
    parts = pattern.split("##")
    if len(parts) >= 2:
        regex = parts[1]
        replacement = parts[2] if len(parts) > 2 else ""
        try:
            return __import__("re").sub(regex, replacement, text, flags=__import__("re").DOTALL)
        except __import__("re").error:
            return text
    return text


def extract_field(html: str | lxml.html.HtmlElement, rule: str, base_url: str = "") -> str:
    """Extract a single string value using a Legado rule."""
    if isinstance(html, str):
        doc = lxml.html.fromstring(html)
    else:
        doc = html

    branches = [b.strip() for b in rule.split("||")]
    for branch in branches:
        replace_regex = ""
        if "##" in branch:
            parts = branch.split("##", 1)
            branch = parts[0]
            replace_regex = "##" + parts[1]

        segments = branch.split("@")
        extract_method = segments[-1].strip()
        selector_segments = [s.strip() for s in segments[:-1]]

        if not selector_segments:
            continue

        current_elements = apply_selector_chain(doc, selector_segments)
        if not current_elements:
            continue

        value = _extract_value(current_elements[0], extract_method, base_url)
        if replace_regex:
            value = _apply_replace_regex(value, replace_regex)
        if value:
            return value

    return ""


def extract_fields_from_element(element: lxml.html.HtmlElement, field_rules: dict[str, str], base_url: str = "") -> tuple[dict[str, str], list[str]]:
    """Extract multiple fields from a single element using field rules.

    Returns (fields_dict, unsupported_syntax_list).
    """
    result = {}
    unsupported = []
    for key, rule in field_rules.items():
        if not rule or not isinstance(rule, str):
            continue
        issues = _check_unsupported(rule)
        if issues:
            unsupported.extend(issues)
            continue
        try:
            val = extract_field(element, rule, base_url)
            result[key] = val
        except Exception:
            result[key] = ""
    return result, list(set(unsupported))


def _check_unsupported(rule: str) -> list[str]:
    issues = []
    if "<js>" in rule:
        issues.append("<js> block")
    if "@js:" in rule:
        issues.append("@js:")
    return issues
