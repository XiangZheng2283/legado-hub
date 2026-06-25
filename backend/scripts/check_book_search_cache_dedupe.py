"""Self-check for book_search_cache dedupe semantics."""

from __future__ import annotations

import sys
import tempfile
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.search_coordinator import SearchCoordinator
from app.storage.db import initialize_database


def main() -> None:
    tmp_root = Path(tempfile.gettempdir()) / "legado-book-cache-dedupe"
    tmp_root.mkdir(parents=True, exist_ok=True)
    db_path = tmp_root / "cache-check.db"
    if db_path.exists():
        db_path.unlink()
    try:
        initialize_database(db_path)

        coordinator = SearchCoordinator()
        coordinator._conn = lambda: sqlite3.connect(db_path)  # ponytail: tiny test seam

        duplicated = [
            {
                "sourceId": "official-a",
                "sourceName": "官方源A",
                "name": "剑宗外门",
                "author": "乘风",
                "rawBookUrl": "official://book-a",
                "bookUrl": "official://book-a",
                "score": 10,
            },
            {
                "sourceId": "official-a",
                "sourceName": "官方源A",
                "name": "剑宗外门",
                "author": "乘风",
                "rawBookUrl": "official://book-a",
                "bookUrl": "official://book-a",
                "score": 30,
            },
        ]
        coordinator._persist_book_cache("title", duplicated[:1])
        coordinator._persist_book_cache("author", duplicated[1:])

        cached = coordinator._query_book_cache("剑宗外门", match_mode="mixed", limit=20)
        assert len(cached) == 1, cached
        assert cached[0]["score"] == 30, cached

        source_cached = coordinator._query_source_cache("乘风", "official-a", limit=20)
        assert len(source_cached) == 1, source_cached
        assert source_cached[0]["rawBookUrl"] == "official://book-a", source_cached

        with coordinator._conn() as conn:
            count = conn.execute("SELECT COUNT(*) FROM book_search_cache").fetchone()[0]
        assert count == 1, count

        print("book search cache dedupe self-check passed")
    finally:
        try:
            if db_path.exists():
                db_path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
