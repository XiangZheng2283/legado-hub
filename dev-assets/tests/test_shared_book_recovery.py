from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.storage.db import initialize_database
from app.services.startup_library_scanner import scan_local_library
from scripts.migrate_shared_subscription_v1 import scan_legacy_shared_subscription


def _make_legacy_dir(novels_root: Path, folder_name: str, metadata: dict, chapter_files: dict[str, str]) -> Path:
    book_dir = novels_root / "legadohub" / folder_name
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    for name, content in chapter_files.items():
        (book_dir / name).write_text(content, encoding="utf-8", newline="\n")
    return book_dir


def _insert_book(db_path: Path, *, book_id: str, name: str, author: str, aggregate_payload: dict, **extra: object) -> None:
    fields = {
        "canonical_name": name,
        "canonical_author": author,
        "cover_url": extra.get("cover_url", ""),
        "intro": extra.get("intro", ""),
        "word_count": extra.get("word_count", ""),
        "primary_book_id": extra.get("primary_book_id", f"{extra.get('primary_source_id', 'official_src')}:{book_id}"),
        "primary_source_id": extra.get("primary_source_id", "official_src"),
        "primary_source_name": extra.get("primary_source_name", "Official Source"),
        "primary_book_url": extra.get("primary_book_url", "https://official.example/book"),
        "primary_toc_url": extra.get("primary_toc_url", "https://official.example/book/toc"),
        "start_chapter_index": int(extra.get("start_chapter_index", 1) or 1),
        "search_visibility_status": extra.get("search_visibility_status", "hidden"),
        "book_status": extra.get("book_status", "ongoing"),
        "status": extra.get("status", "active"),
        "last_check_time": extra.get("last_check_time", "2026-06-26T10:00:00+08:00"),
        "updated_at": extra.get("updated_at", "2026-06-26T10:05:00+08:00"),
        "created_at": extra.get("created_at", "2026-06-26T09:00:00+08:00"),
    }
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO aggregate_book_tasks (
                aggregate_book_id, canonical_name, canonical_author, name, author,
                cover_url, intro, word_count, aggregate_payload_json,
                primary_book_id, primary_source_id, primary_source_name,
                primary_book_url, primary_toc_url, start_chapter_index,
                search_visibility_status, book_status, status, last_check_time,
                updated_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                book_id,
                fields["canonical_name"],
                fields["canonical_author"],
                name,
                author,
                fields["cover_url"],
                fields["intro"],
                fields["word_count"],
                json.dumps(aggregate_payload, ensure_ascii=False),
                fields["primary_book_id"],
                fields["primary_source_id"],
                fields["primary_source_name"],
                fields["primary_book_url"],
                fields["primary_toc_url"],
                fields["start_chapter_index"],
                fields["search_visibility_status"],
                fields["book_status"],
                fields["status"],
                fields["last_check_time"],
                fields["updated_at"],
                fields["created_at"],
            ),
        )
        conn.commit()


def _insert_chapter(db_path: Path, *, chapter_id: str, aggregate_book_id: str, chapter_index: int, title: str, **extra: object) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO aggregate_chapter_tasks (
                chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title, status,
                source_word_count, preview_only, primary_source_chapter_url, processed_content,
                content_file_path, last_processed_at, policy_snapshot_json, source_snapshot_refs_json,
                ai_model, ai_prompt_tokens, ai_completion_tokens, ai_total_tokens, ai_latency_ms,
                deviation_score, ai_self_score, fallback_source_id, source_alignment_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chapter_id,
                aggregate_book_id,
                extra.get("source_chapter_id", f"official_src:chapter:{chapter_index}"),
                chapter_index,
                title,
                extra.get("status", "processed"),
                int(extra.get("source_word_count", 0) or 0),
                1 if extra.get("preview_only", False) else 0,
                extra.get("primary_source_chapter_url", ""),
                extra.get("processed_content", ""),
                extra.get("content_file_path", ""),
                extra.get("last_processed_at", "2026-06-26T10:10:00+08:00"),
                json.dumps(extra.get("policy_snapshot_json", {}), ensure_ascii=False) if extra.get("policy_snapshot_json") else "",
                json.dumps(extra.get("source_snapshot_refs_json", []), ensure_ascii=False) if extra.get("source_snapshot_refs_json") else "",
                extra.get("ai_model", ""),
                int(extra.get("ai_prompt_tokens", 0) or 0),
                int(extra.get("ai_completion_tokens", 0) or 0),
                int(extra.get("ai_total_tokens", 0) or 0),
                int(extra.get("ai_latency_ms", 0) or 0),
                float(extra.get("deviation_score", 0.0) or 0.0),
                float(extra.get("ai_self_score", 0.0) or 0.0),
                extra.get("fallback_source_id", ""),
                json.dumps(extra.get("source_alignment_json", {}), ensure_ascii=False) if extra.get("source_alignment_json") else "",
                extra.get("created_at", "2026-06-26T09:30:00+08:00"),
                extra.get("updated_at", "2026-06-26T10:10:00+08:00"),
            ),
        )
        conn.commit()


