from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.library_books import LibraryBooksService
from app.storage.db import initialize_database


GROUP = {
    "candidateId": "book-status-check",
    "name": "宿命之环",
    "author": "爱潜水的乌贼",
    "items": [
        {
            "sourceId": "qidian_com_web",
            "sourceName": "起点中文网(Web)",
            "rawBookUrl": "https://m.qidian.com/book/1036370336/",
            "bookUrl": "https://m.qidian.com/book/1036370336/",
            "score": 221,
            "name": "宿命之环",
            "author": "爱潜水的乌贼",
        }
    ],
}


async def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="subscription_book_status_")
    db_path = Path(tmpdir) / "app.db"
    initialize_database(db_path)

    service = LibraryBooksService(db_path=db_path)
    created = await service.create_or_get_shared_book(
        GROUP,
        added_by_user_id="tester",
        start_chapter_index=12,
        auto_archive_on_complete=True,
    )
    book = created["book"]
    payload = created["payload"]

    output = {
        "bookStatus": book.get("bookStatus", ""),
        "payloadBookStatus": payload.get("bookStatus", ""),
        "primaryBookUrl": book.get("primaryBookUrl", ""),
        "primaryTocUrl": book.get("primaryTocUrl", ""),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if output["bookStatus"] != "completed":
        print("expected hydrated subscription book status to be completed")
        return 1
    if output["payloadBookStatus"] != "completed":
        print("expected payload book status to be completed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
