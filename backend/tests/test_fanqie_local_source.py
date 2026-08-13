from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path


SOURCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "sources"
    / "official"
    / "fanqie_local"
    / "source.py"
)
SPEC = importlib.util.spec_from_file_location("test_fanqie_local_source", SOURCE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
Source = MODULE.Source


class _Http:
    def __init__(self) -> None:
        self.urls: list[str] = []

    async def fetch_json(self, url: str, **kwargs):
        self.urls.append(url)
        if url.endswith("/api/search"):
            return {
                "items": [
                    {
                        "book_id": "7156171587174009864",
                        "title": "软件测试",
                        "author": "黑马程序员",
                        "raw": {
                            "abstract": "软件测试理论与实践相结合。",
                            "audio_thumb_url_hd": "https://example.test/cover.heic",
                            "word_count": "123456",
                            "category_name": "教育",
                            "last_chapter_title": "第9章 测试文档",
                            "book_tags": ["教材", "计算机"],
                        },
                    }
                ]
            }
        raise AssertionError(f"search must not call the preview endpoint: {url}")


class _Context:
    def __init__(self) -> None:
        self.access = type("Access", (), {"http": _Http()})()
        self.traces: list[dict] = []

    def trace(self, stage: str, **payload) -> None:
        self.traces.append({"stage": stage, **payload})

    @staticmethod
    def cache_get(key: str):
        return None

    @staticmethod
    def cache_set(key: str, value, ttl_seconds: int = 300) -> None:
        return None


def test_search_maps_raw_metadata_without_preview_requests() -> None:
    ctx = _Context()

    items = asyncio.run(Source().search(ctx, "test", 1))

    assert ctx.access.http.urls == [f"{MODULE.TOMATO_BASE}/api/search"]
    assert items == [
        {
            "sourceId": "fanqie_local",
            "name": "软件测试",
            "author": "黑马程序员",
            "bookUrl": f"{MODULE.TOMATO_BASE}/__fanqie__/7156171587174009864",
            "coverUrl": "https://example.test/cover.heic",
            "intro": "软件测试理论与实践相结合。",
            "kind": "教育/教材/计算机",
            "lastChapter": "第9章 测试文档",
            "wordCount": "12万字",
            "extra": {"book_id": "7156171587174009864"},
        }
    ]
