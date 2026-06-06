"""Rule context with @put/@get storage and variable replacement."""

from __future__ import annotations

from app.legado_engine.models import RuleContext


def create_context(base_url: str = "", variables: dict | None = None) -> RuleContext:
    return RuleContext(
        base_url=base_url,
        variables=variables or {},
        storage={},
    )


def context_put(ctx: RuleContext, key: str, value) -> None:
    ctx.put(key, value)


def context_get(ctx: RuleContext, key: str, default=None):
    return ctx.get(key, default)
