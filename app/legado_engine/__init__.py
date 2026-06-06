"""Independent Legado rule engine package.

This package provides Legado-compatible rule execution without dependencies
on the admin/API layer. It is designed to be testable in isolation and
report capabilities explicitly.
"""

from app.legado_engine.models import (
    LegadoSource,
    RequestSpec,
    RuleContext,
    TraceEvent,
    EngineResult,
    EngineCapability,
)
from app.legado_engine.source_adapter import adapt_source_dict
from app.legado_engine.analyzer import LegadoAnalyzer
from app.legado_engine.capabilities import classify_capabilities

__all__ = [
    "LegadoSource",
    "RequestSpec",
    "RuleContext",
    "TraceEvent",
    "EngineResult",
    "EngineCapability",
    "adapt_source_dict",
    "LegadoAnalyzer",
    "classify_capabilities",
]
