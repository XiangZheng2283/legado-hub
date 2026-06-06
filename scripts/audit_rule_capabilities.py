"""Scan local Legado source rules and summarize engine-relevant syntax markers."""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default="data/sources/raw/by-site/legado")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    root = Path(args.dir)
    files = sorted(root.glob("*.json"))
    if args.limit:
        files = files[: args.limit]

    counts: collections.Counter[str] = collections.Counter()
    total_objects = 0

    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            counts["file_error"] += 1
            continue
        objects = data if isinstance(data, list) else [data]
        for raw in objects:
            if not isinstance(raw, dict):
                counts["non_object"] += 1
                continue
            total_objects += 1
            text = json.dumps(raw, ensure_ascii=False)
            if "<js>" in text:
                counts["js_block"] += 1
            if "@js:" in text:
                counts["js_inline"] += 1
            if "xpath:" in text or '"//' in text:
                counts["xpath_marker"] += 1
            if "$." in text:
                counts["jsonpath_marker"] += 1
            if "regex:" in text or "##" in text:
                counts["regex_or_replace"] += 1
            if "nextTocUrl" in text:
                counts["next_toc"] += 1
            if "nextContentUrl" in text:
                counts["next_content"] += 1
            if raw.get("enabledCookieJar"):
                counts["cookie_jar"] += 1
            if raw.get("loginUrl"):
                counts["login"] += 1
            if raw.get("webView"):
                counts["webview"] += 1

    print(json.dumps({
        "files": len(files),
        "objects": total_objects,
        "markers": dict(counts),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
