from __future__ import annotations

import httpx
from types import SimpleNamespace

from app.source_plugins.fetcher import Fetcher
from app.source_plugins.scheduler import PluginScheduler


def test_legacy_iso_header_falls_back_to_gbk() -> None:
    response = httpx.Response(
        200,
        content="天启预报".encode("gbk"),
        headers={"content-type": "text/html; charset=ISO-8859-1"},
    )

    assert Fetcher()._decode_response_text(response) == "天启预报"


def test_toc_timeout_uses_existing_hard_source_limit() -> None:
    scheduler = object.__new__(PluginScheduler)
    scheduler.config = {
        "source_timeout_seconds": 8.0,
        "source_hard_timeout_seconds": 25.0,
    }
    plugin = SimpleNamespace(metadata=SimpleNamespace(browser={}))

    assert scheduler.toc_timeout_for_plugin(plugin) == 25.0
