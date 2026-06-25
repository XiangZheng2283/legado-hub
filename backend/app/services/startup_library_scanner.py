"""Startup scanner that recreates library entries from local novel folders.

On startup, this module scans backend/data/novels/legadohub/ for
metadata.json files and ensures each book has a corresponding
aggregate_book_tasks record. Missing chapter records are recreated from the
local Markdown files so already-downloaded chapters are not re-processed.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import DATA_DIR, DB_PATH
from app.services.novel_file_cache import METADATA_FILE, SUBSCRIPTION_FOLDER

METADATA_VERSION = 1
CHAPTER_FILE_RE = re.compile(r"^(\d{6})\s+(.+)\.md$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_chapter_file(path: Path) -> dict[str, Any] | None:
    """Parse chapter index and title from a file like '000001 第一章.md'."""
    match = CHAPTER_FILE_RE.match(path.name)
    if not match:
        return None
    return {
        "chapterIndex": int(match.group(1)),
        "title": match.group(2).strip(),
    }


def _read_file_content(path: Path) -> tuple[str, dict[str, Any]]:
    """Read chapter content and optional trace metadata from a markdown file."""
    text = path.read_text(encoding="utf-8")
    trace_meta: dict[str, Any] = {}
    body = text
    if "LEGADOHUB_TRACE_BEGIN" in text and "LEGADOHUB_TRACE_END" in text:
        parts = text.rsplit("LEGADOHUB_TRACE_BEGIN", 1)
        body = parts[0].strip()
        trace_block = "LEGADOHUB_TRACE_BEGIN" + parts[1]
        # Extract yaml inside ```yaml ... ```
        yaml_match = re.search(r"```yaml\n(.*?)\n```", trace_block, re.DOTALL)
        if yaml_match:
            # Very small parser: we only need a few scalar keys.
            raw_yaml = yaml_match.group(1)
            trace_meta = _parse_simple_yaml(raw_yaml)
    return body, trace_meta


def _parse_simple_yaml(raw: str) -> dict[str, Any]:
    """Parse only top-level scalar keys from the trace yaml block."""
    result: dict[str, Any] = {}
    for line in raw.splitlines():
        line = line.rstrip()
        if not line or line.startswith("-") or line.startswith(" "):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value and not value.startswith("{"):
                result[key] = value.strip('"')
    return result


def _infer_status(trace_meta: dict[str, Any]) -> str:
    """Infer chapter status from trace metadata."""
    # Prefer explicit status if present.
    status = trace_meta.get("status", "")
    if status in {"processed", "fallback", "error", "pending"}:
        return status
    selected = trace_meta.get("selectedContentSource", "")
    if selected and selected != "primary":
        return "fallback"
    fallback = trace_meta.get("fallbackSourceId", "")
    if fallback:
        return "fallback"
    return "processed"


def _build_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    """Build the aggregate_payload_json from metadata for a recovered book."""
    return {
        "bookId": metadata.get("bookId", ""),
        "name": metadata.get("bookName", ""),
        "author": metadata.get("author", ""),
        "coverUrl": metadata.get("coverUrl", ""),
        "intro": metadata.get("intro", ""),
        "wordCount": metadata.get("wordCount", ""),
        "primaryBookId": metadata.get("primaryBookId", ""),
        "primarySourceId": metadata.get("primarySourceId", ""),
        "primarySourceName": metadata.get("primarySourceName", ""),
        "primaryBookUrl": metadata.get("primaryBookUrl", ""),
        "primaryTocUrl": metadata.get("primaryTocUrl", ""),
        "startChapterIndex": metadata.get("startChapterIndex", 1),
        "totalChapters": metadata.get("totalChapters", 0),
        "sources": [
            {
                "sourceId": metadata.get("primarySourceId", ""),
                "sourceName": metadata.get("primarySourceName", ""),
                "bookId": metadata.get("primaryBookId", ""),
                "bookUrl": metadata.get("primaryBookUrl", ""),
                "tocUrl": metadata.get("primaryTocUrl", ""),
                "score": 0,
            }
        ],
    }


def _insert_book(conn: sqlite3.Connection, metadata: dict[str, Any]) -> None:
    book_id = metadata.get("bookId", "")
    if not book_id:
        return

    now = _now()
    payload = _build_payload(metadata)
    conn.execute(
        """
        INSERT OR IGNORE INTO aggregate_book_tasks
        (aggregate_book_id, canonical_name, canonical_author, name, author, cover_url, intro,
         word_count, aggregate_payload_json, primary_book_id, primary_source_id,
         primary_source_name, primary_book_url, primary_toc_url, start_chapter_index,
         total_chapters_at_subscribe, total_chapters, search_visibility_status, book_status,
         status, interval_minutes, last_check_time, next_check_time, ai_enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            book_id,
            metadata.get("bookName", ""),
            metadata.get("author", ""),
            metadata.get("bookName", ""),
            metadata.get("author", ""),
            metadata.get("coverUrl", ""),
            metadata.get("intro", ""),
            metadata.get("wordCount", ""),
            json.dumps(payload, ensure_ascii=False),
            metadata.get("primaryBookId", ""),
            metadata.get("primarySourceId", ""),
            metadata.get("primarySourceName", ""),
            metadata.get("primaryBookUrl", ""),
            metadata.get("primaryTocUrl", ""),
            metadata.get("startChapterIndex", 1),
            metadata.get("totalChapters", 0),
            metadata.get("totalChapters", 0),
            "hidden",
            metadata.get("bookStatus", "unknown"),
            "active",
            30,
            now,
            now,
            1,
            now,
            now,
        ),
    )
    conn.commit()


