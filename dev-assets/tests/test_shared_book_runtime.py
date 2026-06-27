from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services.shared_book_errors import (
    ERROR_FAMILY_PREFIXES,
    SharedBookErrorCode,
    is_valid_error_code,
)
from app.services.shared_book_job_types import (
    CANONICAL_JOB_TYPES,
    SharedBookJobType,
    is_valid_job_type,
)
from app.services.shared_book_runtime import (
    RUNTIME_FILE_VERSION,
    SharedBookProcessLogger,
    SharedBookQueueFile,
    SharedBookQueueItem,
    SharedBookRuntimePaths,
    SharedBookRuntimeState,
    SharedBookRuntimeStore,
    build_chapter_progress_payload,
)
from app.services.shared_book_storage import SharedBookStorage


def test_shared_book_job_types_are_canonical():
    assert CANONICAL_JOB_TYPES == (
        "book_bootstrap",
        "book_update_check",
        "book_source_map_refresh",
        "book_history_repair",
        "book_manual_rebuild",
        "startup_recovery_scan",
    )
    assert SharedBookJobType.BOOK_BOOTSTRAP == "book_bootstrap"
    assert SharedBookJobType.STARTUP_RECOVERY_SCAN == "startup_recovery_scan"
    assert is_valid_job_type("book_manual_rebuild") is True
    assert is_valid_job_type("Book_Manual_Rebuild") is False


def test_shared_book_error_codes_match_expected_families():
    assert ERROR_FAMILY_PREFIXES == ("S1_", "S2_", "S3_", "SYS_")
    assert SharedBookErrorCode.S1_SOURCE_FETCH_FAILED == "S1_SOURCE_FETCH_FAILED"
    assert SharedBookErrorCode.S2_SOURCE_MAP_MISSING == "S2_SOURCE_MAP_MISSING"
    assert SharedBookErrorCode.S3_OUTPUT_WRITE_FAILED == "S3_OUTPUT_WRITE_FAILED"
    assert SharedBookErrorCode.SYS_RUNTIME_STATE_INVALID == "SYS_RUNTIME_STATE_INVALID"
    assert is_valid_error_code("S1_SOURCE_FETCH_FAILED") is True
    assert is_valid_error_code("APP_UNKNOWN") is False


def test_shared_book_queue_item_schema_validates_required_fields():
    item = SharedBookQueueItem.model_validate(
        {
            "jobId": "job-001",
            "jobType": "book_update_check",
            "bookName": "测试小说",
            "author": "作者甲",
            "enqueueReason": "manual",
            "queuedAt": "2026-06-26T20:00:00+08:00",
            "notBefore": "2026-06-26T20:01:00+08:00",
            "attempt": 1,
            "priority": 50,
            "traceId": "trace-001",
            "payload": {"requestedBy": "tester"},
        }
    )

    assert item.jobType == SharedBookJobType.BOOK_UPDATE_CHECK
    assert item.payload == {"requestedBy": "tester"}
    assert item.lastErrorCode is None


def test_shared_book_queue_item_rejects_invalid_job_type():
    with pytest.raises(ValidationError, match="jobType"):
        SharedBookQueueItem.model_validate(
            {
                "jobId": "job-001",
                "jobType": "unknown_job",
                "bookName": "测试小说",
                "author": "作者甲",
                "enqueueReason": "manual",
                "queuedAt": "2026-06-26T20:00:00+08:00",
            }
        )


def test_shared_book_queue_item_rejects_invalid_error_code():
    with pytest.raises(ValidationError, match="lastErrorCode"):
        SharedBookQueueItem.model_validate(
            {
                "jobId": "job-001",
                "jobType": "book_update_check",
                "bookName": "测试小说",
                "author": "作者甲",
                "enqueueReason": "manual",
                "queuedAt": "2026-06-26T20:00:00+08:00",
                "lastErrorCode": "BAD_CODE",
            }
        )