def test_read_only_scanner_recovers_complete_book(tmp_path: Path):
    db_path = tmp_path / "app.db"
    novels_root = tmp_path / "novels"
    initialize_database(db_path)

    legacy_book_id = "legacy-book-complete"
    folder_name = "完整小说_作者甲"
    legacy_dir = _make_legacy_dir(
        novels_root,
        folder_name,
        {
            "bookId": legacy_book_id,
            "bookName": "完整小说",
            "author": "作者甲",
            "coverUrl": "https://img.example/cover.jpg",
            "intro": "一本完整迁移的小说",
            "wordCount": "12万字",
            "createdAt": "2026-06-25T08:00:00+08:00",
        },
        {
            "000001 第一章 开端.md": "# 第一章 开端\n\n第一章正文\n",
            "000002 第二章 继续.md": "# 第二章 继续\n\n第二章正文\n",
        },
    )
    aggregate_payload = {
        "name": "完整小说",
        "author": "作者甲",
        "sources": [
            {
                "sourceId": "official_src",
                "sourceName": "官方源",
                "bookId": "official_src:book:1",
                "bookUrl": "https://official.example/book/1",
                "tocUrl": "https://official.example/book/1/toc",
                "score": 100,
            }
        ],
    }
    _insert_book(
        db_path,
        book_id=legacy_book_id,
        name="完整小说",
        author="作者甲",
        aggregate_payload=aggregate_payload,
        primary_source_id="official_src",
        primary_source_name="官方源",
        primary_book_url="https://official.example/book/1",
        primary_toc_url="https://official.example/book/1/toc",
        book_status="completed",
        search_visibility_status="visible",
    )
    _insert_chapter(
        db_path,
        chapter_id="legacy-book-complete:1",
        aggregate_book_id=legacy_book_id,
        chapter_index=1,
        title="第一章 开端",
        processed_content="第一章正文",
        content_file_path=str(legacy_dir / "000001 第一章 开端.md"),
        ai_model="gpt-test",
        ai_total_tokens=120,
        primary_source_chapter_url="https://official.example/book/1/1",
        source_alignment_json={"primarySourceId": "official_src", "selectedContentSource": "official"},
    )
    _insert_chapter(
        db_path,
        chapter_id="legacy-book-complete:2",
        aggregate_book_id=legacy_book_id,
        chapter_index=2,
        title="第二章 继续",
        processed_content="第二章正文",
        content_file_path=str(legacy_dir / "000002 第二章 继续.md"),
        ai_model="gpt-test",
        ai_total_tokens=98,
        primary_source_chapter_url="https://official.example/book/1/2",
        source_alignment_json={"primarySourceId": "official_src", "selectedContentSource": "official"},
    )

    result = scan_legacy_shared_subscription(db_path=db_path, novels_root=novels_root)

    assert result["summary"]["booksRecovered"] == 1
    assert result["summary"]["chaptersRecovered"] == 2
    assert not (tmp_path / "library").exists()

    book = result["books"][0]
    metadata = book["proposedFiles"]["metadata.json"]
    chapter_index = book["proposedFiles"]["chapter_index.json"]
    source_refs = book["proposedFiles"]["source_refs.json"]
    chapters = book["proposedFiles"]["chapters"]

    assert metadata["schemaVersion"] == 1
    assert metadata["candidateId"] == book["proposedBookId"]
    assert metadata["name"] == "完整小说"
    assert metadata["author"] == "作者甲"
    assert metadata["primarySourceId"] == "official_src"
    assert metadata["primarySourceName"] == "官方源"
    assert metadata["bookStatus"] == "completed"
    assert metadata["bookState"]["status"] == "completed"
    assert metadata["bookState"]["chapterCount"] == 2
    assert metadata["bookState"]["processedChapterCount"] == 2
    assert metadata["bookState"]["readableChapterCount"] == 2
    assert metadata["bookState"]["proofreadCompleteCount"] == 2
    assert metadata["sourceMapSummary"][0]["sourceId"] == "official_src"
    assert chapter_index["chapters"] == [
        {"index": 1, "title": "第一章 开端", "file": "chapters/0001-第一章 开端.md", "status": "proofread_complete"},
        {"index": 2, "title": "第二章 继续", "file": "chapters/0002-第二章 继续.md", "status": "proofread_complete"},
    ]
    assert source_refs["schemaVersion"] == 1
    assert source_refs["primary"]["sourceId"] == "official_src"
    assert source_refs["sources"][0]["bookUrl"] == "https://official.example/book/1"
    assert chapters[0]["content"].startswith("# 第一章 开端\n\n第一章正文")
    assert "<!-- LEGADOHUB_TRACE_BEGIN" in chapters[0]["content"]
    assert chapters[0]["trace"]["proofreadComplete"] is True
    assert chapters[0]["trace"]["aggregateBookId"] == legacy_book_id
    assert chapters[0]["trace"]["primarySourceId"] == "official_src"
    assert chapters[0]["trace"]["primarySourceUrl"] == "https://official.example/book/1/1"
    assert chapters[0]["trace"]["fetchedWordCount"] == len("第一章正文")
    assert chapters[0]["trace"]["aiModel"] == "gpt-test"
    assert chapters[0]["trace"]["aiTokens"] == 120


