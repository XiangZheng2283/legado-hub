"""Diagnostic normalization tests for plugin smoke failures."""

from pathlib import Path

import pytest
import yaml

from app.source_plugins.errors import normalize_failure
from app.source_plugins.loader import PluginLoader
from app.source_plugins.smoke import run_fixture_smoke


def _write_diag_plugin(tmp_path: Path, behavior: str) -> Path:
    plugin_id = f"diag_{behavior}"
    plugin_dir = tmp_path / plugin_id
    fixture_dir = plugin_dir / "tests" / "fixtures"
    fixture_dir.mkdir(parents=True)
    metadata = {
        "contractVersion": "1.0",
        "id": plugin_id,
        "name": plugin_id,
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search", "detail", "toc", "chapter"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "tags": ["fixture"],
    }
    (plugin_dir / "metadata.yaml").write_text(yaml.safe_dump(metadata), encoding="utf-8")
    search_body = {
        "empty": "return []",
        "timeout": "import asyncio\n        await asyncio.sleep(20)\n        return []",
        "runtime": "raise RuntimeError('boom')",
    }.get(
        behavior,
        'return [{"sourceId": self.id, "name": "凡人修仙传", "author": "忘语", "bookUrl": "https://example.com/book/1/"}]',
    )
    (plugin_dir / "source.py").write_text(
        f'''
class Source:
    id = "{plugin_id}"
    name = "{plugin_id}"
    contract_version = "1.0"

    async def search(self, ctx, keyword: str, page: int):
        {search_body}

    async def detail(self, ctx, book_url: str):
        return {{"sourceId": self.id, "name": "凡人修仙传", "author": "忘语", "bookUrl": book_url, "tocUrl": book_url}}

    async def toc(self, ctx, toc_url: str):
        return [{{"sourceId": self.id, "index": 1, "title": "第一章", "chapterUrl": "https://example.com/book/1/1.html"}}]

    async def chapter(self, ctx, chapter_url: str):
        return {{"sourceId": self.id, "title": "第一章", "chapterUrl": chapter_url, "content": "这是足够长的正文内容，用于诊断测试。"}}
''',
        encoding="utf-8",
    )
    (plugin_dir / "tests" / "smoke.yaml").write_text(
        yaml.safe_dump(
            {
                "keyword": "凡人修仙传",
                "fixtures": {
                    "search": {"url": "https://example.com/search", "file": "search.html"},
                    "detail": {"url": "https://example.com/book/1/", "file": "detail.html"},
                    "toc": {"url": "https://example.com/book/1/", "file": "toc.html"},
                    "chapter": {"url": "https://example.com/book/1/1.html", "file": "chapter.html"},
                },
                "expect": {
                    "search": {"minResults": 1},
                    "toc": {"minChapters": 1},
                    "chapter": {"minContentLength": 20},
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    for name in ("search.html", "detail.html", "toc.html", "chapter.html"):
        (fixture_dir / name).write_text("<html><body>ok</body></html>", encoding="utf-8")
    return plugin_dir


def test_normalize_failure_includes_hint_and_url():
    failure = normalize_failure(
        source_id="xbiqugu_la",
        stage="search",
        code="PARSE_EMPTY",
        message="no rows",
        url="https://example.com/search",
    )

    assert failure["sourceId"] == "xbiqugu_la"
    assert failure["code"] == "PARSE_EMPTY"
    assert failure["url"] == "https://example.com/search"
    assert failure["hint"]


@pytest.mark.asyncio
async def test_missing_fixture_reports_smoke_fixture_missing(tmp_path):
    plugin_dir = _write_diag_plugin(tmp_path, "ok")
    (plugin_dir / "tests" / "fixtures" / "search.html").unlink()
    plugin = PluginLoader(plugins_dir=tmp_path).load_all()["diag_ok"]

    result = await run_fixture_smoke(plugin, plugin_dir)

    assert result["errors"][0]["code"] == "SMOKE_FIXTURE_MISSING"
    assert result["errors"][0]["hint"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("behavior", "code"),
    [("empty", "PARSE_EMPTY"), ("timeout", "PLUGIN_TIMEOUT"), ("runtime", "PLUGIN_RUNTIME_ERROR")],
)
async def test_fixture_smoke_normalizes_stage_failures(tmp_path, behavior, code):
    plugin_dir = _write_diag_plugin(tmp_path, behavior)
    plugin = PluginLoader(plugins_dir=tmp_path).load_all()[f"diag_{behavior}"]

    result = await run_fixture_smoke(plugin, plugin_dir, stage_timeout=0.01 if behavior == "timeout" else 15.0)

    assert any(error["code"] == code and error["hint"] for error in result["errors"]), result
