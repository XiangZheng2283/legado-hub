"""Migrate old novel folder layout to the new layout.

Old layout:
    backend/data/novels/legadohub_ai_aggregate/{book_id}/

New layout:
    backend/data/novels/legadohub/{书名}_{作者}/

Also generates metadata.json for each migrated book folder and updates
aggregate_chapter_tasks.content_file_path to point to the new paths.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import DATA_DIR
from app.services.novel_file_cache import METADATA_FILE, SUBSCRIPTION_FOLDER, NovelFileCache

OLD_SOURCE_FOLDER = "legadohub_ai_aggregate"


def _is_book_id(value: str) -> bool:
    """Detect legacy folder names that are UUIDs or hex book ids."""
    cleaned = value.replace("-", "")
    return len(cleaned) >= 16 and re.fullmatch(r"[0-9a-fA-F]+", cleaned) is not None


def _book_folder_name(name: str, author: str) -> str:
    cache = NovelFileCache()
    safe_name = cache._safe_segment(name or "unknown-book", max_length=80)
    safe_author = cache._safe_segment(author or "", max_length=40)
    if safe_author:
        return f"{safe_name}_{safe_author}"
    return safe_name


def _resolve_target_dir(
    old_dir: Path,
    conn: sqlite3.Connection,
    new_root: Path,
) -> tuple[Path, str, str, str] | None:
    """Return (target_dir, book_id, book_name, author) for an old folder."""
    folder_name = old_dir.name

    # Already migrated format: 书名_作者
    if not _is_book_id(folder_name):
        parts = folder_name.rsplit("_", 1)
        book_name = parts[0]
        author = parts[1] if len(parts) > 1 else ""
        # Try to find book_id by name/author
        row = conn.execute(
            "SELECT aggregate_book_id FROM aggregate_book_tasks WHERE name = ? AND author = ? LIMIT 1",
            (book_name, author),
        ).fetchone()
        book_id = row[0] if row else ""
        return new_root / folder_name, book_id, book_name, author

    # Legacy book_id folder
    book_id = folder_name
    row = conn.execute(
        "SELECT name, author FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
        (book_id,),
    ).fetchone()
    if not row:
        print(f"[skip] No aggregate_book_tasks record for {book_id}")
        return None
    book_name, author = row
    target_name = _book_folder_name(book_name, author)
    return new_root / target_name, book_id, book_name, author


def _update_content_file_path(
    conn: sqlite3.Connection,
    old_path_prefix: str,
    new_path_prefix: str,
) -> int:
    """Update content_file_path rows that start with the old prefix."""
    cursor = conn.execute(
        """
        UPDATE aggregate_chapter_tasks
        SET content_file_path = ? || SUBSTR(content_file_path, ?)
        WHERE content_file_path LIKE ?
        """,
        (new_path_prefix, len(old_path_prefix) + 1, old_path_prefix + "%"),
    )
    conn.commit()
    return cursor.rowcount


def migrate(
    db_path: Path,
    novels_root: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    old_root = novels_root / OLD_SOURCE_FOLDER
    new_root = novels_root / SUBSCRIPTION_FOLDER
    result = {"migrated": 0, "skipped": 0, "files_moved": 0, "db_rows_updated": 0}

    if not old_root.exists():
        print(f"[skip] Old root does not exist: {old_root}")
        return result

    with sqlite3.connect(db_path) as conn:
        for old_dir in sorted(old_root.iterdir()):
            if not old_dir.is_dir():
                continue

            resolved = _resolve_target_dir(old_dir, conn, new_root)
            if resolved is None:
                result["skipped"] += 1
                continue
            target_dir, book_id, book_name, author = resolved

            if not dry_run:
                target_dir.mkdir(parents=True, exist_ok=True)

            moved = 0
            for md_file in sorted(old_dir.glob("*.md")):
                target_file = target_dir / md_file.name
                if target_file.exists():
                    # Keep the newer file
                    if md_file.stat().st_mtime > target_file.stat().st_mtime:
                        if not dry_run:
                            shutil.move(str(md_file), str(target_file))
                        moved += 1
                    else:
                        if not dry_run:
                            md_file.unlink()
                else:
                    if not dry_run:
                        shutil.move(str(md_file), str(target_file))
                    moved += 1

            if not dry_run:
                # Update database paths
                old_prefix = str(old_dir)
                new_prefix = str(target_dir)
                rows = _update_content_file_path(conn, old_prefix, new_prefix)
                result["db_rows_updated"] += rows

                # Generate metadata.json
                cache = NovelFileCache(root=novels_root)
                cache._write_subscription_metadata(
                    target_dir,
                    book_id=book_id,
                    book_name=book_name,
                    author=author,
                )

                # Remove old dir if empty
                try:
                    old_dir.rmdir()
                except OSError:
                    pass

            result["migrated"] += 1
            result["files_moved"] += moved
            print(f"[migrated] {old_dir.name} -> {target_dir.name} ({moved} files)")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate novel folders to the new layout")
    parser.add_argument("--db-path", type=Path, default=DATA_DIR / "app.db")
    parser.add_argument("--novels-root", type=Path, default=DATA_DIR / "novels")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"db_path: {args.db_path}")
    print(f"novels_root: {args.novels_root}")
    print(f"dry_run: {args.dry_run}")
    print("-" * 40)

    result = migrate(args.db_path, args.novels_root, dry_run=args.dry_run)

    print("-" * 40)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
