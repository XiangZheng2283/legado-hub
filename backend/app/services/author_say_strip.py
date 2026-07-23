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
# Deleted tail (normalized 字数) must not exceed this ratio of author-say length.
_MAX_DELETE_LEN_RATIO = 1.20
# Head token length used when climbing from the chapter end.
_HEAD_TOKEN_MIN = 6
_HEAD_TOKEN_MAX = 16
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

    Strategy:
    1) Exact match (whitespace-collapsed, ASCII case-insensitive).
    2) Chapter-end 字数 climb: take last N chars (= author 字数), look for the
       author-say **head token**; if missing, grow the window upward until
       120% of N; delete from head token to end when found.
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
    """Collapse whitespace and fold ASCII letters for case-insensitive compare."""
    return _WS_RE.sub("", value or "").casefold()


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
        span = _find_end_length_head_climb_span(content, needle)
    if span is None:
        return content
    start, end = span

    header_start = _expand_leading_header(content, start)
    cleaned = (content[:header_start] + content[end:]).rstrip()

    # Safety: do not delete almost an entire long chapter on a bad match.
    if content and len(content) >= 200 and len(cleaned) < int(len(content) * 0.35):
        return content
    if not cleaned.strip():
        return content
    return cleaned


def _find_overlap_span(content: str, needle: str) -> tuple[int, int] | None:
    """Locate author text inside content; prefer the last occurrence.

    Comparison is ASCII-case-insensitive (orz == ORZ).
    """
    collapsed, index_map = _collapse_with_map(content)
    needle_collapsed, _ = _collapse_with_map(needle)
    if not needle_collapsed or not index_map:
        return None

    collapsed_cf = collapsed.casefold()
    needle_cf = needle_collapsed.casefold()

    last: tuple[int, int] | None = None
    pos = collapsed_cf.find(needle_cf)
    while pos >= 0:
        orig_start = index_map[pos]
        end_collapsed = pos + len(needle_cf) - 1
        orig_end = index_map[end_collapsed] + 1
        while orig_end < len(content) and content[orig_end] in " \t":
            orig_end += 1
        if orig_end < len(content) and content[orig_end] == "\n":
            orig_end += 1
        last = (orig_start, orig_end)
        pos = collapsed_cf.find(needle_cf, pos + 1)

    if last is not None:
        start, end = last
        removed_key = len(_normalize_match_key(content[start:end]))
        author_key = len(needle_cf)
        # Exact hit still respects 120% 字数 ceiling after header expand is applied later.
        if removed_key > int(author_key * _MAX_DELETE_LEN_RATIO) + 2:
            # Unlikely for exact match; keep if trailing.
            pass
        in_trailing = start >= len(content) * 0.4 or end >= len(content) * 0.75
        if in_trailing or author_key >= 32:
            return start, end

    if len(needle_cf) >= 32:
        head = needle_cf[: min(48, len(needle_cf))]
        pos = collapsed_cf.rfind(head)
        if pos >= 0 and pos >= int(len(collapsed_cf) * 0.4):
            start = index_map[pos]
            removed_key = len(_normalize_match_key(content[start:]))
            if removed_key <= int(len(needle_cf) * _MAX_DELETE_LEN_RATIO):
                return start, len(content)
    return None


def _author_head_token(needle_key: str) -> str:
    """Leading 头词汇 from normalized author-say text."""
    if len(needle_key) <= _HEAD_TOKEN_MIN:
        return needle_key
    # Prefer a stable prefix; avoid ending mid-surrogate (BMP Chinese is fine).
    size = min(_HEAD_TOKEN_MAX, max(_HEAD_TOKEN_MIN, len(needle_key) // 4))
    size = min(size, len(needle_key))
    return needle_key[:size]


def _find_end_length_head_climb_span(content: str, needle: str) -> tuple[int, int] | None:
    """章末字数 + 头词汇向上爬：

    1. From chapter end, take the same 字数 as 作家说 (N).
    2. Search for the author-say head token inside that tail.
    3. If missing, grow the window upward one char at a time.
    4. Stop when window > 120% of N (total delete 字数 cap).
    5. On hit: delete from head token to end of chapter.
    """
    needle_key = _normalize_match_key(needle)
    content_key = _normalize_match_key(content)
    if len(needle_key) < _MIN_AUTHOR_CHARS or not content_key:
        return None

    n = len(needle_key)
    head = _author_head_token(needle_key)
    if len(head) < 2:
        return None

    max_window = min(len(content_key), int(n * _MAX_DELETE_LEN_RATIO))
    if max_window < n:
        # Chapter shorter than author note — only try full content if length ok.
        max_window = len(content_key)

    # Climb: window size from N .. floor(1.2*N)
    start_window = min(n, len(content_key))
    for win in range(start_window, max_window + 1):
        tail_start_key = len(content_key) - win
        tail = content_key[tail_start_key:]
        # Prefer the last head occurrence inside this tail (closest to true start).
        rel = tail.rfind(head)
        if rel < 0:
            continue
        # Absolute key offset of head inside full content_key.
        head_key_offset = tail_start_key + rel
        # Deleted key length from head to end.
        deleted_key_len = len(content_key) - head_key_offset
        if deleted_key_len > int(n * _MAX_DELETE_LEN_RATIO):
            continue
        # Deleted region should not be much shorter than author (avoid tiny head hits).
        if deleted_key_len < int(n * 0.85) and win < n:
            continue

        cut = _original_index_for_key_offset(content, head_key_offset)
        if cut is None:
            continue
        # Optional: include a short run of whitespace immediately before head.
        while cut > 0 and content[cut - 1] in " \t":
            cut -= 1

        removed_key_len = len(_normalize_match_key(content[cut:]))
        if removed_key_len > int(n * _MAX_DELETE_LEN_RATIO):
            continue
        if removed_key_len < max(_MIN_AUTHOR_CHARS, int(n * 0.75)):
            continue
        return cut, len(content)

    return None


def _original_index_for_key_offset(content: str, key_offset: int) -> int | None:
    """Map an index into normalize_match_key(content) back to content index."""
    if key_offset <= 0:
        i = 0
        while i < len(content) and content[i].isspace():
            i += 1
        return i
    count = 0
    for i, ch in enumerate(content):
        if ch.isspace():
            continue
        if count == key_offset:
            return i
        count += 1
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
