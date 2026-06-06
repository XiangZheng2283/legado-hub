"""Regex extraction for Legado engine."""

from __future__ import annotations

import re


def extract_regex(text: str, pattern: str, group: int = 1) -> str:
    """Extract a value using regex."""
    if not text or not pattern:
        return ""
    try:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            return m.group(group) if group <= len(m.groups()) else m.group(0)
    except re.error:
        pass
    return ""


def extract_regex_all(text: str, pattern: str) -> list[str]:
    """Extract all matches using regex."""
    if not text or not pattern:
        return []
    try:
        return re.findall(pattern, text, re.DOTALL)
    except re.error:
        return []
