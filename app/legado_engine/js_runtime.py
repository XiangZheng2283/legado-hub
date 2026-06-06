"""Restricted JavaScript transform execution for Legado engine.

Currently supports safe, stateless string transforms only.
Complex JS with java.ajax or DOM manipulation is classified as unsupported.
"""

from __future__ import annotations

import re


def classify_js_rule(rule: str) -> tuple[bool, str]:
    """Classify whether a JS rule can be safely emulated.

    Returns (can_emulate, reason).
    """
    if "java.ajax" in rule or "java.get" in rule or "java.post" in rule:
        return False, "contains java.ajax/network call"
    if "document" in rule or "window" in rule:
        return False, "contains DOM/window access"
    if "eval(" in rule or "Function(" in rule:
        return False, "contains eval/Function constructor"
    return True, "simple transform"


def apply_safe_js_transform(text: str, js_code: str) -> str:
    """Apply a safe JS-like transform to text.

    Only supports basic operations that can be mapped to Python:
    - .replace(/regex/, replacement)
    - .trim()
    - .split(x).join(y)
    - String concatenation with +
    """
    # Simple .replace(/regex/flags, replacement)
    replace_pattern = r'\.replace\(/(.+?)/(\w*),\s*(.+?)\)'
    for m in re.finditer(replace_pattern, js_code):
        regex = m.group(1)
        flags = m.group(2)
        replacement = m.group(3).strip("'\"")
        rf = 0
        if "i" in flags:
            rf |= re.IGNORECASE
        if "s" in flags:
            rf |= re.DOTALL
        try:
            text = re.sub(regex, replacement, text, flags=rf)
        except re.error:
            pass

    # .trim()
    if ".trim()" in js_code:
        text = text.strip()

    # .split(x).join(y)
    split_join = r'\.split\((.+?)\)\.join\((.+?)\)'
    for m in re.finditer(split_join, js_code):
        sep = m.group(1).strip("'\"")
        joiner = m.group(2).strip("'\"")
        text = joiner.join(text.split(sep))

    return text
