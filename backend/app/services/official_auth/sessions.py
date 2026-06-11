"""Short-lived login sessions for official-source auth flows.

Sessions live in memory (not DB) and expire after 10 minutes.
"""

from __future__ import annotations

import time
import uuid
from typing import Any


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
            "lastError": self.last_error,
            "phoneMasked": self.phone_masked,
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


# Global singleton
session_store = OfficialSessionStore()
