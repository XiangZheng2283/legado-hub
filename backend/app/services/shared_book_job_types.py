"""Canonical shared-book job types."""

from __future__ import annotations

from enum import StrEnum


class SharedBookJobType(StrEnum):
    BOOK_BOOTSTRAP = "book_bootstrap"
    BOOK_UPDATE_CHECK = "book_update_check"
    BOOK_SOURCE_MAP_REFRESH = "book_source_map_refresh"
    BOOK_HISTORY_REPAIR = "book_history_repair"
    BOOK_MANUAL_REBUILD = "book_manual_rebuild"
    STARTUP_RECOVERY_SCAN = "startup_recovery_scan"


CANONICAL_JOB_TYPES = tuple(item.value for item in SharedBookJobType)


def is_valid_job_type(value: str) -> bool:
    return str(value or "") in CANONICAL_JOB_TYPES