def test_read_only_scanner_marks_preview_heavy_chapters(tmp_path: Path):
    db_path = tmp_path / "app.db"
    novels_root = tmp_path / "novels"
    initialize_database(db_path)

    legacy_book_id = "legacy-book-preview"
    folder_name = "预览小说_作者乙"
    legacy_dir = _make_legacy_dir(
        novels_root,
        folder_name,
        {
            "bookId": legacy_book_id,
            "bookName": "预览小说",
            "author": "作者乙",
        },
        {
            "000001 第一章 试看.md": "# 第一章 试看\n\n试看正文片段\n",
            "000002 第二章 仍旧试看.md": "# 第二章 仍旧试看\n\n另一个试看片段\n",
        },
    )
    _insert_book(
        db_path,
        book_id=legacy_book_id,
        name="预览小说",
        author="作者乙",
        aggregate_payload={"name": "预览小说", "author": "作者乙", "sources": []},
        primary_source_id="official_src",
        primary_source_name="官方源",
    )
    _insert_chapter(
        db_path,
        chapter_id="legacy-book-preview:1",
        aggregate_book_id=legacy_book_id,
        chapter_index=1,
        title="第一章 试看",
        status="processed",
        processed_content="试看正文片段",
        content_file_path=str(legacy_dir / "000001 第一章 试看.md"),
        preview_only=True,
        source_word_count=321,
        primary_source_chapter_url="https://official.example/preview/1",
        source_alignment_json={"primarySourceId": "official_src", "selectedContentSource": "official"},
    )
    _insert_chapter(
        db_path,
        chapter_id="legacy-book-preview:2",
        aggregate_book_id=legacy_book_id,
        chapter_index=2,
        title="第二章 仍旧试看",
        status="pending",
        processed_content="另一个试看片段",
        content_file_path=str(legacy_dir / "000002 第二章 仍旧试看.md"),
        preview_only=True,
        source_word_count=287,
        primary_source_chapter_url="https://official.example/preview/2",
        source_alignment_json={"primarySourceId": "official_src", "selectedContentSource": "official"},
    )

    result = scan_legacy_shared_subscription(db_path=db_path, novels_root=novels_root)

    book = result["books"][0]
    metadata = book["proposedFiles"]["metadata.json"]
    chapter_index = book["proposedFiles"]["chapter_index.json"]["chapters"]
    chapters = book["proposedFiles"]["chapters"]

    assert metadata["bookState"]["previewChapterCount"] == 2
    assert chapter_index[0]["status"] == "supplemented"
    assert chapter_index[1]["status"] == "fetched"
    assert chapters[0]["trace"]["previewOnly"] is True
    assert chapters[1]["trace"]["previewOnly"] is True
    assert chapters[0]["trace"]["primarySource"]["wordCount"] == 321


