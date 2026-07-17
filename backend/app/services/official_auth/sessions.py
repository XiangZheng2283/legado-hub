"""Short-lived login sessions for official-source auth flows.

Sessions live in memory (not DB) and expire after 10 minutes.
"""

from __future__ import annotations

import copy
import re
import time
import uuid
from typing import Any


REDACTED = "[REDACTED]"
MAX_ERROR_LENGTH = 500
MAX_TRACE_STRING_LENGTH = 2000
MAX_TRACE_ITEMS = 100
MAX_TRACE_DEPTH = 8
_SENSITIVE_KEYS = {
    "authorization",
    "bindphone",
    "fu",
    "inputuserid",
    "mobile",
    "mobilephone",
    "password",
    "passwd",
    "phone",
    "phonenumber",
    "secret",
    "sessionid",
    "ywguid",
    "ywkey",
    "ywopenid",
    "alk",
    "csrftoken",
    "qdinfo",
}
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_CODE_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(cookie|cookies|authorization|(?:access|refresh|challenge|captcha|cmfu)?token|"
    r"password|passwd|secret|(?:sms|validate|captcha)?code|ywguid|ywkey|ywopenid|alk|qdinfo)"
    r"\b[\"']?\s*[:=]\s*[\"']?[^\s,;\"'}]+"
)
_LABELED_SECRET_RE = re.compile(
    r"(?i)\b(token|cookie|password|secret)[-_:][a-z0-9._~+/=-]+"
)


def _sensitive_key(key: object) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).casefold())
    return (
        normalized in _SENSITIVE_KEYS
        or "cookie" in normalized
        or normalized.endswith(("token", "password", "passwd", "secret", "code"))
    )


def _redact_text(value: object, max_length: int) -> str:
    text = str(value or "")
    text = _PHONE_RE.sub("[REDACTED_PHONE]", text)
    text = _CODE_RE.sub("[REDACTED_CODE]", text)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}={REDACTED}", text)
    text = _LABELED_SECRET_RE.sub(lambda match: f"{match.group(1)}={REDACTED}", text)
    return text if len(text) <= max_length else f"{text[: max_length - 3]}..."


def _redact_trace_value(value: Any, depth: int = 0) -> Any:
    if depth >= MAX_TRACE_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        items = list(value.items())[:MAX_TRACE_ITEMS]
        redacted = {
            key: REDACTED if _sensitive_key(key) else _redact_trace_value(item, depth + 1)
            for key, item in items
        }
        if len(value) > MAX_TRACE_ITEMS:
            redacted["__truncated__"] = True
        return redacted
    if isinstance(value, list):
        return [_redact_trace_value(item, depth + 1) for item in value[:MAX_TRACE_ITEMS]]
    if isinstance(value, tuple):
        return tuple(_redact_trace_value(item, depth + 1) for item in value[:MAX_TRACE_ITEMS])
    if isinstance(value, set):
        return [_redact_trace_value(item, depth + 1) for item in list(value)[:MAX_TRACE_ITEMS]]
    if isinstance(value, str):
        return _redact_text(value, MAX_TRACE_STRING_LENGTH)
    return value


def _redact_error(error: object) -> str:
    return _redact_text(error, MAX_ERROR_LENGTH)


def _safe_masked_phone(value: object) -> str:
    phone = str(value or "").strip()
    if not phone:
        return ""
    if re.fullmatch(r"1[3-9]\d\*{4}\d{4}", phone):
        return phone
    if re.fullmatch(r"1[3-9]\d{9}", phone):
        return f"{phone[:3]}****{phone[-4:]}"
    return REDACTED


class OfficialLoginSession:
    """A single login attempt session."""

    EXPIRY_SECONDS = 600  # 10 minutes

    def __init__(self, plugin_id: str, method: str = ""):
        self.session_id = uuid.uuid4().hex[:16]
        self.plugin_id = plugin_id
        self.method = method
        self.created_at = time.time()
        self.status = "init"          # init | challenge | sms_sent | success | failed
        self.last_step = ""
        self.last_error = ""
        self.phone_masked = ""
        self.challenge_state: dict[str, Any] = {}  # challenge-specific data
        self.private_payload: dict[str, Any] = {}  # opaque data for private plugin
        self.cookies: dict[str, dict[str, str]] = {}

    def expired(self) -> bool:
        return time.time() - self.created_at > self.EXPIRY_SECONDS

    def to_dict(self) -> dict:
        return {
            "sessionId": self.session_id,
            "pluginId": self.plugin_id,
            "method": self.method,
            "status": self.status,
            "lastStep": self.last_step,
            "lastError": _redact_error(self.last_error),
            "phoneMasked": _safe_masked_phone(self.phone_masked),
            "expired": self.expired(),
        }


class OfficialSessionStore:
    """In-memory store for login sessions."""

    def __init__(self):
        self._sessions: dict[str, OfficialLoginSession] = {}

    def create(self, plugin_id: str, method: str = "") -> OfficialLoginSession:
        self._cleanup_expired()
        session = OfficialLoginSession(plugin_id, method)
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> OfficialLoginSession | None:
        self._cleanup_expired()
        session = self._sessions.get(session_id)
        if session and session.expired():
            self._sessions.pop(session_id, None)
            return None
        return session

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s.created_at > OfficialLoginSession.EXPIRY_SECONDS + 60
        ]
        for sid in expired:
            self._sessions.pop(sid, None)


class LoginTraceStore:
    """In-memory store for recent login step traces.

    Each entry captures the method, payload, and result of a login step so
    that debugging the official-source login flow does not require tailing
    server logs.
    """

    MAX_ENTRIES_PER_PLUGIN = 20

    def __init__(self):
        self._traces: dict[str, list[dict[str, Any]]] = {}

    def record(
        self,
        plugin_id: str,
        step: str,
        payload: dict[str, Any],
        result: dict[str, Any],
        session_id: str = "",
        error: str = "",
    ) -> None:
        self._traces.setdefault(plugin_id, [])
        self._traces[plugin_id].append(
            {
                "timestamp": time.time(),
                "pluginId": plugin_id,
                "sessionId": session_id,
                "step": step,
                "payload": _redact_trace_value(payload),
                "result": _redact_trace_value(result),
                "error": _redact_error(error),
            }
        )
        # Keep only the most recent entries.
        self._traces[plugin_id] = self._traces[plugin_id][-self.MAX_ENTRIES_PER_PLUGIN :]

    def get(self, plugin_id: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self._traces.get(plugin_id, []))

    def clear(self, plugin_id: str) -> None:
        self._traces.pop(plugin_id, None)


# Global singletons
session_store = OfficialSessionStore()
login_trace_store = LoginTraceStore()
