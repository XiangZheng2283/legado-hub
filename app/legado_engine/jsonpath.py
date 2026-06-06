"""JsonPath extraction for Legado engine."""

from __future__ import annotations

import re


def extract_jsonpath(data: dict | list, path: str) -> list:
    """Extract values using JsonPath-like syntax.

    Supports: $.key, $.key.nested, $.array[*], $.array[0], $.array[*].field
    """
    if not path.startswith("$"):
        return []
    current_items = [data]
    segments = _tokenize(path)
    for seg in segments:
        if not seg:
            continue
        next_items = []
        for current in current_items:
            next_items.extend(_step(current, seg))
        current_items = [item for item in next_items if item is not None]
        if not current_items:
            return []
    return current_items


def _tokenize(path: str) -> list[str]:
    body = path[1:]
    tokens: list[str] = []
    for part in body.split("."):
        if not part:
            continue
        pos = 0
        m = re.match(r"^([^\[]+)", part)
        if m:
            tokens.append(m.group(1))
            pos = m.end()
        for idx in re.findall(r"\[([^\]]+)\]", part[pos:]):
            tokens.append(idx)
    return tokens


def _step(current, seg: str) -> list:
    if isinstance(current, dict):
        if seg == "*":
            return list(current.values())
        return [current.get(seg)]
    if isinstance(current, list):
        if seg == "*":
            return list(current)
        if seg.startswith("'") or seg.startswith('"'):
            key = seg.strip("'\"")
            return [item.get(key) for item in current if isinstance(item, dict)]
        try:
            idx = int(seg)
            return [current[idx]] if 0 <= idx < len(current) else []
        except ValueError:
            return [item.get(seg) for item in current if isinstance(item, dict)]
    return []


def extract_jsonpath_text(data: dict | list, path: str) -> str:
    """Extract first value as string."""
    results = extract_jsonpath(data, path)
    if not results:
        return ""
    val = results[0]
    if isinstance(val, (dict, list)):
        return __import__("json").dumps(val, ensure_ascii=False)
    return str(val)
