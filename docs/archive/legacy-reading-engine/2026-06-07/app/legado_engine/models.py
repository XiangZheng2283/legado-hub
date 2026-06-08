"""Core data models for the Legado engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LegadoSource:
    source_id: str
    source_name: str
    source_url: str
    search_url: str = ""
    explore_url: str = ""
    header: str = ""
    enabled_cookie_jar: bool = False
    rule_search: dict = field(default_factory=dict)
    rule_book_info: dict = field(default_factory=dict)
    rule_toc: dict = field(default_factory=dict)
    rule_content: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


@dataclass
class RequestSpec:
    url: str
    method: str = "GET"
    body: str | None = None
    headers: dict = field(default_factory=dict)
    charset: str = "utf-8"


@dataclass
class RuleContext:
    base_url: str = ""
    variables: dict = field(default_factory=dict)
    storage: dict = field(default_factory=dict)
    last_result: Any = None

    def put(self, key: str, value: Any) -> None:
        self.storage[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.storage.get(key, default)

    def replace_vars(self, text: str) -> str:
        for key, value in self.variables.items():
            text = text.replace(f"{{{{{key}}}}}", str(value))
        return text


@dataclass
class TraceEvent:
    stage: str
    source_id: str
    url: str = ""
    extractor_type: str = ""
    rule_path: str = ""
    proxy_used: bool = False
    latency_ms: int = 0
    error: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "sourceId": self.source_id,
            "url": self.url,
            "extractorType": self.extractor_type,
            "rulePath": self.rule_path,
            "proxyUsed": self.proxy_used,
            "latencyMs": self.latency_ms,
            "error": self.error,
            "timestamp": self.timestamp,
        }


@dataclass
class EngineResult:
    success: bool
    data: Any = None
    trace: list[TraceEvent] = field(default_factory=list)
    error: str = ""
    unsupported_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "trace": [t.to_dict() for t in self.trace],
            "error": self.error,
            "unsupportedReasons": self.unsupported_reasons,
        }


@dataclass
class EngineCapability:
    name: str
    supported: bool
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "supported": self.supported,
            "notes": self.notes,
        }
