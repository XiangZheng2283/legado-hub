from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import DATA_DIR
from app.services.novel_file_cache import METADATA_FILE, SUBSCRIPTION_FOLDER
from app.services.shared_book_storage import SharedBookStorage

SCHEMA_VERSION = 1
CHAPTER_FILE_RE = re.compile(r"^(\d+)[\s_-]+(.+)\.md$", re.IGNORECASE)
TRACE_BLOCK_RE = re.compile(
    r"\n*LEGADOHUB_TRACE_BEGIN.*?LEGADOHUB_TRACE_END\s*$",
    re.DOTALL,
)
TRACE_PAYLOAD_RE = re.compile(
    r"LEGADOHUB_TRACE_BEGIN\s*(.*?)\s*LEGADOHUB_TRACE_END",
    re.DOTALL,
)
RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _add_warning(warnings: list[str], message: str) -> None:
    warnings.append(message)


def _safe_json_loads(raw: str | None, *, warnings: list[str], context: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception as exc:
        _add_warning(warnings, f"{context}: failed to parse JSON: {exc}")
        return {}
    if isinstance(payload, dict):
        return payload
    _add_warning(warnings, f"{context}: expected JSON object, got {type(payload).__name__}")
    return {}


def _safe_json_loads_list(raw: str | None, *, warnings: list[str], context: str) -> list[Any]:
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except Exception as exc:
        _add_warning(warnings, f"{context}: failed to parse JSON: {exc}")
        return []
    if isinstance(payload, list):
        return payload
    _add_warning(warnings, f"{context}: expected JSON array, got {type(payload).__name__}")
    return []


def _safe_segment(value: str, *, max_length: int = 96) -> str:
    normalized = str(value or "").strip().strip(".")
    normalized = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        normalized = "unknown"
    if normalized.upper() in RESERVED_WINDOWS_NAMES:
        normalized = f"{normalized}_"
    return normalized[:max_length].rstrip(" .") or "unknown"


def _slug_part(value: str, *, max_length: int) -> str:
    normalized = _safe_segment(value or "", max_length=max_length).lower()
    normalized = normalized.replace(" ", "-").replace("_", "-")
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or "unknown"


def _stable_book_id(*, legacy_book_id: str, book_name: str, author: str) -> str:
    base = f"{_slug_part(book_name, max_length=48)}_{_slug_part(author, max_length=24)}"
    digest_source = legacy_book_id or f"{book_name}|{author}"
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:8]
    return f"{base}_{digest}"


def _target_folder_name(book_name: str, author: str) -> str:
    safe_name = _safe_segment(book_name or "unknown-book", max_length=80)
    safe_author = _safe_segment(author or "", max_length=40)
    if safe_author:
        return f"{safe_name}_{safe_author}"
    return safe_name


def _map_legacy_chapter_status(row: sqlite3.Row) -> str:
    legacy_status = str(row["status"] or "").strip().lower()
    if legacy_status in {"pending", "fetched"}:
        return "fetched"
    if legacy_status in {"ai_processing", "completing"}:
        return "processing"
    if legacy_status == "fallback":
        return "readable"
    if legacy_status == "error":
        return "failed"
    if legacy_status == "skipped":
        return "skipped"
    if legacy_status == "processed":
        has_ai = bool(row["ai_model"]) or int(row["ai_total_tokens"] or 0) > 0 or bool(row["policy_snapshot_json"])
        return "proofread_complete" if has_ai else "supplemented"
    return legacy_status or "unknown"


def _book_state_status(book_row: sqlite3.Row) -> str:
    status = str(book_row["status"] or "").strip().lower()
    book_status = str(book_row["book_status"] or "").strip().lower()
    if status == "archived":
        return "archived"
    if book_status in {"completed", "finished", "完结", "完本"}:
        return "completed"
    if status in {"paused", "error"}:
        return status
    return "active"


def _normalize_root(path: Path) -> Path:
    return path.resolve(strict=False)