def test_read_only_scanner_keeps_third_party_fallback_refs(tmp_path: Path):
    db_path = tmp_path / "app.db"
    novels_root = tmp_path / "novels"
    initialize_database(db_path)

    legacy_book_id = "legacy-book-fallback"
    folder_name = "补源小说_作者丙"
    legacy_dir = _make_legacy_dir(
        novels_root,
        folder_name,
        {
            "bookId": legacy_book_id,
            "bookName": "补源小说",
            "author": "作者丙",
        },
        {
            "000001 第一章 借力补全.md": "# 第一章 借力补全\n\n第三方补全后的正文\n",
        },
    )
    aggregate_payload = {
        "name": "补源小说",
        "author": "作者丙",
        "sources": [
            {
                "sourceId": "official_src",
                "sourceName": "官方源",
                "bookId": "official_src:book:3",
                "bookUrl": "https://official.example/book/3",
                "tocUrl": "https://official.example/book/3/toc",
                "score": 100,
            },
            {
                "sourceId": "third_src",
                "sourceName": "第三方源",
                "bookId": "third_src:book:3",
                "bookUrl": "https://third.example/book/3",
                "tocUrl": "https://third.example/book/3/toc",
                "score": 87,
            },
        ],
    }
    _insert_book(
        db_path,
        book_id=legacy_book_id,
        name="补源小说",
        author="作者丙",
        aggregate_payload=aggregate_payload,
        primary_source_id="official_src",
        primary_source_name="官方源",
    )
    _insert_chapter(
        db_path,
        chapter_id="legacy-book-fallback:1",
        aggregate_book_id=legacy_book_id,
        chapter_index=1,
        title="第一章 借力补全",
        status="fallback",
        processed_content="第三方补全后的正文",
        content_file_path=str(legacy_dir / "000001 第一章 借力补全.md"),
        fallback_source_id="third_src",
        primary_source_chapter_url="https://official.example/book/3/1",
        source_alignment_json={
            "primarySourceId": "official_src",
            "candidateSourceId": "third_src",
            "selectedContentSource": "candidate",
            "alignmentPassed": True,
        },
        source_snapshot_refs_json=[
            {"sourceId": "official_src", "snapshotId": "snap-official-1"},
            {"sourceId": "third_src", "snapshotId": "snap-third-1"},
        ],
    )

    result = scan_legacy_shared_subscription(db_path=db_path, novels_root=novels_root)

    book = result["books"][0]
    chapter_entry = book["proposedFiles"]["chapter_index.json"]["chapters"][0]
    chapter_file = book["proposedFiles"]["chapters"][0]
    source_refs = book["proposedFiles"]["source_refs.json"]

    assert chapter_entry["status"] == "readable"
    assert chapter_file["trace"]["supplementSource"]["sourceId"] == "third_src"
    assert chapter_file["trace"]["selectedContentSource"] == "candidate"
    assert chapter_file["trace"]["sourceSnapshotRefs"][1]["snapshotId"] == "snap-third-1"
    assert {item["sourceId"] for item in source_refs["sources"]} == {"official_src", "third_src"}