def _update_book_stats(conn: sqlite3.Connection, book_id: str) -> None:
    """Recalculate processed/visible/failed chapter counts from the database."""
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status IN ('processed', 'fallback') THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS failed
        FROM aggregate_chapter_tasks
        WHERE aggregate_book_id = ?
        """,
        (book_id,),
    ).fetchone()
    if not row:
        return
    total, completed, failed = row
    completed = completed or 0
    failed = failed or 0

    # Visibility: from start_chapter_index, continuous completed count.
    start_row = conn.execute(
        "SELECT start_chapter_index FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
        (book_id,),
    ).fetchone()
    start_index = start_row[0] if start_row and start_row[0] else 1

    visible = 0
    if completed and completed > 0:
        rows = conn.execute(
            """
            SELECT chapter_index, status
            FROM aggregate_chapter_tasks
            WHERE aggregate_book_id = ? AND chapter_index >= ?
            ORDER BY chapter_index
            """,
            (book_id, start_index),
    ).fetchall()
        for idx, status in rows:
            if status in ("processed", "fallback"):
                visible += 1
            else:
                break

    visibility = "visible" if visible >= min(50, total - start_index + 1) else "hidden"

    conn.execute(
        """
        UPDATE aggregate_book_tasks
        SET total_chapters = ?, processed_chapters = ?, visible_processed_chapters = ?,
            failed_chapters = ?, search_visibility_status = ?, updated_at = ?
        WHERE aggregate_book_id = ?
        """,
        (total, completed, visible, failed, visibility, _now(), book_id),
    )
    conn.commit()


def _recover_chapters(conn: sqlite3.Connection, book_id: str, book_dir: Path) -> int:
    """Insert or update aggregate_chapter_tasks from local markdown files."""
    existing_indexes = {
        row[0]
        for row in conn.execute(
            "SELECT chapter_index FROM aggregate_chapter_tasks WHERE aggregate_book_id = ?",
            (book_id,),
        ).fetchall()
        if row[0] is not None
    }

    count = 0
    for md_file in sorted(book_dir.glob("*.md")):
        if md_file.name == METADATA_FILE:
            continue
        parsed = _parse_chapter_file(md_file)
        if not parsed:
            continue
        chapter_index = parsed["chapterIndex"]
        if chapter_index in existing_indexes:
            continue
        title = parsed["title"]
        content, trace_meta = _read_file_content(md_file)
        status = _infer_status(trace_meta)
        chapter_id = trace_meta.get("chapterId", "")
        if not chapter_id:
            # Build a deterministic chapter id from the virtual source and the file path.
            from app.services.aggregate_virtual_source import make_aggregate_chapter_url

            chapter_id = make_aggregate_chapter_url(book_id, chapter_index)
        now = _now()
        conn.execute(
            """
            INSERT INTO aggregate_chapter_tasks
            (chapter_id, aggregate_book_id, chapter_index, title, status, content_length,
             processed_content, content_file_path, source_alignment_json, fallback_source_id,
             ai_model, ai_total_tokens, last_processed_at, updated_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chapter_id,
                book_id,
                chapter_index,
                title,
                status,
                len(content),
                content,
                str(md_file),
                json.dumps(trace_meta.get("alignment", {}), ensure_ascii=False) if trace_meta.get("alignment") else "",
                trace_meta.get("fallbackSourceId", "") or trace_meta.get("selectedSource", ""),
                trace_meta.get("aiModel", ""),
                _safe_int(trace_meta.get("aiTokens", 0)),
                now,
                now,
                now,
            ),
        )
        count += 1
    conn.commit()
    return count


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def scan_local_library(
    db_path: Path | None = None,
    novels_root: Path | None = None,
) -> dict[str, Any]:
    """Scan local novel folders and recreate library entries on startup."""
    db_path = db_path or DB_PATH
    novels_root = novels_root or DATA_DIR / "novels"
    result: dict[str, Any] = {"recovered": 0, "chapters": 0, "skipped": 0, "errors": []}

    subscription_root = novels_root / SUBSCRIPTION_FOLDER
    if not subscription_root.exists():
        return result

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for book_dir in sorted(subscription_root.iterdir()):
            if not book_dir.is_dir():
                continue
            metadata_path = book_dir / METADATA_FILE
            if not metadata_path.exists():
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception as exc:
                result["errors"].append(f"{book_dir.name}: failed to read metadata: {exc}")
                continue

            book_id = metadata.get("bookId", "")
            if not book_id:
                result["skipped"] += 1
                continue

            existing = conn.execute(
                "SELECT aggregate_book_id FROM aggregate_book_tasks WHERE aggregate_book_id = ?",
                (book_id,),
            ).fetchone()

            try:
                if not existing:
                    _insert_book(conn, metadata)
                    result["recovered"] += 1
                chapters = _recover_chapters(conn, book_id, book_dir)
                result["chapters"] += chapters
                _update_book_stats(conn, book_id)
            except Exception as exc:
                result["errors"].append(f"{book_id}: {exc}")

    return result
