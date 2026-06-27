from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services.library_books import LibraryBooksService
from app.services import shared_book_storage as shared_book_storage_module
from app.services.shared_book_storage import SharedBookStorage
from app.storage.db import initialize_database


def _insert_library_book(
    db_path: Path,
    *,
    aggregate_book_id: str,
    name: str = "测试小说",
    author: str = "作者甲",
    visible_processed_chapters: int,
    processed_chapters: int | None = None,
    search_visibility_status: str = "visible",
    status: str = "active",
):
    initialize_database(db_path)
    service = LibraryBooksService(db_path=db_path)
    with service._conn() as conn:
        conn.execute(
            """
            INSERT INTO aggregate_book_tasks (
                aggregate_book_id, canonical_name, canonical_author, name, author,
                aggregate_payload_json, primary_book_id, primary_source_id,
                search_visibility_status, processed_chapters, visible_processed_chapters,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                aggregate_book_id,
                service._canonical_name(name),
                service._canonical_author(author),
                name,
                author,
                "src-a:book-1",
                "src-a",
                search_visibility_status,
                visible_processed_chapters if processed_chapters is None else processed_chapters,
                visible_processed_chapters,
                status,
            ),
        )
        conn.commit()


def _patch_discovery_threshold(monkeypatch: pytest.MonkeyPatch, threshold: int):
    monkeypatch.setattr(
        "app.services.library_books.AggregateSettingsRepository.content_workflow",
        lambda self: {"minReadableChaptersForDiscovery": threshold},
    )


def test_shared_book_storage_resolves_expected_paths(tmp_path: Path):
    storage = SharedBookStorage(tmp_path / "library")

    shared_dir = storage.shared_book_dir(book_name="测试小说", author="作者甲")

    assert shared_dir == tmp_path / "library" / "测试小说_作者甲"
    assert storage.metadata_path(book_name="测试小说", author="作者甲") == shared_dir / "metadata.json"
    assert storage.chapter_index_path(book_name="测试小说", author="作者甲") == shared_dir / "chapter_index.json"
    assert storage.chapters_dir(book_name="测试小说", author="作者甲") == shared_dir / "chapters"
    assert (
        storage.chapter_markdown_path(
            book_name="测试小说",
            author="作者甲",
            chapter_index=12,
            title="第12章 / 试读",
        )
        == shared_dir / "chapters" / "0012-第12章 _ 试读.md"
    )
    assert storage.runtime_dir(book_name="测试小说", author="作者甲") == shared_dir / "runtime"
    assert storage.logs_dir(book_name="测试小说", author="作者甲") == shared_dir / "logs"
    assert storage.source_refs_path(book_name="测试小说", author="作者甲") == shared_dir / "source_refs.json"


def test_shared_book_storage_atomic_write_json(tmp_path: Path):
    storage = SharedBookStorage(tmp_path / "library")
    target = storage.metadata_path(book_name="测试小说", author="作者甲")

    storage.atomic_write_json(target, {"bookId": "book-1", "chapterCount": 3})

    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == {"bookId": "book-1", "chapterCount": 3}
    assert list(target.parent.glob("metadata.json.*.tmp")) == []


def test_shared_book_storage_atomic_write_json_repeated_writes_replace_content(tmp_path: Path):
    storage = SharedBookStorage(tmp_path / "library")
    target = storage.metadata_path(book_name="测试小说", author="作者甲")

    storage.atomic_write_json(target, {"bookId": "book-1", "chapterCount": 3})
    storage.atomic_write_json(target, {"bookId": "book-1", "chapterCount": 4, "status": "updated"})

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "bookId": "book-1",
        "chapterCount": 4,
        "status": "updated",
    }
    assert list(target.parent.glob("metadata.json.*.tmp")) == []


def test_shared_book_storage_atomic_write_json_uses_unique_temp_file_per_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    storage = SharedBookStorage(tmp_path / "library")
    target = storage.metadata_path(book_name="测试小说", author="作者甲")
    generated_temp_paths: list[Path] = []
    original_replace = shared_book_storage_module.os.replace

    class _FakeUuid:
        def __init__(self, hex_value: str):
            self.hex = hex_value

    uuid_values = iter([_FakeUuid("tempA"), _FakeUuid("tempB")])

    def fake_uuid4():
        return next(uuid_values)

    def recording_replace(src: Path | str, dst: Path | str):
        generated_temp_paths.append(Path(src))
        return original_replace(src, dst)

    monkeypatch.setattr(shared_book_storage_module.uuid, "uuid4", fake_uuid4)
    monkeypatch.setattr(shared_book_storage_module.os, "replace", recording_replace)

    storage.atomic_write_json(target, {"bookId": "book-1", "chapterCount": 1})
    storage.atomic_write_json(target, {"bookId": "book-1", "chapterCount": 2})

    assert generated_temp_paths == [
        target.with_name("metadata.json.tempA.tmp"),
        target.with_name("metadata.json.tempB.tmp"),
    ]
    assert all(path != target.with_name("metadata.json.tmp") for path in generated_temp_paths)


def test_shared_book_storage_atomic_write_markdown(tmp_path: Path):
    storage = SharedBookStorage(tmp_path / "library")
    target = storage.chapter_markdown_path(
        book_name="测试小说",
        author="作者甲",
        chapter_index=1,
        title="第一章 开始",
    )

    storage.atomic_write_markdown(target, "# 第一章 开始\r\n\r\n正文")

    assert target.exists()
    assert target.read_text(encoding="utf-8") == "# 第一章 开始\n\n正文\n"
    assert list(target.parent.glob("0001-第一章 开始.md.*.tmp")) == []


def test_shared_book_storage_metadata_excludes_private_source_urls():
    storage = SharedBookStorage()
    payload = {
        "candidateId": "cand-1",
        "name": "测试小说",
        "author": "作者甲",
        "coverUrl": "https://img.example/cover.jpg",
        "intro": "简介",
        "bookStatus": "ongoing",
        "totalChaptersAtSubscribe": 12,
        "primaryBookId": "src-a:book-1",
        "primarySourceId": "src-a",
        "primarySourceName": "来源A",
        "primaryBookUrl": "https://private.example/book/1",
        "primaryTocUrl": "https://private.example/book/1/toc",
        "sources": [
            {
                "bookId": "src-a:book-1",
                "sourceId": "src-a",
                "sourceName": "来源A",
                "bookUrl": "https://private.example/book/1",
                "tocUrl": "https://private.example/book/1/toc",
                "score": 100,
                "lastChapter": "第12章",
                "coverUrl": "https://img.example/cover.jpg",
                "intro": "简介",
                "wordCount": "10万字",
                "chapterCount": 12,
                "bookStatus": "ongoing",
                "author": "作者甲",
                "name": "测试小说",
            },
            {
                "bookId": "src-b:book-9",
                "sourceId": "src-b",
                "sourceName": "来源B",
                "bookUrl": "https://third.example/book/9",
                "tocUrl": "https://third.example/book/9/toc",
                "score": 88,
                "lastChapter": "第11章",
                "chapterCount": 11,
                "bookStatus": "ongoing",
                "author": "作者甲",
                "name": "测试小说",
            },
        ],
    }

    metadata = storage.build_shared_metadata(payload)

    assert metadata["primaryBookId"] == "src-a:book-1"
    assert metadata["primarySourceId"] == "src-a"
    assert metadata["primarySourceName"] == "来源A"
    assert "primaryBookUrl" not in metadata
    assert "primaryTocUrl" not in metadata
    assert metadata["sourceMapSummary"] == [
        {
            "bookId": "src-a:book-1",
            "sourceId": "src-a",
            "sourceName": "来源A",
            "score": 100,
            "lastChapter": "第12章",
            "chapterCount": 12,
            "bookStatus": "ongoing",
            "author": "作者甲",
            "name": "测试小说",
        },
        {
            "bookId": "src-b:book-9",
            "sourceId": "src-b",
            "sourceName": "来源B",
            "score": 88,
            "lastChapter": "第11章",
            "chapterCount": 11,
            "bookStatus": "ongoing",
            "author": "作者甲",
            "name": "测试小说",
        },
    ]
    assert "bookUrl" not in json.dumps(metadata, ensure_ascii=False)
    assert "tocUrl" not in json.dumps(metadata, ensure_ascii=False)


def test_shared_book_storage_source_refs_include_private_source_urls():
    storage = SharedBookStorage()
    payload = {
        "primaryBookId": "src-a:book-1",
        "primarySourceId": "src-a",
        "primaryBookUrl": "https://private.example/book/1",
        "primaryTocUrl": "https://private.example/book/1/toc",
        "sources": [
            {
                "bookId": "src-a:book-1",
                "sourceId": "src-a",
                "sourceName": "来源A",
                "bookUrl": "https://private.example/book/1",
                "tocUrl": "https://private.example/book/1/toc",
            },
            {
                "bookId": "src-b:book-9",
                "sourceId": "src-b",
                "sourceName": "来源B",
                "bookUrl": "https://third.example/book/9",
                "tocUrl": "https://third.example/book/9/toc",
            },
        ],
    }

    refs = storage.build_private_source_refs(payload)

    assert refs == {
        "primary": {
            "sourceId": "src-a",
            "bookId": "src-a:book-1",
            "bookUrl": "https://private.example/book/1",
            "tocUrl": "https://private.example/book/1/toc",
        },
        "sources": [
            {
                "sourceId": "src-a",
                "sourceName": "来源A",
                "bookId": "src-a:book-1",
                "bookUrl": "https://private.example/book/1",
                "tocUrl": "https://private.example/book/1/toc",
            },
            {
                "sourceId": "src-b",
                "sourceName": "来源B",
                "bookId": "src-b:book-9",
                "bookUrl": "https://third.example/book/9",
                "tocUrl": "https://third.example/book/9/toc",
            },
        ],
    }


def test_library_books_source_map_summary_reads_shared_metadata_only():
    service = LibraryBooksService(db_path=":memory:")
    shared_metadata = {
        "sourceMapSummary": [
            {
                "bookId": "src-a:book-1",
                "sourceId": "src-a",
                "sourceName": "来源A",
                "score": 100,
                "chapterCount": 12,
                "lastChapter": "第12章",
                "bookStatus": "ongoing",
                "name": "测试小说",
                "author": "作者甲",
            }
        ],
        "primaryBookUrl": "https://private.example/book/1",
        "primaryTocUrl": "https://private.example/book/1/toc",
    }

    summary = service.build_source_map_summary(shared_metadata)

    assert summary == [
        {
            "bookId": "src-a:book-1",
            "sourceId": "src-a",
            "sourceName": "来源A",
            "score": 100,
            "chapterCount": 12,
            "lastChapter": "第12章",
            "bookStatus": "ongoing",
            "name": "测试小说",
            "author": "作者甲",
        }
    ]
    assert "bookUrl" not in json.dumps(summary, ensure_ascii=False)
    assert "tocUrl" not in json.dumps(summary, ensure_ascii=False)


def test_shared_book_storage_parse_trace_block_success():
    storage = SharedBookStorage()
    markdown = """# 第一章

正文

<!-- LEGADOHUB_TRACE_BEGIN
{"chapterId":"c1","proofreadComplete":true,"score":9}
LEGADOHUB_TRACE_END -->
"""

    trace = storage.parse_trace_block(markdown)

    assert trace == {"chapterId": "c1", "proofreadComplete": True, "score": 9}


def test_shared_book_storage_parse_trace_block_success_with_nested_json():
    storage = SharedBookStorage()
    markdown = """# 第一章

正文

<!-- LEGADOHUB_TRACE_BEGIN -->
{
  "chapterId": "c1",
  "details": {
    "source": {
      "name": "alpha",
      "meta": {"depth": 2}
    },
    "snippet": "brace text: {not json}"
  }
}
<!-- LEGADOHUB_TRACE_END -->
"""

    trace = storage.parse_trace_block(markdown)

    assert trace == {
        "chapterId": "c1",
        "details": {
            "source": {
                "name": "alpha",
                "meta": {"depth": 2},
            },
            "snippet": "brace text: {not json}",
        },
    }


@pytest.mark.parametrize(
    "markdown, expected_message",
    [
        ("# 第一章\n\n正文\n", "markers not found"),
        (
            "# 第一章\n\n<!-- LEGADOHUB_TRACE_BEGIN\n{bad json}\nLEGADOHUB_TRACE_END -->\n",
            "invalid JSON",
        ),
        (
            "# 第一章\n\nLEGADOHUB_TRACE_BEGIN\n[]\nLEGADOHUB_TRACE_END\n",
            "JSON object",
        ),
    ],
)
def test_shared_book_storage_parse_trace_block_failure(markdown: str, expected_message: str):
    storage = SharedBookStorage()

    with pytest.raises(ValueError, match=expected_message):
        storage.parse_trace_block(markdown)


def test_shared_book_storage_rebuild_book_state_from_files_counts_statuses():
    storage = SharedBookStorage()
    chapter_index = {
        "chapters": [
            {"index": 1, "title": "第一章", "file": "chapters/0001-第一章.md", "status": "proofread_complete"},
            {"index": 2, "title": "第二章", "file": "chapters/0002-第二章.md", "status": "supplemented"},
            {"index": 3, "title": "第三章", "file": "chapters/0003-第三章.md", "status": "readable"},
            {"index": 4, "title": "第四章", "file": "chapters/0004-第四章.md", "status": "suspect"},
            {"index": 5, "title": "第五章", "file": "chapters/0005-第五章.md", "status": "failed"},
            {"index": 6, "title": "第六章", "file": "chapters/0006-第六章.md", "status": "fetched"},
        ]
    }
    chapter_traces = {
        2: {"chapterIndex": 2, "chapterStatus": "supplemented", "previewOnly": True},
        6: {"chapterIndex": 6, "chapterStatus": "fetched", "previewOnly": True},
    }
    existing_state = {
        "status": "active",
        "searchVisibilityStatus": "visible",
        "lastUpdateCheckAt": "2026-06-26T12:00:00+08:00",
    }

    rebuilt = storage.rebuild_book_state_from_files(
        chapter_index_payload=chapter_index,
        chapter_traces=chapter_traces,
        existing_state=existing_state,
    )

    assert rebuilt == {
        "status": "active",
        "searchVisibilityStatus": "visible",
        "chapterCount": 6,
        "processedChapterCount": 4,
        "readableChapterCount": 4,
        "previewChapterCount": 2,
        "proofreadCompleteCount": 1,
        "suspectChapterCount": 1,
        "failedChapterCount": 1,
        "latestChapterIndex": 6,
        "latestChapterTitle": "第六章",
        "lastUpdateCheckAt": "2026-06-26T12:00:00+08:00",
    }


def test_shared_book_storage_rebuild_book_state_suspect_falls_back_to_trace_when_index_missing():
    storage = SharedBookStorage()
    chapter_index = {
        "chapters": [
            {"index": 1, "title": "第一章", "file": "chapters/0001-第一章.md", "status": ""},
            {"index": 2, "title": "第二章", "file": "chapters/0002-第二章.md"},
        ]
    }
    chapter_traces = {
        1: {"chapterIndex": 1, "chapterStatus": "suspect"},
        2: {"chapterIndex": 2, "chapterStatus": "proofread_complete"},
    }

    rebuilt = storage.rebuild_book_state_from_files(
        chapter_index_payload=chapter_index,
        chapter_traces=chapter_traces,
        existing_state={},
    )

    assert rebuilt["suspectChapterCount"] == 1
    assert rebuilt["processedChapterCount"] == 2
    assert rebuilt["readableChapterCount"] == 2
    assert rebuilt["proofreadCompleteCount"] == 1


def test_shared_book_storage_detects_and_repairs_book_state_drift():
    storage = SharedBookStorage()
    metadata = {
        "name": "测试小说",
        "author": "作者甲",
        "bookState": {
            "status": "active",
            "searchVisibilityStatus": "hidden",
            "chapterCount": 9,
            "processedChapterCount": 99,
            "readableChapterCount": 88,
            "previewChapterCount": 77,
            "proofreadCompleteCount": 66,
            "suspectChapterCount": 55,
            "failedChapterCount": 44,
            "latestChapterIndex": 999,
            "latestChapterTitle": "旧标题",
            "lastUpdateCheckAt": "2026-06-26T12:00:00+08:00",
        },
    }
    chapter_index = {
        "chapters": [
            {"index": 1, "title": "第一章", "file": "chapters/0001-第一章.md", "status": "proofread_complete"},
            {"index": 2, "title": "第二章", "file": "chapters/0002-第二章.md", "status": "failed"},
        ]
    }
    chapter_traces = {
        1: {"chapterIndex": 1, "chapterStatus": "proofread_complete"},
        2: {"chapterIndex": 2, "chapterStatus": "failed"},
    }

    assert storage.book_state_needs_rebuild(
        metadata_payload=metadata,
        chapter_index_payload=chapter_index,
        chapter_traces=chapter_traces,
    ) is True

    repaired = storage.rebuild_metadata_summary(
        metadata,
        chapter_index_payload=chapter_index,
        chapter_traces=chapter_traces,
    )

    assert repaired["bookState"] == {
        "status": "active",
        "searchVisibilityStatus": "hidden",
        "chapterCount": 2,
        "processedChapterCount": 1,
        "readableChapterCount": 1,
        "previewChapterCount": 0,
        "proofreadCompleteCount": 1,
        "suspectChapterCount": 0,
        "failedChapterCount": 1,
        "latestChapterIndex": 2,
        "latestChapterTitle": "第二章",
        "lastUpdateCheckAt": "2026-06-26T12:00:00+08:00",
    }


def test_shared_book_storage_write_book_bundle_writes_chapter_then_index_then_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    storage = SharedBookStorage(tmp_path / "library")
    metadata_path = storage.metadata_path(book_name="测试小说", author="作者甲")
    chapter_index_path = storage.chapter_index_path(book_name="测试小说", author="作者甲")
    chapter_file_path = storage.chapter_markdown_path(
        book_name="测试小说",
        author="作者甲",
        chapter_index=1,
        title="第一章",
    )

    metadata_payload = {
        "name": "测试小说",
        "author": "作者甲",
        "bookState": {
            "status": "active",
            "searchVisibilityStatus": "visible",
            "chapterCount": 0,
            "processedChapterCount": 0,
            "readableChapterCount": 0,
            "previewChapterCount": 0,
            "proofreadCompleteCount": 0,
            "suspectChapterCount": 0,
            "failedChapterCount": 0,
        },
    }
    chapter_index_payload = {
        "chapters": [
            {"index": 1, "title": "第一章", "file": "chapters/0001-第一章.md", "status": "suspect"},
        ]
    }
    chapter_markdown = """# 第一章

正文

<!-- LEGADOHUB_TRACE_BEGIN
{"chapterIndex":1,"chapterStatus":"suspect","previewOnly":false}
LEGADOHUB_TRACE_END -->
"""
    write_order: list[str] = []
    original_markdown_write = storage.atomic_write_markdown
    original_json_write = storage.atomic_write_json

    def record_markdown(path: Path, text: str):
        write_order.append(path.name)
        return original_markdown_write(path, text)

    def record_json(path: Path, payload: dict[str, object] | list[object]):
        write_order.append(path.name)
        return original_json_write(path, payload)

    monkeypatch.setattr(storage, "atomic_write_markdown", record_markdown)
    monkeypatch.setattr(storage, "atomic_write_json", record_json)

    rebuilt_metadata = storage.write_book_bundle(
        metadata_path=metadata_path,
        metadata_payload=metadata_payload,
        chapter_index_path=chapter_index_path,
        chapter_index_payload=chapter_index_payload,
        chapter_files=[(chapter_file_path, chapter_markdown)],
    )

    assert write_order == [
        "0001-第一章.md",
        "chapter_index.json",
        "metadata.json",
    ]
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["bookState"]["suspectChapterCount"] == 1
    assert rebuilt_metadata["bookState"]["processedChapterCount"] == 1


def test_library_books_book_state_summary_reads_shared_metadata_only():
    service = LibraryBooksService(db_path=":memory:")
    shared_metadata = {
        "bookState": {
            "status": "active",
            "searchVisibilityStatus": "visible",
            "chapterCount": 3,
            "processedChapterCount": 2,
            "readableChapterCount": 2,
            "previewChapterCount": 1,
            "proofreadCompleteCount": 1,
            "suspectChapterCount": 1,
            "failedChapterCount": 0,
            "latestChapterIndex": 3,
            "latestChapterTitle": "第三章",
            "lastUpdateCheckAt": "2026-06-26T12:30:00+08:00",
        },
        "primaryBookUrl": "https://private.example/book/1",
    }

    summary = service.build_book_state_summary(shared_metadata)

    assert summary == {
        "status": "active",
        "searchVisibilityStatus": "visible",
        "chapterCount": 3,
        "processedChapterCount": 2,
        "readableChapterCount": 2,
        "previewChapterCount": 1,
        "proofreadCompleteCount": 1,
        "suspectChapterCount": 1,
        "failedChapterCount": 0,
        "latestChapterIndex": 3,
        "latestChapterTitle": "第三章",
        "lastUpdateCheckAt": "2026-06-26T12:30:00+08:00",
    }


def test_library_books_injected_search_hidden_below_discovery_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    db_path = tmp_path / "library.db"
    _insert_library_book(
        db_path,
        aggregate_book_id="book-hidden",
        visible_processed_chapters=49,
        processed_chapters=80,
        search_visibility_status="visible",
    )
    _patch_discovery_threshold(monkeypatch, 50)

    service = LibraryBooksService(db_path=db_path)

    items = service.build_search_injected_items_for_keyword("测试小说", min_readable_chapters=50)

    assert items == []


def test_library_books_injected_search_visible_at_discovery_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    db_path = tmp_path / "library.db"
    _insert_library_book(
        db_path,
        aggregate_book_id="book-visible",
        visible_processed_chapters=50,
        processed_chapters=80,
        search_visibility_status="hidden",
    )
    _patch_discovery_threshold(monkeypatch, 50)

    service = LibraryBooksService(db_path=db_path)

    items = service.build_search_injected_items_for_keyword("测试小说", min_readable_chapters=50)

    assert len(items) == 1
    assert items[0]["aggregateBookId"] == "book-visible"
    assert items[0]["visibleProcessedChapters"] == 50


def test_library_books_injected_search_visible_with_raised_configured_threshold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    db_path = tmp_path / "library.db"
    _insert_library_book(
        db_path,
        aggregate_book_id="book-raised-threshold",
        visible_processed_chapters=75,
        processed_chapters=120,
        search_visibility_status="visible",
    )
    _patch_discovery_threshold(monkeypatch, 75)

    service = LibraryBooksService(db_path=db_path)

    assert service.discovery_min_readable_chapters() == 75
    items = service.build_search_injected_items_for_keyword("测试小说")

    assert len(items) == 1
    assert items[0]["aggregateBookId"] == "book-raised-threshold"


def test_atomic_write_leaves_original_intact_on_crash_before_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Simulate a crash during chapter write before os.replace; original file must remain valid."""
    storage = SharedBookStorage(tmp_path / "library")
    target = storage.chapter_markdown_path(
        book_name="测试小说",
        author="作者甲",
        chapter_index=1,
        title="第一章 开始",
    )
    original_text = "# 第一章 开始\n\n原始正文\n"
    storage.atomic_write_markdown(target, original_text)

    def crashing_replace(src: Path | str, dst: Path | str) -> None:
        raise OSError("simulate crash before replace")

    monkeypatch.setattr(shared_book_storage_module.os, "replace", crashing_replace)

    with pytest.raises(OSError, match="simulate crash before replace"):
        storage.atomic_write_markdown(target, "# 第一章 开始\n\n新正文\n")

    assert target.exists()
    assert target.read_text(encoding="utf-8") == original_text
    tmp_files = list(target.parent.glob("0001-第一章 开始.md.*.tmp"))
    assert len(tmp_files) == 1


def test_cleanup_tmp_files_removes_stale_temp_files(tmp_path: Path):
    """Cleanup should remove leftover .tmp files without touching valid target files."""
    storage = SharedBookStorage(tmp_path / "library")
    target = storage.chapter_markdown_path(
        book_name="测试小说",
        author="作者甲",
        chapter_index=1,
        title="第一章 开始",
    )
    storage.atomic_write_markdown(target, "# 第一章 开始\n\n正文\n")

    stale_tmp = target.with_name("0001-第一章 开始.md.deadbeef.tmp")
    stale_tmp.write_text("stale", encoding="utf-8")
    other_tmp = target.parent / "other.md.12345678.tmp"
    other_tmp.write_text("other", encoding="utf-8")

    storage.cleanup_tmp_files(book_name="测试小说", author="作者甲")

    assert target.exists()
    assert not stale_tmp.exists()
    assert not other_tmp.exists()


def test_cleanup_tmp_files_detects_broken_chapter_and_reports(tmp_path: Path):
    """A chapter file whose trace block is malformed should be reported, not treated as valid."""
    storage = SharedBookStorage(tmp_path / "library")
    chapter_dir = storage.chapters_dir(book_name="测试小说", author="作者甲")
    chapter_dir.mkdir(parents=True, exist_ok=True)
    broken_chapter = chapter_dir / "0001-第一章.md"
    broken_chapter.write_text("# 第一章\n\n正文\n\n<!-- LEGADOHUB_TRACE_BEGIN\nnot valid json\nLEGADOHUB_TRACE_END -->", encoding="utf-8")

    chapter_index_payload = {
        "bookId": "book-1",
        "chapters": [{"index": 1, "title": "第一章", "file": "chapters/0001-第一章.md", "status": "fetched"}],
    }
    result = storage.check_chapter_traces(
        book_name="测试小说",
        author="作者甲",
        chapter_index_payload=chapter_index_payload,
    )

    assert result["valid"] is False
    assert result["broken"] == [1]
    assert result["missing"] == []


def test_write_book_bundle_order_keeps_metadata_consistent_after_partial_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """If metadata write crashes after chapter files succeed, chapter truth remains consistent."""
    storage = SharedBookStorage(tmp_path / "library")
    metadata_path = storage.metadata_path(book_name="测试小说", author="作者甲")
    chapter_index_path = storage.chapter_index_path(book_name="测试小说", author="作者甲")
    chapter_path = storage.chapter_markdown_path(
        book_name="测试小说", author="作者甲", chapter_index=1, title="第一章"
    )

    real_replace = shared_book_storage_module.os.replace
    call_count = {"n": 0}

    def failing_replace_on_third_call(src: Path | str, dst: Path | str) -> None:
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise OSError("metadata write crash")
        real_replace(src, dst)

    monkeypatch.setattr(shared_book_storage_module.os, "replace", failing_replace_on_third_call)

    with pytest.raises(OSError, match="metadata write crash"):
        storage.write_book_bundle(
            metadata_path=metadata_path,
            metadata_payload={"bookId": "book-1"},
            chapter_index_path=chapter_index_path,
            chapter_index_payload={
                "bookId": "book-1",
                "chapters": [{"index": 1, "title": "第一章", "file": "chapters/0001-第一章.md", "status": "fetched"}],
            },
            chapter_files=[(chapter_path, storage.render_chapter_markdown(
                title="第一章", body="正文", trace_payload={"chapterIndex": 1, "chapterTitle": "第一章", "chapterStatus": "fetched"}
            ))],
        )

    assert chapter_path.exists()
    assert chapter_index_path.exists()
    assert not metadata_path.exists()
    traces = storage.check_chapter_traces(book_name="测试小说", author="作者甲")
    assert traces["valid"] is True
