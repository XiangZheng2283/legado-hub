from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.catalog import Catalog


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe official-source books for likely preview-only chapter signals.")
    parser.add_argument("--keyword", default="宿命之环", help="Search keyword")
    parser.add_argument("--source-id", default="qidian_com_web", help="Official source id")
    parser.add_argument("--books", type=int, default=3, help="How many search results to inspect")
    parser.add_argument("--tail-chapters", type=int, default=5, help="How many tail chapters to probe per book")
    return parser.parse_args()


def chapter_probe_payload(chapter: dict, result: dict) -> dict:
    extra = result.get("extra") if isinstance(result.get("extra"), dict) else {}
    debug = result.get("debug") if isinstance(result.get("debug"), dict) else {}
    return {
        "chapterTitle": chapter.get("title", ""),
        "chapterUrl": result.get("rawChapterUrl", "") or result.get("chapterUrl", ""),
        "contentLength": len(result.get("content", "") or ""),
        "isPaid": bool(result.get("isPaid", False) or extra.get("isPaid", False)),
        "previewOnly": bool(
            result.get("previewOnly", False)
            or extra.get("previewOnly", False)
            or extra.get("isLocked", False)
            or debug.get("previewOnly", False)
        ),
        "sourceWordCount": (
            result.get("sourceWordCount")
            or result.get("wordCount")
            or extra.get("actualWords")
            or extra.get("wordCount")
            or 0
        ),
    }


async def main() -> int:
    args = parse_args()
    catalog = Catalog()
    search = await catalog.search(args.keyword, 1, source_ids=[args.source_id])
    items = [dict(item) for item in search.get("items", []) if isinstance(item, dict)]
    items = [item for item in items if item.get("sourceId") == args.source_id][: max(1, args.books)]

    output = {
        "keyword": args.keyword,
        "sourceId": args.source_id,
        "searchCount": len(items),
        "books": [],
    }

    for item in items:
        book_id = item.get("bookId", "")
        if not book_id:
            continue
        detail = await catalog.book_detail(book_id)
        detail_data = detail.get("data") if isinstance(detail, dict) else {}
        toc = await catalog.toc(book_id)
        chapters = [dict(ch) for ch in toc.get("chapters", []) if isinstance(ch, dict)]
        tail = chapters[-max(1, args.tail_chapters) :] if chapters else []
        chapter_probes = []
        for chapter in tail:
            chapter_id = chapter.get("chapterId", "")
            if not chapter_id:
                continue
            try:
                chapter_result = await catalog.chapter(chapter_id)
                chapter_probes.append(chapter_probe_payload(chapter, chapter_result))
            except Exception as exc:
                chapter_probes.append(
                    {
                        "chapterTitle": chapter.get("title", ""),
                        "error": str(exc),
                    }
                )
        output["books"].append(
            {
                "name": detail_data.get("name", "") if isinstance(detail_data, dict) else item.get("name", ""),
                "author": detail_data.get("author", "") if isinstance(detail_data, dict) else item.get("author", ""),
                "bookId": book_id,
                "kind": detail_data.get("kind", "") if isinstance(detail_data, dict) else "",
                "lastChapter": detail_data.get("lastChapter", "") if isinstance(detail_data, dict) else item.get("lastChapter", ""),
                "chapterCount": len(chapters),
                "tailProbes": chapter_probes,
            }
        )

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
