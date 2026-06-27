"""Runtime and queue file models for shared-book processing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.shared_book_errors import is_valid_error_code
from app.services.shared_book_job_types import SharedBookJobType, is_valid_job_type
from app.services.shared_book_storage import SharedBookStorage

RUNTIME_FILE_VERSION = 1


@dataclass(frozen=True)
class SharedBookStageDefinition:
    name: str
    queue_filename: str
    allows_active_job: bool


STAGE_DEFINITIONS = (
    SharedBookStageDefinition(name="stage1", queue_filename="stage1.json", allows_active_job=True),
    SharedBookStageDefinition(name="stage2", queue_filename="stage2.json", allows_active_job=True),
    SharedBookStageDefinition(name="stage3", queue_filename="stage3.json", allows_active_job=True),
    SharedBookStageDefinition(name="retry", queue_filename="retry.json", allows_active_job=False),
)
STAGE_DEFINITION_BY_NAME = {item.name: item for item in STAGE_DEFINITIONS}
QUEUE_STAGES = tuple(item.name for item in STAGE_DEFINITIONS)
ACTIVE_JOB_SLOTS = tuple(item.name for item in STAGE_DEFINITIONS if item.allows_active_job)
QueueStage = str
ActiveJobSlot = str


class SharedBookQueueItem(BaseModel):
    """Canonical queue item payload persisted in runtime queue files."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    jobId: str = Field(min_length=1)
    jobType: SharedBookJobType
    bookName: str = Field(min_length=1)
    author: str = Field(min_length=1)
    enqueueReason: str = Field(min_length=1)
    # Runtime files keep timestamps as plain strings for now; we only validate presence here,
    # leaving format/parsing decisions to later scheduler integration.
    queuedAt: str = Field(min_length=1)
    notBefore: str | None = None
    attempt: int = Field(default=0, ge=0)
    priority: int = Field(default=0)
    traceId: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    startedAt: str | None = None
    leaseOwner: str | None = None
    lastErrorCode: str | None = None
    lastErrorMessage: str | None = None
    lastErrorAt: str | None = None

    @field_validator("jobType", mode="before")
    @classmethod
    def _validate_job_type(cls, value: Any) -> Any:
        if not is_valid_job_type(str(value or "")):
            raise ValueError(f"jobType must be one of: {', '.join(item.value for item in SharedBookJobType)}")
        return value

    @field_validator("lastErrorCode")
    @classmethod
    def _validate_error_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not is_valid_error_code(value):
            raise ValueError("lastErrorCode must match canonical shared-book error code families")
        return value


class SharedBookQueueFile(BaseModel):
    """One runtime queue file under runtime/queues/."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    version: int = Field(default=RUNTIME_FILE_VERSION)
    stage: QueueStage
    items: list[SharedBookQueueItem] = Field(default_factory=list)

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: int) -> int:
        if int(value) != RUNTIME_FILE_VERSION:
            raise ValueError(f"unsupported runtime file version: {value}")
        return int(value)

    @field_validator("stage")
    @classmethod
    def _validate_stage(cls, value: str) -> str:
        if value not in QUEUE_STAGES:
            raise ValueError(f"stage must be one of: {', '.join(QUEUE_STAGES)}")
        return value


class SharedBookRuntimeState(BaseModel):
    """Runtime state persisted in state.json."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    version: int = Field(default=RUNTIME_FILE_VERSION)
    updatedAt: str = ""
    activeJobs: dict[ActiveJobSlot, SharedBookQueueItem] = Field(default_factory=dict)
    lastCompletedJobId: str | None = None
    recoveryCursor: dict[str, Any] = Field(default_factory=dict)
    stage3Deferred: list["SharedBookStage3DeferredItem"] = Field(default_factory=list)

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: int) -> int:
        if int(value) != RUNTIME_FILE_VERSION:
            raise ValueError(f"unsupported runtime file version: {value}")
        return int(value)

    @model_validator(mode="after")
    def _validate_active_jobs(self) -> "SharedBookRuntimeState":
        invalid_slots = [slot for slot in self.activeJobs if slot not in ACTIVE_JOB_SLOTS]
        if invalid_slots:
            raise ValueError(f"activeJobs contains unsupported stage slots: {', '.join(sorted(invalid_slots))}")
        return self