def _path_within_root(path: Path, *, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def _path_hint_within_root(
    path_value: str,
    *,
    novels_root: Path,
    warnings: list[str],
    context: str,
) -> Path | None:
    if not path_value:
        return None
    candidate = Path(path_value).resolve(strict=False)
    if not _path_within_root(candidate, root=novels_root):
        _add_warning(
            warnings,
            f"{context}: ignored out-of-root path hint: {candidate}",
        )
        return None
    return candidate


def _resolve_book_dir(book_row: sqlite3.Row, *, novels_root: Path, warnings: list[str]) -> Path | None:
    novels_root = _normalize_root(novels_root)
    subscription_root = novels_root / SUBSCRIPTION_FOLDER
    candidates: list[Path] = []

    folder_name = _target_folder_name(book_row["name"] or "", book_row["author"] or "")
    candidates.append(subscription_root / folder_name)
    candidates.append(subscription_root / str(book_row["aggregate_book_id"] or ""))

    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate

    content_file_path = str(book_row["sample_content_file_path"] or "").strip()
    if content_file_path:
        hinted_path = _path_hint_within_root(
            content_file_path,
            novels_root=novels_root,
            warnings=warnings,
            context=f"book {book_row['aggregate_book_id']} sample_content_file_path",
        )
        parent = hinted_path.parent if hinted_path else None
        if parent is not None and parent.exists() and parent.is_dir():
            return parent

    if subscription_root.exists():
        for book_dir in sorted(subscription_root.iterdir()):
            if not book_dir.is_dir():
                continue
            metadata_path = book_dir / METADATA_FILE
            if not metadata_path.exists():
                continue
            metadata = _safe_json_loads(
                metadata_path.read_text(encoding="utf-8"),
                warnings=warnings,
                context=f"{metadata_path}",
            )
            if metadata.get("bookId") == book_row["aggregate_book_id"]:
                return book_dir

    return None


def _strip_existing_trace(text: str) -> str:
    return TRACE_BLOCK_RE.sub("", text or "").rstrip()


def _strip_heading(text: str, title: str) -> str:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    heading = f"# {title}".strip()
    if heading and normalized.startswith(heading):
        remainder = normalized[len(heading):].lstrip("\n")
        return remainder.strip()
    return normalized


def _parse_legacy_chapter_filename(path: Path) -> tuple[int | None, str]:
    match = CHAPTER_FILE_RE.match(path.name)
    if not match:
        return None, path.stem
    return int(match.group(1)), match.group(2).strip()


def _extract_existing_trace_payload(
    raw_text: str,
    *,
    warnings: list[str],
    context: str,
) -> dict[str, Any]:
    match = TRACE_PAYLOAD_RE.search(raw_text or "")
    if not match:
        return {}
    raw_payload = match.group(1).strip()
    if raw_payload.endswith("-->"):
        raw_payload = raw_payload[:-3].rstrip()
    if raw_payload.startswith("<!--"):
        raw_payload = raw_payload[4:].lstrip()
    payload = _safe_json_loads(raw_payload, warnings=warnings, context=context)
    return payload if isinstance(payload, dict) else {}


def _load_chapter_body(
    row: sqlite3.Row,
    *,
    fallback_dir: Path | None,
    novels_root: Path,
    warnings: list[str],
) -> tuple[str, Path | None, dict[str, Any]]:
    direct_path = str(row["content_file_path"] or "").strip()
    candidate_paths: list[Path] = []
    if direct_path:
        hinted_path = _path_hint_within_root(
            direct_path,
            novels_root=novels_root,
            warnings=warnings,
            context=f"chapter {row['chapter_id']} content_file_path",
        )
        if hinted_path is not None:
            candidate_paths.append(hinted_path)
    if fallback_dir is not None:
        for md_file in sorted(fallback_dir.glob("*.md")):
            index, _ = _parse_legacy_chapter_filename(md_file)
            if index and index == int(row["chapter_index"] or 0):
                candidate_paths.append(md_file)
                break
    for candidate in candidate_paths:
        if candidate.exists() and candidate.is_file():
            raw = candidate.read_text(encoding="utf-8")
            existing_trace = _extract_existing_trace_payload(
                raw,
                warnings=warnings,
                context=f"{candidate}",
            )
            content = _strip_heading(_strip_existing_trace(raw), row["title"] or "")
            if content:
                return content, candidate, existing_trace
    processed_content = str(row["processed_content"] or "").strip()
    return processed_content, None, {}


def _build_trace(
    row: sqlite3.Row,
    *,
    chapter_status: str,
    body: str,
    existing_trace: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    alignment = _safe_json_loads(
        row["source_alignment_json"],
        warnings=warnings,
        context=f"chapter {row['chapter_id']} source_alignment_json",
    )
    policy_snapshot = _safe_json_loads(
        row["policy_snapshot_json"],
        warnings=warnings,
        context=f"chapter {row['chapter_id']} policy_snapshot_json",
    )
    source_snapshot_refs = _safe_json_loads_list(
        row["source_snapshot_refs_json"],
        warnings=warnings,
        context=f"chapter {row['chapter_id']} source_snapshot_refs_json",
    )
    primary_source = existing_trace.get("primarySource")
    if not isinstance(primary_source, dict):
        primary_source = {}
    primary_source_id = (
        alignment.get("primarySourceId")
        or existing_trace.get("primarySourceId")
        or primary_source.get("sourceId")
        or ""
    )
    primary_source_url = (
        existing_trace.get("primarySourceUrl")
        or primary_source.get("chapterUrl")
        or row["primary_source_chapter_url"]
        or ""
    )
    source_word_count = int(
        row["source_word_count"]
        or primary_source.get("wordCount", 0)
        or existing_trace.get("officialWordCount", 0)
        or 0
    )
    supplement_source = existing_trace.get("supplementSource")
    if not isinstance(supplement_source, dict):
        supplement_source = {}
    supplement_source_id = (
        row["fallback_source_id"]
        or alignment.get("candidateSourceId")
        or supplement_source.get("sourceId")
        or ""
    )
    proofread_complete = chapter_status == "proofread_complete"
    selected_content_source = (
        alignment.get("selectedContentSource")
        or existing_trace.get("selectedContentSource")
        or ""
    )
    if not source_snapshot_refs:
        existing_snapshot_refs = existing_trace.get("sourceSnapshotRefs")
        if isinstance(existing_snapshot_refs, list):
            source_snapshot_refs = existing_snapshot_refs

    trace: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "aggregateBookId": row["aggregate_book_id"] or "",
        "chapterId": row["chapter_id"] or "",
        "chapterIndex": int(row["chapter_index"] or 0),
        "chapterTitle": row["title"] or "",
        "chapterStatus": chapter_status,
        "proofreadComplete": proofread_complete,
        "previewOnly": bool(row["preview_only"]),
        "primarySource": {
            "sourceId": primary_source_id,
            "chapterId": row["source_chapter_id"] or "",
            "chapterUrl": primary_source_url,
            "wordCount": source_word_count,
        },
        "primarySourceId": primary_source_id,
        "primarySourceUrl": primary_source_url,
        "officialWordCount": source_word_count,
        "fetchedWordCount": len(str(body or "")),
        "selectedContentSource": selected_content_source,
        "processedAt": existing_trace.get("processedAt") or row["last_processed_at"] or row["updated_at"] or "",
        "legacy": {
            "legacyStatus": row["status"] or "",
            "chapterId": row["chapter_id"] or "",
            "contentFilePath": row["content_file_path"] or "",
        },
    }
    if supplement_source_id:
        trace["supplementSource"] = {
            "sourceId": supplement_source_id,
            "selected": True,
        }
    if row["ai_model"] or int(row["ai_total_tokens"] or 0) > 0 or alignment:
        trace["aiCheck"] = {
            "model": row["ai_model"] or "",
            "deviationScore": float(row["deviation_score"] or 0.0),
            "selfScore": float(row["ai_self_score"] or 0.0),
            "promptTokens": int(row["ai_prompt_tokens"] or 0),
            "completionTokens": int(row["ai_completion_tokens"] or 0),
            "totalTokens": int(row["ai_total_tokens"] or 0),
            "latencyMs": int(row["ai_latency_ms"] or 0),
        }
        trace["aiModel"] = trace["aiCheck"]["model"]
        trace["aiTokens"] = trace["aiCheck"]["totalTokens"]
    if alignment:
        trace["alignment"] = alignment
    if source_snapshot_refs:
        trace["sourceSnapshotRefs"] = source_snapshot_refs
    if policy_snapshot:
        trace["legacyPolicySnapshot"] = policy_snapshot
    return trace


def _render_trace_block(trace: dict[str, Any]) -> str:
    trace_json = json.dumps(trace, ensure_ascii=False, indent=2)
    return f"<!-- LEGADOHUB_TRACE_BEGIN\n{trace_json}\nLEGADOHUB_TRACE_END -->"


def _render_chapter_markdown(*, title: str, body: str, trace: dict[str, Any]) -> str:
    normalized_body = str(body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    heading = f"# {title}".strip()
    if normalized_body:
        return f"{heading}\n\n{normalized_body}\n\n{_render_trace_block(trace)}\n"
    return f"{heading}\n\n{_render_trace_block(trace)}\n"


def _load_book_rows(conn: sqlite3.Connection, aggregate_book_id: str | None = None) -> list[sqlite3.Row]:
    params: list[Any] = []
    where_sql = ""
    if aggregate_book_id:
        where_sql = "WHERE b.aggregate_book_id = ?"
        params.append(aggregate_book_id)
    query = f"""
        SELECT b.*,
               (
                 SELECT content_file_path
                 FROM aggregate_chapter_tasks c
                 WHERE c.aggregate_book_id = b.aggregate_book_id
                   AND c.content_file_path IS NOT NULL
                   AND c.content_file_path != ''
                 ORDER BY COALESCE(c.chapter_index, 999999), c.created_at
                 LIMIT 1
               ) AS sample_content_file_path
        FROM aggregate_book_tasks b
        {where_sql}
        ORDER BY b.created_at ASC, b.aggregate_book_id ASC
    """
    return conn.execute(query, params).fetchall()


def _load_chapter_rows(conn: sqlite3.Connection, aggregate_book_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title, status,
               source_word_count, preview_only, primary_source_chapter_url, processed_content,
               content_file_path, last_processed_at, policy_snapshot_json, source_snapshot_refs_json,
               trace_hash, ai_model, ai_prompt_tokens, ai_completion_tokens, ai_total_tokens,
               ai_latency_ms, deviation_score, ai_self_score, fallback_source_id,
               source_alignment_json, created_at, updated_at
        FROM aggregate_chapter_tasks
        WHERE aggregate_book_id = ?
        ORDER BY COALESCE(chapter_index, 999999), created_at ASC, chapter_id ASC
        """,
        (aggregate_book_id,),
    ).fetchall()


def _build_source_refs(book_row: sqlite3.Row, *, proposed_book_id: str, warnings: list[str]) -> dict[str, Any]:
    payload = _safe_json_loads(
        book_row["aggregate_payload_json"],
        warnings=warnings,
        context=f"book {book_row['aggregate_book_id']} aggregate_payload_json",
    )
    storage = SharedBookStorage(root=Path("."))
    source_refs = storage.build_private_source_refs(
        {
            "primarySourceId": book_row["primary_source_id"] or "",
            "primaryBookId": book_row["primary_book_id"] or "",
            "primaryBookUrl": book_row["primary_book_url"] or "",
            "primaryTocUrl": book_row["primary_toc_url"] or "",
            "sources": payload.get("sources") if isinstance(payload.get("sources"), list) else [],
        }
    )
    source_refs["schemaVersion"] = SCHEMA_VERSION
    source_refs["bookId"] = proposed_book_id
    source_refs["legacyBookId"] = book_row["aggregate_book_id"] or ""
    return source_refs


def _build_metadata(
    book_row: sqlite3.Row,
    *,
    proposed_book_id: str,
    chapter_entries: list[dict[str, Any]],
    chapter_traces: dict[int, dict[str, Any]],
    legacy_metadata: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    payload = _safe_json_loads(
        book_row["aggregate_payload_json"],
        warnings=warnings,
        context=f"book {book_row['aggregate_book_id']} aggregate_payload_json",
    )
    storage = SharedBookStorage(root=Path("."))
    metadata = storage.build_shared_metadata(
        {
            "candidateId": proposed_book_id,
            "name": book_row["name"] or legacy_metadata.get("bookName", ""),
            "author": book_row["author"] or legacy_metadata.get("author", ""),
            "coverUrl": book_row["cover_url"] or legacy_metadata.get("coverUrl", ""),
            "intro": book_row["intro"] or legacy_metadata.get("intro", ""),
            "bookStatus": book_row["book_status"] or legacy_metadata.get("bookStatus", ""),
            "wordCount": book_row["word_count"] or legacy_metadata.get("wordCount", ""),
            "totalChaptersAtSubscribe": int(book_row["total_chapters_at_subscribe"] or 0),
            "primaryBookId": book_row["primary_book_id"] or "",
            "primarySourceId": book_row["primary_source_id"] or "",
            "primarySourceName": book_row["primary_source_name"] or "",
            "sources": payload.get("sources") if isinstance(payload.get("sources"), list) else [],
            "bookState": {
                "status": _book_state_status(book_row),
                "searchVisibilityStatus": book_row["search_visibility_status"] or "hidden",
                "lastUpdateCheckAt": book_row["last_check_time"] or book_row["updated_at"] or "",
            },
        }
    )
    metadata["schemaVersion"] = SCHEMA_VERSION
    metadata["createdAt"] = legacy_metadata.get("createdAt") or book_row["created_at"] or ""
    metadata["updatedAt"] = book_row["updated_at"] or legacy_metadata.get("updatedAt") or ""
    metadata["bookState"] = storage.rebuild_book_state_from_files(
        chapter_index_payload={"chapters": chapter_entries},
        chapter_traces=chapter_traces,
        existing_state=metadata.get("bookState"),
    )
    metadata["migration"] = {
        "phase": 0,
        "mode": "read_only_scan",
        "legacyBookId": book_row["aggregate_book_id"] or "",
        "legacyStartChapterIndex": int(book_row["start_chapter_index"] or 1),
    }
    return metadata


def scan_legacy_shared_subscription(
    *,
    db_path: Path,
    novels_root: Path,
    aggregate_book_id: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "mode": "read_only_scan",
        "dbPath": str(db_path),
        "novelsRoot": str(novels_root),
        "books": [],
        "warnings": [],
        "summary": {
            "booksScanned": 0,
            "booksRecovered": 0,
            "chaptersRecovered": 0,
            "missingLegacyDirs": 0,
        },
    }
    novels_root = _normalize_root(novels_root)

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        for book_row in _load_book_rows(conn, aggregate_book_id):
            result["summary"]["booksScanned"] += 1
            book_warnings: list[str] = []
            legacy_dir = _resolve_book_dir(book_row, novels_root=novels_root, warnings=book_warnings)
            if legacy_dir is None:
                result["summary"]["missingLegacyDirs"] += 1

            legacy_metadata: dict[str, Any] = {}
            if legacy_dir is not None:
                metadata_path = legacy_dir / METADATA_FILE
                if metadata_path.exists():
                    legacy_metadata = _safe_json_loads(
                        metadata_path.read_text(encoding="utf-8"),
                        warnings=book_warnings,
                        context=f"{metadata_path}",
                    )

            proposed_book_id = _stable_book_id(
                legacy_book_id=book_row["aggregate_book_id"] or "",
                book_name=book_row["name"] or legacy_metadata.get("bookName", ""),
                author=book_row["author"] or legacy_metadata.get("author", ""),
            )
            target_folder_name = _target_folder_name(
                book_row["name"] or legacy_metadata.get("bookName", ""),
                book_row["author"] or legacy_metadata.get("author", ""),
            )

            chapter_rows = _load_chapter_rows(conn, book_row["aggregate_book_id"])
            chapter_index_entries: list[dict[str, Any]] = []
            chapter_files: list[dict[str, Any]] = []
            chapter_traces: dict[int, dict[str, Any]] = {}

            for row in chapter_rows:
                chapter_index = int(row["chapter_index"] or 0)
                title = row["title"] or ""
                chapter_status = _map_legacy_chapter_status(row)
                safe_title = _safe_segment(title or "未命名章节", max_length=120)
                target_rel_path = f"chapters/{chapter_index:04d}-{safe_title}.md"
                body, legacy_file, existing_trace = _load_chapter_body(
                    row,
                    fallback_dir=legacy_dir,
                    novels_root=novels_root,
                    warnings=book_warnings,
                )
                trace = _build_trace(
                    row,
                    chapter_status=chapter_status,
                    body=body,
                    existing_trace=existing_trace,
                    warnings=book_warnings,
                )
                if chapter_index > 0:
                    chapter_traces[chapter_index] = trace
                rendered = _render_chapter_markdown(title=title or "未命名章节", body=body, trace=trace)
                chapter_index_entries.append(
                    {
                        "index": chapter_index,
                        "title": title,
                        "file": target_rel_path,
                        "status": chapter_status,
                    }
                )
                chapter_files.append(
                    {
                        "index": chapter_index,
                        "title": title,
                        "targetPath": f"library/{target_folder_name}/{target_rel_path}",
                        "legacyPath": str(legacy_file) if legacy_file else str(row["content_file_path"] or ""),
                        "content": rendered,
                        "trace": trace,
                    }
                )

            chapter_index = {
                "schemaVersion": SCHEMA_VERSION,
                "bookId": proposed_book_id,
                "chapters": chapter_index_entries,
            }
            metadata = _build_metadata(
                book_row,
                proposed_book_id=proposed_book_id,
                chapter_entries=chapter_index_entries,
                chapter_traces=chapter_traces,
                legacy_metadata=legacy_metadata,
                warnings=book_warnings,
            )
            source_refs = _build_source_refs(book_row, proposed_book_id=proposed_book_id, warnings=book_warnings)

            result["books"].append(
                {
                    "legacyBookId": book_row["aggregate_book_id"] or "",
                    "proposedBookId": proposed_book_id,
                    "legacyDir": str(legacy_dir) if legacy_dir else "",
                    "targetDir": f"library/{target_folder_name}",
                    "warnings": book_warnings,
                    "proposedFiles": {
                        "metadata.json": metadata,
                        "chapter_index.json": chapter_index,
                        "source_refs.json": source_refs,
                        "chapters": chapter_files,
                    },
                }
            )
            result["warnings"].extend(book_warnings)
            result["summary"]["booksRecovered"] += 1
            result["summary"]["chaptersRecovered"] += len(chapter_files)

    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only shared-subscription migration scanner")
    parser.add_argument("--db-path", type=Path, default=DATA_DIR / "app.db")
    parser.add_argument("--novels-root", type=Path, default=DATA_DIR / "novels")
    parser.add_argument("--aggregate-book-id", default="")
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = scan_legacy_shared_subscription(
        db_path=args.db_path,
        novels_root=args.novels_root,
        aggregate_book_id=args.aggregate_book_id or None,
    )
    if args.pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
