from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.source_plugins.scheduler import PluginScheduler


def test_chapter_review_media_requires_declared_media_capability() -> None:
    scheduler = object.__new__(PluginScheduler)
    scheduler._plugins = {
        "example": SimpleNamespace(
            metadata=SimpleNamespace(enabled=True),
            capabilities=["chapter_reviews"],
            source=SimpleNamespace(
                chapter_review_media=lambda *_args: (_ for _ in ()).throw(
                    AssertionError("media method must not be called")
                ),
            ),
        ),
    }
    scheduler._make_ctx = lambda _source_id: (_ for _ in ()).throw(
        AssertionError("context must not be created")
    )

    result = asyncio.run(
        scheduler.chapter_review_media("example", "https://example.test/chapter", "image.jpg")
    )

    assert result["bytes"] == b""
    assert "chapter review media" in result["debug"]["error"]
