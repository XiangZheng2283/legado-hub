from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.access_bridge import facade
from app.services.access_bridge.facade import SourceAccessBridge
from app.services.access_bridge.search_provider import duckduckgo_library_search


@pytest.mark.asyncio
async def test_search_provider_keeps_fetcher_proxy_policy(monkeypatch) -> None:
    calls: list[dict] = []

    async def fake_fetch_text(_url: str, **kwargs) -> str:
        calls.append(kwargs)
        return ""

    async def fake_search_site(_keyword: str, *, fetch_text, **_kwargs) -> list:
        await fetch_text("https://www.bing.com/search")
        return []

    ctx = SimpleNamespace(proxy_mode="auto", trace=lambda *_args, **_kwargs: None)
    bridge = SourceAccessBridge(ctx)
    ctx.access = bridge
    monkeypatch.setattr(bridge.http, "fetch_text", fake_fetch_text)
    monkeypatch.setattr(facade, "search_site", fake_search_site)

    await bridge.search_provider(
        "测试",
        target_domain="example.test",
        url_patterns=[r"/book/\\d+"],
        provider_order=["bing_html"],
    )

    assert calls == [{"headers": facade.DEFAULT_HEADERS, "timeout": 5.0, "proxy": True}]


@pytest.mark.asyncio
async def test_ddgs_search_retries_transient_failures(monkeypatch) -> None:
    calls = 0

    class FakeDDGS:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def text(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RuntimeError("temporary limit")
            return [{"title": "测试", "href": "https://example.test/book/1"}]

    monkeypatch.setitem(sys.modules, "ddgs", SimpleNamespace(DDGS=FakeDDGS))

    rows = await duckduckgo_library_search(
        "测试",
        target_domain="example.test",
        query_site_path="/book",
    )

    assert calls == 3
    assert rows[0]["href"] == "https://example.test/book/1"


def _load_source(plugin_id: str):
    source_path = Path(__file__).resolve().parents[2] / "plugins" / "sources" / "thirdparty" / plugin_id / "source.py"
    spec = importlib.util.spec_from_file_location(f"test_{plugin_id}", source_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Source()


@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_id", ["96dushu_com", "xiaoshuohu_com"])
async def test_search_provider_plugins_do_not_disable_proxy(plugin_id: str) -> None:
    calls: list[dict] = []

    async def search_provider(*_args, **kwargs) -> list:
        calls.append(kwargs)
        return []

    async def fetch_text(*_args, **_kwargs) -> str:
        return "<html></html>"

    ctx = SimpleNamespace(
        access=SimpleNamespace(
            search_provider=search_provider,
            http=SimpleNamespace(fetch_text=fetch_text),
        ),
        select=lambda *_args: [],
    )

    assert await _load_source(plugin_id).search(ctx, "测试", 1) == []
    assert "proxy" not in calls[0]


@pytest.mark.asyncio
async def test_69shuba_tw_search_does_not_scan_explore_pages_after_failure() -> None:
    source = _load_source("69shuba_tw")
    calls = 0

    async def failed_fetch(*_args, **_kwargs) -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("browser unavailable")

    source._fetch = failed_fetch
    ctx = SimpleNamespace(to_traditional=lambda value: value)

    assert await source.search(ctx, "测试", 1) == []
    assert calls == 1


@pytest.mark.asyncio
async def test_69shuba_search_rejects_unrelated_provider_hit() -> None:
    source = _load_source("69shuba_com")

    async def search_provider(*_args, **_kwargs) -> list:
        return [SimpleNamespace(
            title="高天之上",
            url="https://www.69shuba.com/book/51261",
            provider="duckduckgo_ddgs",
            snippet="",
            matched_pattern=r"/book/\d+",
        )]

    async def detail(_ctx, _url: str) -> dict:
        return {"name": "高天之上", "author": "阴天神隐"}

    source.detail = detail
    ctx = SimpleNamespace(
        access=SimpleNamespace(search_provider=search_provider),
        clean_text=lambda value: str(value or "").strip(),
        trace=lambda *_args, **_kwargs: None,
    )

    assert await source._search_provider_search(ctx, "天命之上") == []