def test_shared_book_queue_item_rejects_forbidden_extra_fields():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SharedBookQueueItem.model_validate(
            {
                "jobId": "job-001",
                "jobType": "book_update_check",
                "bookName": "测试小说",
                "author": "作者甲",
                "enqueueReason": "manual",
                "queuedAt": "2026-06-26T20:00:00+08:00",
                "unexpectedField": "nope",
            }
        )


@pytest.mark.parametrize(
    ("stage_name", "expected_filename"),
    [
        ("stage1", "stage1.json"),
        ("stage2", "stage2.json"),
        ("stage3", "stage3.json"),
        ("retry", "retry.json"),
    ],
)
def test_shared_book_runtime_paths_resolve_queue_files(tmp_path: Path, stage_name: str, expected_filename: str):
    storage = SharedBookStorage(tmp_path / "library")
    runtime_paths = SharedBookRuntimePaths(storage=storage)

    paths = runtime_paths.for_book(book_name="测试小说", author="作者甲")

    assert paths.state_path == tmp_path / "library" / "测试小说_作者甲" / "runtime" / "state.json"
    assert paths.queue_paths[stage_name].name == expected_filename
    assert paths.queue_paths[stage_name].parent.name == "queues"


def test_shared_book_runtime_store_load_save_round_trip(tmp_path: Path):
    storage = SharedBookStorage(tmp_path / "library")
    store = SharedBookRuntimeStore(storage=storage)

    state = SharedBookRuntimeState(
        updatedAt="2026-06-26T20:10:00+08:00",
        activeJobs={
            "stage1": SharedBookQueueItem(
                jobId="job-stage1",
                jobType=SharedBookJobType.BOOK_BOOTSTRAP,
                bookName="测试小说",
                author="作者甲",
                enqueueReason="startup",
                queuedAt="2026-06-26T20:00:00+08:00",
                startedAt="2026-06-26T20:05:00+08:00",
                attempt=1,
                priority=100,
            )
        },
        lastCompletedJobId="job-prev",
    )
    queue = SharedBookQueueFile(
        stage="stage1",
        items=[
            SharedBookQueueItem(
                jobId="job-stage1",
                jobType=SharedBookJobType.BOOK_BOOTSTRAP,
                bookName="测试小说",
                author="作者甲",
                enqueueReason="startup",
                queuedAt="2026-06-26T20:00:00+08:00",
                attempt=1,
                priority=100,
            )
        ],
    )

    store.save_state(book_name="测试小说", author="作者甲", state=state)
    store.save_queue(book_name="测试小说", author="作者甲", queue=queue)

    loaded_state = store.load_state(book_name="测试小说", author="作者甲")
    loaded_queue = store.load_queue(book_name="测试小说", author="作者甲", stage="stage1")

    assert loaded_state == state
    assert loaded_queue == queue

    state_payload = json.loads(
        (tmp_path / "library" / "测试小说_作者甲" / "runtime" / "state.json").read_text(encoding="utf-8")
    )
    queue_payload = json.loads(
        (tmp_path / "library" / "测试小说_作者甲" / "runtime" / "queues" / "stage1.json").read_text(encoding="utf-8")
    )
    assert state_payload["version"] == RUNTIME_FILE_VERSION
    assert queue_payload["version"] == RUNTIME_FILE_VERSION


def test_shared_book_runtime_store_returns_defaults_when_files_missing(tmp_path: Path):
    storage = SharedBookStorage(tmp_path / "library")
    store = SharedBookRuntimeStore(storage=storage)

    state = store.load_state(book_name="测试小说", author="作者甲")
    queue = store.load_queue(book_name="测试小说", author="作者甲", stage="retry")

    assert state == SharedBookRuntimeState()
    assert queue == SharedBookQueueFile(stage="retry")


def test_shared_book_runtime_state_rejects_invalid_active_job_slot():
    with pytest.raises(ValidationError, match="activeJobs contains unsupported stage slots"):
        SharedBookRuntimeState.model_validate(
            {
                "activeJobs": {
                    "retry": {
                        "jobId": "job-001",
                        "jobType": "book_update_check",
                        "bookName": "测试小说",
                        "author": "作者甲",
                        "enqueueReason": "manual",
                        "queuedAt": "2026-06-26T20:00:00+08:00",
                    }
                }
            }
        )


