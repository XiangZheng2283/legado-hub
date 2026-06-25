from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.aggregate_processor import AggregateProcessor
from app.services.library_books import LibraryBooksService
from app.storage.db import initialize_database


SAMPLES: dict[str, dict] = {
    "夜无疆": {
        "name": "夜无疆",
        "author": "辰东",
        "bookUrl": "https://m.qidian.com/book/1040765595/",
        "startChapterIndex": 740,
    },
    "天人图谱": {
        "name": "天人图谱",
        "author": "误道者",
        "bookUrl": "https://m.qidian.com/book/1037676014/",
        "startChapterIndex": 2019,
    },
    "神农道君": {
        "name": "神农道君",
        "author": "神威校尉",
        "bookUrl": "https://m.qidian.com/book/1039640376/",
        "startChapterIndex": 698,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe live candidate completion on a real preview-only official book.")
    parser.add_argument("--book", choices=sorted(SAMPLES.keys()), default="夜无疆")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--chapter-limit", type=int, default=3)
    return parser.parse_args()


def build_group(sample: dict) -> dict:
    return {
        "candidateId": f"real-candidate:{sample['bookUrl']}",
        "name": sample["name"],
        "author": sample["author"],
        "items": [
            {
                "sourceId": "qidian_com_web",
                "sourceName": "起点中文网(Web)",
                "rawBookUrl": sample["bookUrl"],
                "bookUrl": sample["bookUrl"],
                "score": 200,
                "name": sample["name"],
                "author": sample["author"],
            }
        ],
    }


async def main() -> int:
    args = parse_args()
    sample = SAMPLES[args.book]
    tmpdir = tempfile.mkdtemp(prefix="real_candidate_completion_")
    db_path = Path(tmpdir) / "app.db"
    initialize_database(db_path)

    service = LibraryBooksService(db_path=db_path)
    created = await service.create_or_get_shared_book(
        build_group(sample),
        added_by_user_id="tester",
        start_chapter_index=int(sample["startChapterIndex"]),
        auto_archive_on_complete=False,
    )
    book = created["book"]
    payload = created["payload"]

    processor = AggregateProcessor(db_path=db_path, ai_service=None)
    enqueue = processor.enqueue_book(book["aggregateBookId"], payload)
    rounds = []
    for _ in range(max(1, args.rounds)):
        rounds.append(await processor.run_book_task(book["aggregateBookId"], chapter_limit=max(1, args.chapter_limit)))

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT chapter_index, title, status, preview_only, fallback_source_id, source_alignment_json
            FROM aggregate_chapter_tasks
            WHERE aggregate_book_id = ? AND chapter_index >= ?
            ORDER BY chapter_index ASC
            LIMIT 6
            """,
            (book["aggregateBookId"], int(sample["startChapterIndex"])),
        ).fetchall()
        snapshot_rows = conn.execute(
            """
            SELECT chapter_index, source_id, title, length(clean_content)
            FROM aggregate_source_snapshots
            WHERE aggregate_book_id = ? AND chapter_index >= ?
            ORDER BY chapter_index ASC, source_id ASC
            LIMIT 30
            """,
            (book["aggregateBookId"], int(sample["startChapterIndex"])),
        ).fetchall()

    chapters = []
    candidate_completed = 0
    for row in rows:
        alignment = json.loads(row[5] or "{}")
        item = {
            "chapterIndex": row[0],
            "title": row[1],
            "status": row[2],
            "previewOnly": bool(row[3]),
            "fallbackSourceId": row[4] or "",
            "alignmentReason": alignment.get("alignmentReason", ""),
            "alignmentPassed": alignment.get("alignmentPassed", False),
        }
        if item["fallbackSourceId"] and item["fallbackSourceId"] != "qidian_com_web" and not item["previewOnly"]:
            candidate_completed += 1
        chapters.append(item)

    output = {
        "sample": sample,
        "enqueue": enqueue,
        "rounds": rounds,
        "chapters": chapters,
        "snapshotSample": [
            {
                "chapterIndex": row[0],
                "sourceId": row[1],
                "title": row[2],
                "contentLength": row[3],
            }
            for row in snapshot_rows
        ],
        "candidateCompletedCount": candidate_completed,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