def test_read_only_scanner_ignores_out_of_root_db_file_hints(tmp_path: Path):
    db_path = tmp_path / "app.db"
    novels_root = tmp_path / "novels"
    outside_root = tmp_path / "outside"
    initialize_database(db_path)
    outside_root.mkdir(parents=True, exist_ok=True)

    legacy_book_id = "legacy-book-guarded"
    folder_name = "边界小说_作者丁"
    _make_legacy_dir(
        novels_root,
        folder_name,
        {
            "bookId": legacy_book_id,
            "bookName": "边界小说",
            "author": "作者丁",
        },
        {
            "000001 第一章 边界内文件.md": "# 第一章 边界内文件\n\n来自根目录内的正文\n",
        },
    )
    outside_file = outside_root / "000001 第一章 边界外文件.md"
    outside_file.write_text("# 第一章 边界外文件\n\n来自根目录外的正文\n", encoding="utf-8", newline="\n")

    _insert_book(
        db_path,
        book_id=legacy_book_id,
        name="边界小说",
        author="作者丁",
        aggregate_payload={"name": "边界小说", "author": "作者丁", "sources": []},
        primary_source_id="official_src",
        primary_source_name="官方源",
    )
    _insert_chapter(
        db_path,
        chapter_id="legacy-book-guarded:1",
        aggregate_book_id=legacy_book_id,
        chapter_index=1,
        title="第一章 边界内文件",
        processed_content="来自 processed_content 的回退正文",
        content_file_path=str(outside_file),
        source_alignment_json={"primarySourceId": "official_src", "selectedContentSource": "official"},
    )

    result = scan_legacy_shared_subscription(db_path=db_path, novels_root=novels_root)

    book = result["books"][0]
    chapter = book["proposedFiles"]["chapters"][0]

    assert "来自根目录外的正文" not in chapter["content"]
    assert "来自根目录内的正文" in chapter["content"]
    assert any("ignored out-of-root path hint" in item for item in result["warnings"])
    assert any("ignored out-of-root path hint" in item for item in book["warnings"])


def test_read_only_scanner_collects_json_parse_warnings(tmp_path: Path):
    db_path = tmp_path / "app.db"
    novels_root = tmp_path / "novels"
    initialize_database(db_path)

    legacy_book_id = "legacy-book-bad-json"
    legacy_dir = _make_legacy_dir(
        novels_root,
        "损坏JSON小说_作者戊",
        {
            "bookId": legacy_book_id,
            "bookName": "损坏JSON小说",
            "author": "作者戊",
        },
        {
            "000001 第一章 JSON告警.md": "# 第一章 JSON告警\n\n正文\n",
        },
    )
    _insert_book(
        db_path,
        book_id=legacy_book_id,
        name="损坏JSON小说",
        author="作者戊",
        aggregate_payload={"name": "损坏JSON小说", "author": "作者戊", "sources": []},
        primary_source_id="official_src",
        primary_source_name="官方源",
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO aggregate_chapter_tasks (
                chapter_id, aggregate_book_id, source_chapter_id, chapter_index, title, status,
                processed_content, content_file_path, source_alignment_json, policy_snapshot_json,
                source_snapshot_refs_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-book-bad-json:1",
                legacy_book_id,
                "official_src:chapter:1",
                1,
                "第一章 JSON告警",
                "processed",
                "正文",
                str(legacy_dir / "000001 第一章 JSON告警.md"),
                "{bad json",
                "{still bad",
                "[oops",
                "2026-06-26T09:00:00+08:00",
                "2026-06-26T10:00:00+08:00",
            ),
        )
        conn.commit()

    result = scan_legacy_shared_subscription(db_path=db_path, novels_root=novels_root)

    assert any("failed to parse JSON" in item for item in result["warnings"])
    assert len(result["books"][0]["warnings"]) >= 3