def test_shared_book_runtime_store_rejects_queue_stage_mismatch(tmp_path: Path):
    storage = SharedBookStorage(tmp_path / "library")
    store = SharedBookRuntimeStore(storage=storage)
    paths = store.paths.for_book(book_name="测试小说", author="作者甲")
    paths.queue_paths["stage2"].parent.mkdir(parents=True, exist_ok=True)
    paths.queue_paths["stage2"].write_text(
        json.dumps({"version": 1, "stage": "stage1", "items": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )

    with pytest.raises(ValueError, match="stage mismatch"):
        store.load_queue(book_name="测试小说", author="作者甲", stage="stage2")


def test_shared_book_process_logger_appends_and_reads(tmp_path: Path):
    storage = SharedBookStorage(tmp_path / "library")
    logger = SharedBookProcessLogger(storage=storage)

    logger.append(
        book_name="测试小说",
        author="作者甲",
        event="chapter_fetch",
        book_id="book-1",
        chapter_index=1,
        stage="stage1",
    )
    logger.append(
        book_name="测试小说",
        author="作者甲",
        event="chapter_write",
        book_id="book-1",
        chapter_index=1,
        stage="stage1",
        payload={"status": "fetched"},
    )
    logger.append(
        book_name="测试小说",
        author="作者甲",
        event="chapter_error",
        book_id="book-1",
        chapter_index=2,
        stage="stage2",
        error_code="S2_SOURCE_MAP_MISSING",
        error_message="missing source map",
    )

    all_logs = logger.read(book_name="测试小说", author="作者甲", limit=10)
    assert all_logs["total"] == 3

    stage1_logs = logger.read(book_name="测试小说", author="作者甲", stage="stage1")
    assert stage1_logs["total"] == 2

    chapter1_logs = logger.read(book_name="测试小说", author="作者甲", chapter_index=1)
    assert chapter1_logs["total"] == 2

    error_logs = logger.read(book_name="测试小说", author="作者甲", event="chapter_error")
    assert error_logs["total"] == 1
    assert error_logs["items"][0]["errorCode"] == "S2_SOURCE_MAP_MISSING"


def test_build_chapter_progress_payload_shapes_three_nodes():
    payload = build_chapter_progress_payload(
        book_id="book-1",
        chapter_index=1,
        chapter_title="第一章",
        chapter_trace={
            "chapterStatus": "supplemented",
            "previewOnly": True,
            "primarySource": {"sourceId": "official", "officialWordCount": 100},
            "supplementSource": {"sourceId": "third-party"},
        },
        logs=[{"event": "chapter_fetch"}],
    )

    assert payload["bookId"] == "book-1"
    assert payload["chapterIndex"] == 1
    assert payload["chapterStatus"] == "supplemented"
    assert len(payload["nodes"]) == 3

    stage1 = payload["nodes"][0]
    stage2 = payload["nodes"][1]
    stage3 = payload["nodes"][2]

    assert stage1["stage"] == "stage1"
    assert stage1["complete"] is True
    assert stage2["stage"] == "stage2"
    assert stage2["complete"] is True
    assert stage2["supplementSource"]["sourceId"] == "third-party"
    assert stage3["stage"] == "stage3"
    assert stage3["complete"] is False
    assert stage3["status"] == "pending"
    assert len(payload["logs"]) == 1


def test_build_chapter_progress_payload_proofread_complete():
    payload = build_chapter_progress_payload(
        book_id="book-1",
        chapter_index=2,
        chapter_title="第二章",
        chapter_trace={
            "chapterStatus": "proofread_complete",
            "previewOnly": False,
            "aiProcessedAt": "2026-06-26T10:00:00+08:00",
        },
    )

    assert payload["nodes"][0]["complete"] is True
    assert payload["nodes"][1]["complete"] is True
    assert payload["nodes"][2]["complete"] is True
    assert payload["nodes"][2]["status"] == "proofread_complete"
    assert payload["nodes"][2]["aiProcessedAt"] == "2026-06-26T10:00:00+08:00"

