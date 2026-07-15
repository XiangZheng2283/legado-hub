"""Canonical shared-book runtime error codes."""

from __future__ import annotations

import re
from enum import StrEnum

ERROR_FAMILY_PREFIXES = ("S1_", "S2_", "S3_", "SYS_")
_ERROR_CODE_PATTERN = re.compile(r"^(S1_|S2_|S3_|SYS_)[A-Z0-9_]+$")


class SharedBookErrorCode(StrEnum):
    S1_SOURCE_FETCH_FAILED = "S1_SOURCE_FETCH_FAILED"
    S1_SOURCE_CONTENT_DEFERRED = "S1_SOURCE_CONTENT_DEFERRED"
    S1_SOURCE_AUTH_REQUIRED = "S1_SOURCE_AUTH_REQUIRED"
    S1_SOURCE_CONFIGURATION_INVALID = "S1_SOURCE_CONFIGURATION_INVALID"
    S2_SOURCE_MAP_MISSING = "S2_SOURCE_MAP_MISSING"
    S2_CANDIDATE_FETCH_FAILED = "S2_CANDIDATE_FETCH_FAILED"
    S2_ALIGNMENT_FAILED = "S2_ALIGNMENT_FAILED"
    S3_AI_FAILED = "S3_AI_FAILED"
    S3_AI_BUDGET_EXCEEDED = "S3_AI_BUDGET_EXCEEDED"
    S3_CONTENT_CANDIDATE_UNTRUSTED = "S3_CONTENT_CANDIDATE_UNTRUSTED"
    S3_OUTPUT_WRITE_FAILED = "S3_OUTPUT_WRITE_FAILED"
    SYS_RUNTIME_STATE_INVALID = "SYS_RUNTIME_STATE_INVALID"


class SharedBookRetryClass(StrEnum):
    SHORT_RETRY = "short_retry"
    LONG_RETRY_SCAN = "long_retry_scan"
    NO_RETRY = "no_retry"


_STAGE1_RETRY_CLASS_BY_CODE: dict[SharedBookErrorCode, SharedBookRetryClass] = {
    SharedBookErrorCode.S1_SOURCE_FETCH_FAILED: SharedBookRetryClass.SHORT_RETRY,
    SharedBookErrorCode.S1_SOURCE_CONTENT_DEFERRED: SharedBookRetryClass.LONG_RETRY_SCAN,
    SharedBookErrorCode.S1_SOURCE_AUTH_REQUIRED: SharedBookRetryClass.LONG_RETRY_SCAN,
    SharedBookErrorCode.S1_SOURCE_CONFIGURATION_INVALID: SharedBookRetryClass.NO_RETRY,
}

_STAGE2_RETRY_CLASS_BY_CODE: dict[SharedBookErrorCode, SharedBookRetryClass] = {
    SharedBookErrorCode.S2_SOURCE_MAP_MISSING: SharedBookRetryClass.LONG_RETRY_SCAN,
    SharedBookErrorCode.S2_CANDIDATE_FETCH_FAILED: SharedBookRetryClass.SHORT_RETRY,
    SharedBookErrorCode.S2_ALIGNMENT_FAILED: SharedBookRetryClass.SHORT_RETRY,
}

_STAGE3_RETRY_CLASS_BY_CODE: dict[SharedBookErrorCode, SharedBookRetryClass] = {
    SharedBookErrorCode.S3_AI_FAILED: SharedBookRetryClass.SHORT_RETRY,
    SharedBookErrorCode.S3_AI_BUDGET_EXCEEDED: SharedBookRetryClass.LONG_RETRY_SCAN,
    SharedBookErrorCode.S3_CONTENT_CANDIDATE_UNTRUSTED: SharedBookRetryClass.LONG_RETRY_SCAN,
    SharedBookErrorCode.S3_OUTPUT_WRITE_FAILED: SharedBookRetryClass.SHORT_RETRY,
}

STAGE1_NO_RETRY_ERROR_CODES = frozenset(
    code for code, retry_class in _STAGE1_RETRY_CLASS_BY_CODE.items()
    if retry_class == SharedBookRetryClass.NO_RETRY
)


def is_valid_error_code(value: str | None) -> bool:
    text = str(value or "")
    return bool(_ERROR_CODE_PATTERN.fullmatch(text))


def classify_stage1_error(exc: Exception) -> SharedBookErrorCode:
    """Map a Stage 1 chapter-fetch failure to a canonical shared-book error code."""
    from app.ai.client import AIProviderHTTPError, AIProviderNotConfiguredError

    msg = str(exc).lower()

    if isinstance(exc, ValueError) and "empty" in msg:
        return SharedBookErrorCode.S1_SOURCE_CONTENT_DEFERRED

    if isinstance(exc, TimeoutError):
        return SharedBookErrorCode.S1_SOURCE_FETCH_FAILED

    try:
        import httpx

        if isinstance(exc, httpx.TimeoutException):
            return SharedBookErrorCode.S1_SOURCE_FETCH_FAILED
    except ImportError:
        pass

    if isinstance(exc, AIProviderHTTPError):
        if exc.status_code == 401:
            return SharedBookErrorCode.S1_SOURCE_AUTH_REQUIRED
        if exc.status_code == 400:
            return SharedBookErrorCode.S1_SOURCE_CONFIGURATION_INVALID
        return SharedBookErrorCode.S1_SOURCE_FETCH_FAILED

    if isinstance(exc, AIProviderNotConfiguredError):
        return SharedBookErrorCode.S1_SOURCE_CONFIGURATION_INVALID

    if "timeout" in msg or "timed out" in msg:
        return SharedBookErrorCode.S1_SOURCE_FETCH_FAILED

    return SharedBookErrorCode.S1_SOURCE_FETCH_FAILED


