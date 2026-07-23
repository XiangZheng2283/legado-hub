"""Strip author-say text that book sources embed into chapter bodies.

When the official review feed already exposes ``authorReviews`` (作家说),
mirrors often append the same copy after the chapter text. That overlaps the
reading client's dedicated 作家说 chrome. This module removes matching tails
from the body so only the review surface keeps the author note.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# Ignore tiny fragments — too easy to false-positive on common short phrases.
_MIN_AUTHOR_CHARS = 16
_HEADER_RE = re.compile(
    r"(?m)^[ \t]*(?:【?\s*作家说\s*】?|作者有话说|作者的话|作者说)[ \t]*[:：]?[ \t]*$"
)
_INLINE_FN_RE = re.compile(r"\[fn=\d+\]")
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def extract_author_say_texts(reviews: Any) -> list[str]:
    """Collect non-empty author-say bodies from a reviews payload."""
    if not isinstance(reviews, dict):
        return []
    items = reviews.get("authorReviews")
    if not isinstance(items, list):
        return []
    texts: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = item.get("content") or item.get("Content") or ""
        cleaned = _clean_review_text(str(raw))
        if len(cleaned) < _MIN_AUTHOR_CHARS:
            continue
        key = _normalize_match_key(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        texts.append(cleaned)
    return texts


def strip_overlapping_author_say(content: str, author_texts: Iterable[str]) -> str:
    """Remove author-say copy from chapter content when it overlaps review text.

    Prefer matches near the end of the chapter (where mirrors usually append
    作家说). Also drop a preceding 作家说/作者有话说 header line when present.
    """
    if not content or not content.strip():
        return content
    texts = [t for t in author_texts if isinstance(t, str) and t.strip()]
    if not texts:
        return content

    result = content
    for text in sorted(texts, key=len, reverse=True):
        result = _strip_one_author_text(result, text)
    return _trim_trailing_blank_lines(result)


def _clean_review_text(value: str) -> str:
    text = _HTML_TAG_RE.sub(" ", value or "")
    text = _INLINE_FN_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS_RE.sub(" ", text).strip()
    return text


def _normalize_match_key(value: str) -> str:
    return _WS_RE.sub("", value or "")


def _collapse_with_map(value: str) -> tuple[str, list[int]]:
    """Collapse whitespace; map each collapsed index back to original index."""
    collapsed: list[str] = []
    index_map: list[int] = []
    prev_ws = False
    for idx, ch in enumerate(value):
        if ch.isspace():
            if collapsed and not prev_ws:
                collapsed.append(" ")
                index_map.append(idx)
            prev_ws = True
            continue
        prev_ws = False
        collapsed.append(ch)
        index_map.append(idx)
    return "".join(collapsed), index_map


def _strip_one_author_text(content: str, author_text: str) -> str:
    needle = _clean_review_text(author_text)
    if len(needle) < _MIN_AUTHOR_CHARS:
        return content

    span = _find_overlap_span(content, needle)
    if span is None:
        return content
    start, end = span

    # Expand upward over blank lines + a 作家说 header.
    header_start = _expand_leading_header(content, start)
    cleaned = (content[:header_start] + content[end:]).rstrip()
    # Avoid wiping a long chapter on a bad match. Short samples may legitimately
    # shrink a lot when the author note is a large share of the string.
    if content and len(content) >= 200 and len(cleaned) < int(len(content) * 0.35):
        return content
    if content and len(cleaned) < 8:
        return content
    return cleaned


def _find_overlap_span(content: str, needle: str) -> tuple[int, int] | None:
    """Locate author text inside content; prefer the last occurrence."""
    collapsed, index_map = _collapse_with_map(content)
    needle_collapsed, _ = _collapse_with_map(needle)
    if not needle_collapsed or not index_map:
        return None

    last: tuple[int, int] | None = None
    pos = collapsed.find(needle_collapsed)
    while pos >= 0:
        orig_start = index_map[pos]
        end_collapsed = pos + len(needle_collapsed) - 1
        orig_end = index_map[end_collapsed] + 1
        while orig_end < len(content) and content[orig_end] in " \t":
            orig_end += 1
        if orig_end < len(content) and content[orig_end] == "\n":
            orig_end += 1
        last = (orig_start, orig_end)
        pos = collapsed.find(needle_collapsed, pos + 1)

    if last is not None:
        start, end = last
        # Accept trailing appends; drop only clearly-early short coincidences.
        in_trailing = start >= len(content) * 0.4 or end >= len(content) * 0.75
        if in_trailing or len(needle_collapsed) >= 32:
            return start, end

    # Fallback: distinctive head near chapter end (partial mirror append).
    if len(needle_collapsed) >= 32:
        head = needle_collapsed[: min(48, len(needle_collapsed))]
        pos = collapsed.rfind(head)
        if pos >= 0 and pos >= int(len(collapsed) * 0.4):
            return index_map[pos], len(content)
    return None


def _expand_leading_header(content: str, match_start: int) -> int:
    """If a 作家说 header sits just above the match, include it in the cut."""
    if match_start <= 0:
        return 0
    cut = match_start
    while cut > 0 and content[cut - 1] in " \t":
        cut -= 1
    while cut > 0 and content[cut - 1] == "\n":
        cut -= 1
        while cut > 0 and content[cut - 1] in " \t":
            cut -= 1

    line_end = cut
    line_start = content.rfind("\n", 0, line_end)
    line_start = 0 if line_start < 0 else line_start + 1
    prev_line = content[line_start:line_end].strip()
    if _HEADER_RE.match(prev_line) or prev_line in {
        "作家说",
        "【作家说】",
        "作者有话说",
        "作者的话",
        "作者说",
    }:
        header_start = line_start
        while header_start > 0 and content[header_start - 1] == "\n":
            header_start -= 1
            while header_start > 0 and content[header_start - 1] in " \t":
                header_start -= 1
        return header_start
    return cut if cut < match_start else match_start


def _trim_trailing_blank_lines(content: str) -> str:
    text = (content or "").replace("\r\n", "\n").replace("\r", "\n").rstrip()
    if content.endswith("\n") and text:
        return text + "\n"
    return text
