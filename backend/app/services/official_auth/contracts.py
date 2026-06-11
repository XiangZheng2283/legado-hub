"""Abstract contracts for official-source private auth plugins.

Open-source layer: defines interfaces that private packages must implement.
Private packages under plugins/sources/official/qidian_com/private/ implement these.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class AuthApiContract(ABC):
    """Private phone-login protocol (captcha + SMS)."""

    @abstractmethod
    def request_code(self, payload: dict) -> dict:
        """Request SMS verification code.

        Payload: {"phone": "13800138000", ...}
        Returns: {"ok": bool, "sessionId": str, "nextAction": str, ...}
        """
        ...

    @abstractmethod
    def verify_code(self, payload: dict) -> dict:
        """Verify SMS code and complete login.

        Payload: {"sessionId": str, "phone": str, "code": str, "challengeToken": str}
        Returns: {"ok": bool, "authenticated": bool, "accountName": str, "cookies": dict}
        """
        ...

    @abstractmethod
    def continue_challenge(self, payload: dict) -> dict:
        """Continue after challenge (slide captcha etc.). Optional."""
        ...


class CookieAuthContract(ABC):
    """Private cookie parsing, verification, normalization."""

    @abstractmethod
    def parse_cookie_text(self, cookie_text: str) -> dict[str, dict[str, str]]:
        """Parse raw cookie text string into domain-keyed jar."""
        ...

    @abstractmethod
    def verify_cookies(self, cookie_jar: dict[str, dict[str, str]]) -> dict:
        """Verify cookies are valid and return auth status.

        Returns: {"authenticated": bool, "accountName": str, "message": str}
        """
        ...

    @abstractmethod
    def normalize_cookies(self, cookie_jar: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        """Normalize cookie jar to standard format."""
        ...


class ReviewsContract(ABC):
    """Private chapter-reviews (paragraph + chapter-end)."""

    @abstractmethod
    async def chapter_reviews(self, ctx: Any, chapter_url: str) -> dict:
        """Fetch reviews for a chapter.

        Returns: {"paragraphs": {}, "chapterEnd": [], "summary": {}}
        """
        ...


class PrivatePluginManifest:
    """Parsed manifest.json from a private package."""

    def __init__(self, data: dict):
        self.plugin_id: str = data.get("pluginId", "")
        self.version: str = data.get("version", "")
        caps = data.get("capabilities", {})
        self.phone_auth: bool = caps.get("phoneAuth", False)
        self.cookie_auth: bool = caps.get("cookieAuth", False)
        self.reviews: bool = caps.get("reviews", False)

    def available_methods(self) -> list[str]:
        methods: list[str] = []
        if self.phone_auth:
            methods.append("phone")
        if self.cookie_auth:
            methods.append("cookie")
        return methods

    def default_method(self) -> str:
        methods = self.available_methods()
        return methods[0] if methods else ""