def classify_stage1_retry(error_code: SharedBookErrorCode | str) -> SharedBookRetryClass:
    """Return the retry routing class for a canonical Stage 1 error code."""
    try:
        code = SharedBookErrorCode(str(error_code))
    except ValueError:
        return SharedBookRetryClass.SHORT_RETRY
    return _STAGE1_RETRY_CLASS_BY_CODE.get(code, SharedBookRetryClass.SHORT_RETRY)


def classify_stage2_error(exc: Exception) -> SharedBookErrorCode:
    """Map a Stage 2 candidate-source failure to a canonical error code."""
    from app.ai.client import AIProviderHTTPError, AIProviderNotConfiguredError

    msg = str(exc).lower()

    if isinstance(exc, ValueError) and ("alignment" in msg or "mismatch" in msg):
        return SharedBookErrorCode.S2_ALIGNMENT_FAILED

    if isinstance(exc, TimeoutError):
        return SharedBookErrorCode.S2_CANDIDATE_FETCH_FAILED

    try:
        import httpx

        if isinstance(exc, httpx.TimeoutException):
            return SharedBookErrorCode.S2_CANDIDATE_FETCH_FAILED
    except ImportError:
        pass

    if isinstance(exc, AIProviderHTTPError):
        if exc.status_code == 401:
            return SharedBookErrorCode.S2_SOURCE_MAP_MISSING
        if exc.status_code == 400:
            return SharedBookErrorCode.S2_ALIGNMENT_FAILED
        return SharedBookErrorCode.S2_CANDIDATE_FETCH_FAILED

    if isinstance(exc, AIProviderNotConfiguredError):
        return SharedBookErrorCode.S2_SOURCE_MAP_MISSING

    if "source map" in msg or "candidate" in msg or "no candidate" in msg:
        return SharedBookErrorCode.S2_SOURCE_MAP_MISSING

    if "timeout" in msg or "timed out" in msg:
        return SharedBookErrorCode.S2_CANDIDATE_FETCH_FAILED

    return SharedBookErrorCode.S2_CANDIDATE_FETCH_FAILED


def classify_stage2_retry(error_code: SharedBookErrorCode | str) -> SharedBookRetryClass:
    """Return the retry routing class for a canonical Stage 2 error code."""
    try:
        code = SharedBookErrorCode(str(error_code))
    except ValueError:
        return SharedBookRetryClass.SHORT_RETRY
    return _STAGE2_RETRY_CLASS_BY_CODE.get(code, SharedBookRetryClass.SHORT_RETRY)


def classify_stage3_error(exc: Exception) -> SharedBookErrorCode:
    """Map a Stage 3 AI processing failure to a canonical error code."""
    from app.ai.client import AIProviderHTTPError, AIProviderNotConfiguredError

    msg = str(exc).lower()

    if isinstance(exc, ValueError) and (
        "no usable candidate" in msg
        or "all candidates untrusted" in msg
        or "content candidate untrusted" in msg
        or "current正文不可信" in msg
    ):
        return SharedBookErrorCode.S3_CONTENT_CANDIDATE_UNTRUSTED

    if isinstance(exc, AIProviderNotConfiguredError):
        return SharedBookErrorCode.S3_AI_BUDGET_EXCEEDED

    if isinstance(exc, AIProviderHTTPError):
        if exc.status_code == 429:
            return SharedBookErrorCode.S3_AI_BUDGET_EXCEEDED
        if exc.status_code in (401, 403):
            return SharedBookErrorCode.S3_AI_BUDGET_EXCEEDED
        return SharedBookErrorCode.S3_AI_FAILED

    if "budget" in msg or "rate limit" in msg or "quota" in msg or "429" in msg:
        return SharedBookErrorCode.S3_AI_BUDGET_EXCEEDED

    if "timeout" in msg or "timed out" in msg:
        return SharedBookErrorCode.S3_AI_FAILED

    return SharedBookErrorCode.S3_AI_FAILED


def classify_stage3_retry(error_code: SharedBookErrorCode | str) -> SharedBookRetryClass:
    """Return the retry routing class for a canonical Stage 3 error code."""
    try:
        code = SharedBookErrorCode(str(error_code))
    except ValueError:
        return SharedBookRetryClass.SHORT_RETRY
    return _STAGE3_RETRY_CLASS_BY_CODE.get(code, SharedBookRetryClass.SHORT_RETRY)
