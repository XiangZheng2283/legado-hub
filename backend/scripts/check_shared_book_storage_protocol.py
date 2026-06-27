#!/usr/bin/env python3
"""Operator verification script for shared-book storage protocol.

Checks that a live book directory follows the atomic-write and truth-source
rules defined in docs/superpowers/specs/2026-06-26-shared-subscription-rewrite-design.md.

Run from repo root:
    python backend/scripts/check_shared_book_storage_protocol.py <book_name> <author>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.shared_book_storage import SharedBookStorage


def _fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)


def _ok(message: str) -> None:
    print(f"OK: {message}")


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: check_shared_book_storage_protocol.py <book_name> <author>")
        return 2

    book_name, author = sys.argv[1], sys.argv[2]
    storage = SharedBookStorage()
    book_dir = storage.shared_book_dir(book_name=book_name, author=author)

    if not book_dir.exists():
        _fail(f"shared book directory does not exist: {book_dir}")

    metadata_path = storage.metadata_path(book_name=book_name, author=author)
    chapter_index_path = storage.chapter_index_path(book_name=book_name, author=author)

    if not metadata_path.exists():
        _fail(f"metadata.json missing: {metadata_path}")
    if not chapter_index_path.exists():
        _fail(f"chapter_index.json missing: {chapter_index_path}")

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _fail(f"metadata.json is not valid JSON: {exc}")

    try:
        chapter_index = json.loads(chapter_index_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _fail(f"chapter_index.json is not valid JSON: {exc}")

    # 1. Shared metadata must not contain private source URLs.
    raw_source_map = metadata.get("sourceMap") or metadata.get("sourceMapSummary") or []
    for item in raw_source_map:
        if isinstance(item, dict) and (item.get("bookUrl") or item.get("tocUrl")):
            _fail(f"shared metadata leaks source URL: {item}")

    _ok("shared metadata does not contain source URLs")

    # 2. Every indexed chapter must have a valid trace block.
    trace_check = storage.check_chapter_traces(
        book_name=book_name,
        author=author,
        chapter_index_payload=chapter_index,
    )
    if not trace_check["valid"]:
        _fail(
            f"chapter trace validation failed: total={trace_check['total']}, "
            f"broken={trace_check['broken']}, missing={trace_check['missing']}"
        )

    _ok(f"all {trace_check['total']} indexed chapters have valid trace blocks")

    # 3. Derived counts in metadata must match chapter_index + trace reality.
    chapter_traces: dict[int, dict] = {}
    for entry in chapter_index.get("chapters", []):
        if not isinstance(entry, dict):
            continue
        file_name = str(entry.get("file", "") or "").strip()
        chapter_path = book_dir / file_name if file_name else None
        if not chapter_path or not chapter_path.exists():
            continue
        try:
            trace = storage.parse_trace_block(chapter_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        chapter_index_val = int(trace.get("chapterIndex", 0) or 0)
        if chapter_index_val > 0:
            chapter_traces[chapter_index_val] = trace

    rebuilt_state = storage.rebuild_book_state_from_files(
        chapter_index_payload=chapter_index,
        chapter_traces=chapter_traces,
        existing_state=metadata.get("bookState"),
    )
    current_state = storage.build_book_state_summary(
        metadata.get("bookState"),
        chapter_count=rebuilt_state["chapterCount"],
    )

    drift_keys = [
        "chapterCount",
        "processedChapterCount",
        "readableChapterCount",
        "previewChapterCount",
        "proofreadCompleteCount",
        "suspectChapterCount",
        "failedChapterCount",
    ]
    drift = {key for key in drift_keys if rebuilt_state.get(key) != current_state.get(key)}
    if drift:
        _fail(f"metadata bookState drift detected on keys: {sorted(drift)}")

    _ok("metadata bookState matches rebuilt counts from chapter files")

    # 4. No leftover .tmp files.
    tmp_files = list(book_dir.rglob("*.tmp"))
    if tmp_files:
        _fail(f"stale .tmp files found: {tmp_files}")

    _ok("no stale .tmp files")

    # 5. Private source_refs.json exists and contains URLs.
    source_refs_path = storage.source_refs_path(book_name=book_name, author=author)
    if not source_refs_path.exists():
        _fail(f"private source_refs.json missing: {source_refs_path}")

    try:
        source_refs = json.loads(source_refs_path.read_text(encoding="utf-8"))
    except Exception as exc:
        _fail(f"source_refs.json is not valid JSON: {exc}")

    primary = source_refs.get("primary") or {}
    if not primary.get("bookUrl"):
        _fail("source_refs.json primary source missing bookUrl")

    _ok("private source_refs.json contains primary source URL")

    print("\nAll storage protocol checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
