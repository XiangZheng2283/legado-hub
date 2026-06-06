#!/usr/bin/env python3
"""Inspect a Legado source JSON file and print a compact module summary."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


MODULE_KEYS = [
    "searchUrl",
    "ruleSearch",
    "exploreUrl",
    "ruleExplore",
    "ruleBookInfo",
    "ruleToc",
    "ruleContent",
    "jsLib",
]


def describe_value(value: Any) -> str:
    if value is None:
        return "missing"
    if isinstance(value, dict):
        return f"dict({len(value)}): {', '.join(value.keys())}"
    if isinstance(value, list):
        return f"list({len(value)})"
    text = str(value).replace("\n", "\\n")
    if len(text) > 180:
        text = text[:177] + "..."
    return f"{type(value).__name__}: {text}"


def load_json(path: Path) -> Any:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return json.loads(path.read_text(encoding=encoding))
        except UnicodeDecodeError:
            continue
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: inspect_legado_source.py <source.json>", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    data = load_json(path)
    sources = data if isinstance(data, list) else [data]

    print(f"path: {path}")
    print(f"top_type: {type(data).__name__}")
    print(f"source_count: {len(sources)}")

    for index, source in enumerate(sources[:20]):
        print(f"\n[{index}]")
        if not isinstance(source, dict):
            print(f"type: {type(source).__name__}")
            continue
        print(f"name: {source.get('bookSourceName')}")
        print(f"url: {source.get('bookSourceUrl')}")
        print(f"group: {source.get('bookSourceGroup')}")
        print(f"type: {source.get('bookSourceType')}")
        for key in MODULE_KEYS:
            print(f"{key}: {describe_value(source.get(key))}")

    if len(sources) > 20:
        print(f"\n... skipped {len(sources) - 20} sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
