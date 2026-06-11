"""Typed models for Source Access Bridge capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BrowserCookie:
    name: str
    value: str
    domain: str
    path: str = "/"
    expires: float | None = None
    http_only: bool = False
    secure: bool = False
    same_site: str = ""


@dataclass(frozen=True)
class BrowserChallengeState:
    detected: bool = False
    kind: str = ""
    message: str = ""
    url: str = ""


@dataclass(frozen=True)
class NetworkEntry:
    url: str
    method: str = "GET"
    status: int = 0
    resource_type: str = ""
    request_headers: dict[str, str] = field(default_factory=dict)
    response_headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DomSnapshot:
    title: str = ""
    url: str = ""
    text: str = ""
    links: list[dict[str, str]] = field(default_factory=list)
    forms: list[dict[str, Any]] = field(default_factory=list)
    buttons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AccessFetchRequest:
    plugin_id: str
    url: str
    stage: str = ""
    method: str = "GET"
    headers: dict[str, str] = field(default_factory=dict)
    data: dict[str, Any] | None = None
    profile_id: str = ""
    proxy_profile: str = ""
    wait_ms: int = 2500
    timeout_ms: int = 90000
    capture_network: bool = False
    dom_snapshot: bool = False


@dataclass(frozen=True)
class AccessFetchResult:
    ok: bool
    final_url: str
    title: str = ""
    html: str = ""
    cookies: list[BrowserCookie | dict[str, Any]] = field(default_factory=list)
    challenge: BrowserChallengeState | dict[str, Any] = field(default_factory=BrowserChallengeState)
    network: list[NetworkEntry | dict[str, Any]] = field(default_factory=list)
    dom_snapshot: DomSnapshot | dict[str, Any] | None = None
    proxy_used: bool = False
    profile_id: str = ""
    elapsed_ms: int = 0
    error: str = ""


@dataclass(frozen=True)
class SearchProviderHit:
    title: str
    url: str
    provider: str
    rank: int = 0
    snippet: str = ""
    matched_pattern: str = ""
