"""Configuration for Source Access Bridge browser runtimes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.config import DATA_DIR


def _positive_int_env(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


@dataclass(frozen=True)
class AccessBridgeConfig:
    """Runtime configuration for the Source Access Bridge service."""

    provider: str = "chromium"
    enabled_by_env: bool = True
    browserless_ws: str = ""
    browserless_token: str = ""
    public_base_url: str = ""
    profile_root: Path = DATA_DIR / "browser_profiles"
    connect_timeout_ms: int = 5000
    action_timeout_ms: int = 90000

    default_connect_timeout_ms: int = 5000
    default_action_timeout_ms: int = 90000

    @classmethod
    def from_env(cls) -> AccessBridgeConfig:
        """Load Source Access Bridge configuration from environment variables."""
        profile_root = os.getenv("LEGADOHUB_BROWSER_PROFILE_ROOT", "").strip()
        provider = os.getenv("LEGADOHUB_BROWSER_PROVIDER", "").strip().lower()
        if not provider:
            provider = "browserless" if os.getenv("LEGADOHUB_BROWSERLESS_WS", "").strip() else "chromium"
        enabled = os.getenv("LEGADOHUB_BROWSER_ENABLED", "1").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        return cls(
            provider=provider,
            enabled_by_env=enabled,
            browserless_ws=os.getenv("LEGADOHUB_BROWSERLESS_WS", "").strip(),
            browserless_token=os.getenv("LEGADOHUB_BROWSERLESS_TOKEN", "").strip(),
            public_base_url=os.getenv("LEGADOHUB_BROWSER_PUBLIC_BASE_URL", "").strip().rstrip("/"),
            profile_root=Path(profile_root) if profile_root else DATA_DIR / "browser_profiles",
            connect_timeout_ms=_positive_int_env(
                "LEGADOHUB_BROWSER_CONNECT_TIMEOUT_MS",
                cls.default_connect_timeout_ms,
            ),
            action_timeout_ms=_positive_int_env(
                "LEGADOHUB_BROWSER_ACTION_TIMEOUT_MS",
                cls.default_action_timeout_ms,
            ),
        )

    @property
    def enabled(self) -> bool:
        """Whether Source Access Bridge is enabled for runtime use."""
        if not self.enabled_by_env:
            return False
        if self.provider == "browserless":
            return bool(self.browserless_ws)
        return self.provider in {"chromium", "playwright"}

    def browserless_endpoint(self) -> str:
        """Return the Browserless WebSocket endpoint including token if needed."""
        if not self.browserless_ws or not self.browserless_token:
            return self.browserless_ws
        separator = "&" if "?" in self.browserless_ws else "?"
        return f"{self.browserless_ws}{separator}token={self.browserless_token}"