def test_read_only_scanner_recovers_trace_data_from_existing_chapter_payload(tmp_path: Path):
    db_path = tmp_path / "app.db"
    novels_root = tmp_path / "novels"
    initialize_database(db_path)

    legacy_book_id = "legacy-book-payload-trace"
    legacy_dir = _make_legacy_dir(
        novels_root,
        "章节载荷小说_作者己",
        {
            "bookId": legacy_book_id,
            "bookName": "章节载荷小说",
            "author": "作者己",
        },
        {
            "000001 第一章 载荷恢复.md": (
                "# 第一章 载荷恢复\n\n章节正文\n\n"
                "<!-- LEGADOHUB_TRACE_BEGIN\n"
                "{\n"
                '  "schemaVersion": 1,\n'
                '  "processedAt": "2026-06-26T12:30:00+08:00",\n'
                '  "selectedContentSource": "candidate",\n'
                '  "sourceSnapshotRefs": [{"sourceId": "payload_src", "snapshotId": "snap-payload-1"}],\n'
                '  "supplementSource": {"sourceId": "payload_src", "selected": true}\n'
                "}\n"
                "LEGADOHUB_TRACE_END -->\n"
            ),
        },
    )
    _insert_book(
        db_path,
        book_id=legacy_book_id,
        name="章节载荷小说",
        author="作者己",
        aggregate_payload={"name": "章节载荷小说", "author": "作者己", "sources": []},
        primary_source_id="official_src",
        primary_source_name="官方源",
    )
    _insert_chapter(
        db_path,
        chapter_id="legacy-book-payload-trace:1",
        aggregate_book_id=legacy_book_id,
        chapter_index=1,
        title="第一章 载荷恢复",
        status="processed",
        processed_content="章节正文",
        content_file_path=str(legacy_dir / "000001 第一章 载荷恢复.md"),
        primary_source_chapter_url="https://official.example/book/payload/1",
    )

    result = scan_legacy_shared_subscription(db_path=db_path, novels_root=novels_root)

    trace = result["books"][0]["proposedFiles"]["chapters"][0]["trace"]
    assert trace["selectedContentSource"] == "candidate"
    assert trace["processedAt"] == "2026-06-26T12:30:00+08:00"
    assert trace["supplementSource"]["sourceId"] == "payload_src"
    assert trace["sourceSnapshotRefs"][0]["snapshotId"] == "snap-payload-1"


def test_startup_scanner_marks_future_schema_as_readonly(tmp_path: Path):
    db_path = tmp_path / "app.db"
    novels_root = tmp_path / "novels"
    library_root = tmp_path / "library"
    initialize_database(db_path)

    book_dir = library_root / "未来版本小说_作者庚"
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "metadata.json").write_text(
        json.dumps(
            {
                "schemaVersion": 99,
                "candidateId": "future-book",
                "name": "未来版本小说",
                "author": "作者庚",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
        newline="\n",
    )

    result = scan_local_library(db_path=db_path, novels_root=novels_root, library_root=library_root)

    assert result["readonly"] == 1
    guard = result["sharedGuards"][0]
    assert guard["mode"] == "readonly"
    assert guard["state"] == "readonly"
    assert guard["reason"] == "unsupported_schema_version"
    assert guard["schemaVersion"] == 99
    assert guard["repairNeeded"] is False


def test_startup_scanner_marks_malformed_metadata_as_repair_needed(tmp_path: Path):
    db_path = tmp_path / "app.db"
    novels_root = tmp_path / "novels"
    library_root = tmp_path / "library"
    initialize_database(db_path)

    book_dir = library_root / "损坏元数据小说_作者辛"
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "metadata.json").write_text("{bad json", encoding="utf-8", newline="\n")

    result = scan_local_library(db_path=db_path, novels_root=novels_root, library_root=library_root)

    assert result["corrupted"] == 1
    guard = result["sharedGuards"][0]
    assert guard["mode"] == "readonly"
    assert guard["state"] == "corrupted"
    assert guard["reason"] == "invalid_metadata_json"
    assert guard["repairNeeded"] is True