class SharedBookStage3DeferredItem(BaseModel):
    """Narrow runtime signal for readable chapters waiting on later Stage 3 proofread."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    chapterId: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    retryNotBefore: str = Field(min_length=1)
    updatedAt: str = Field(min_length=1)
    attempt: int = Field(default=0, ge=0)


@dataclass(frozen=True)
class SharedBookRuntimeBookPaths:
    state_path: Path
    queue_paths: dict[QueueStage, Path]


class SharedBookRuntimePaths:
    """Resolve runtime file locations for a shared book."""

    def __init__(self, storage: SharedBookStorage | None = None):
        self.storage = storage or SharedBookStorage()

    def for_book(self, *, book_name: str, author: str) -> SharedBookRuntimeBookPaths:
        runtime_dir = self.storage.runtime_dir(book_name=book_name, author=author)
        queue_dir = runtime_dir / "queues"
        queue_paths: dict[QueueStage, Path] = {
            definition.name: queue_dir / definition.queue_filename for definition in STAGE_DEFINITIONS
        }
        return SharedBookRuntimeBookPaths(
            state_path=runtime_dir / "state.json",
            queue_paths=queue_paths,
        )


class SharedBookRuntimeStore:
    """Load and save runtime state / queue files with validation."""

    def __init__(self, storage: SharedBookStorage | None = None):
        self.storage = storage or SharedBookStorage()
        self.paths = SharedBookRuntimePaths(self.storage)

    def load_state(self, *, book_name: str, author: str) -> SharedBookRuntimeState:
        runtime_paths = self.paths.for_book(book_name=book_name, author=author)
        payload = self._read_json(runtime_paths.state_path)
        if payload is None:
            return SharedBookRuntimeState()
        return SharedBookRuntimeState.model_validate(payload)

    def save_state(self, *, book_name: str, author: str, state: SharedBookRuntimeState) -> None:
        runtime_paths = self.paths.for_book(book_name=book_name, author=author)
        self.storage.atomic_write_json(runtime_paths.state_path, state.model_dump(mode="json"))

    def load_queue(self, *, book_name: str, author: str, stage: QueueStage) -> SharedBookQueueFile:
        self._validate_stage(stage)
        runtime_paths = self.paths.for_book(book_name=book_name, author=author)
        payload = self._read_json(runtime_paths.queue_paths[stage])
        if payload is None:
            return SharedBookQueueFile(stage=stage)
        queue = SharedBookQueueFile.model_validate(payload)
        if queue.stage != stage:
            raise ValueError(f"queue stage mismatch: expected {stage}, got {queue.stage}")
        return queue

    def save_queue(self, *, book_name: str, author: str, queue: SharedBookQueueFile) -> None:
        self._validate_stage(queue.stage)
        runtime_paths = self.paths.for_book(book_name=book_name, author=author)
        self.storage.atomic_write_json(runtime_paths.queue_paths[queue.stage], queue.model_dump(mode="json"))

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError(f"runtime file must contain a JSON object: {path}")
        return payload

    def _validate_stage(self, stage: str) -> None:
        if stage not in QUEUE_STAGES:
            raise ValueError(f"unsupported queue stage: {stage}")


class SharedBookProcessLogger:
    """Append-only JSONL logger for shared-book processing events.

    Each line is a JSON object with at least:
    - ts: ISO-8601 timestamp
    - event: event type
    - bookId
    - chapterIndex (optional)
    - stage (optional)
    - errorCode (optional)
    """

    def __init__(self, storage: SharedBookStorage | None = None):
        self.storage = storage or SharedBookStorage()

    def append(
        self,
        *,
        book_name: str,
        author: str,
        event: str,
        book_id: str | None = None,
        chapter_index: int | None = None,
        stage: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Path:
        logs_dir = self.storage.logs_dir(book_name=book_name, author=author)
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / "process.jsonl"
        record: dict[str, Any] = {
            "ts": datetime.now().isoformat(),
            "event": event,
        }
        if book_id:
            record["bookId"] = book_id
        if chapter_index is not None:
            record["chapterIndex"] = chapter_index
        if stage:
            record["stage"] = stage
        if error_code:
            record["errorCode"] = error_code
        if error_message:
            record["errorMessage"] = error_message
        if payload:
            record["payload"] = payload
        with log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
        return log_path

    def read(
        self,
        *,
        book_name: str,
        author: str,
        limit: int = 50,
        offset: int = 0,
        event: str | None = None,
        chapter_index: int | None = None,
        stage: str | None = None,
    ) -> dict[str, Any]:
        log_path = self.storage.logs_dir(book_name=book_name, author=author) / "process.jsonl"
        if not log_path.exists():
            return {"items": [], "total": 0, "limit": limit, "offset": offset}

        lines = log_path.read_text(encoding="utf-8").splitlines()
        items: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if event and record.get("event") != event:
                continue
            if chapter_index is not None and record.get("chapterIndex") != chapter_index:
                continue
            if stage and record.get("stage") != stage:
                continue
            items.append(record)

        total = len(items)
        start = max(0, offset)
        end = start + max(1, limit)
        return {"items": items[start:end], "total": total, "limit": limit, "offset": offset}


def build_chapter_progress_payload(
    *,
    book_id: str,
    chapter_index: int,
    chapter_title: str,
    chapter_trace: dict[str, Any] | None,
    logs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the chapter progress payload for the 3-node modal."""
    trace = dict(chapter_trace) if chapter_trace else {}
    status = str(trace.get("chapterStatus", "") or "pending")
    preview_only = bool(trace.get("previewOnly", False))

    stage1_complete = status not in {"", "pending"}
    stage2_complete = status in {"supplemented", "readable", "proofread_complete", "suspect", "failed"}
    stage3_complete = status in {"proofread_complete"}

    stage1 = {
        "stage": "stage1",
        "label": "主源抓取",
        "complete": stage1_complete,
        "status": status if stage1_complete else "pending",
        "previewOnly": preview_only,
        "primarySource": trace.get("primarySource") or {},
    }
    stage2 = {
        "stage": "stage2",
        "label": "第三方补全",
        "complete": stage2_complete,
        "status": "supplemented" if stage2_complete and status != "failed" else ("pending" if not stage2_complete else status),
        "supplementSource": trace.get("supplementSource"),
    }
    stage3 = {
        "stage": "stage3",
        "label": "AI 校对",
        "complete": stage3_complete,
        "status": "proofread_complete" if stage3_complete else ("pending" if stage2_complete else "waiting"),
        "aiProcessedAt": trace.get("aiProcessedAt"),
    }

    return {
        "bookId": book_id,
        "chapterIndex": chapter_index,
        "chapterTitle": chapter_title,
        "chapterStatus": status,
        "nodes": [stage1, stage2, stage3],
        "logs": logs or [],
    }
