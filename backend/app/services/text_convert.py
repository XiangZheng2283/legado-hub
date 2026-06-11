"""Text conversion helpers shared by source plugin runtime."""

from __future__ import annotations

from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def _opencc_converter():
    try:
        from opencc import OpenCC
    except Exception:
        return None
    return OpenCC("tw2sp")


@lru_cache(maxsize=1)
def _opencc_traditional_converter():
    try:
        from opencc import OpenCC
    except Exception:
        return None
    return OpenCC("s2twp")


def to_simplified(value: Any) -> Any:
    """Convert Traditional Chinese text to Simplified Chinese.

    Non-string values are returned unchanged. The fallback keeps the runtime
    usable when the optional converter is unavailable, while requirements.txt
    pins the real converter for normal installs.
    """
    if not isinstance(value, str) or not value:
        return value
    converter = _opencc_converter()
    if converter is None:
        return value
    converted = converter.convert(value)
    return _normalize_simplified_residue(converted)


def to_traditional(value: Any) -> Any:
    """Convert Simplified Chinese text to Traditional Chinese for TW sources."""
    if not isinstance(value, str) or not value:
        return value
    converter = _opencc_traditional_converter()
    if converter is None:
        return value
    return converter.convert(value)


def _normalize_simplified_residue(value: str) -> str:
    """Clean common Taiwan wording that OpenCC keeps ambiguous."""
    value = value.replace("妳", "你").replace("祢", "你")
    value = value.replace("臺", "台")
    value = value.replace("著地", "着地")
    import re

    return re.sub(r"著(?!名|作|述|书|称|者|录|于|手)", "着", value)


