"""Fixture-backed smoke runner tests."""

from pathlib import Path

import pytest
import yaml

from app.source_plugins.loader import PluginLoader
from app.source_plugins.smoke import load_smoke_spec, run_fixture_smoke


def _write_plugin(tmp_path: Path, plugin_id: str = "fixture_site") -> Path:
    plugin_dir = tmp_path / plugin_id
    fixture_dir = plugin_dir / "tests" / "fixtures"
    fixture_dir.mkdir(parents=True)
    metadata = {
        "contractVersion": "1.0",
        "id": plugin_id,
        "name": "Fixture Site",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search", "detail", "toc", "chapter"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "tags": ["fixture"],
    }
    (plugin_dir / "metadata.yaml").write_text(yaml.safe_dump(metadata, allow_unicode=True), encoding="utf-8")
    (plugin_dir / "source.py").write_text(
        f'''
class Source:
    id = "{plugin_id}"
    name = "Fixture Site"
    contract_version = "1.0"

    async def search(self, ctx, keyword: str, page: int):
        html = await ctx.access.http.fetch_text("https://example.com/search")
        name = ctx.text(html, ".name")
        author = ctx.text(html, ".author")
        href = ctx.attr(html, ".name", "href")
        return [{{"sourceId": self.id, "name": name, "author": author, "bookUrl": ctx.urljoin("https://example.com", href)}}]

    async def detail(self, ctx, book_url: str):
        html = await ctx.access.http.fetch_text(book_url)
        return {{
            "sourceId": self.id,
            "name": ctx.text(html, "h1"),
            "author": ctx.text(html, ".author"),
            "bookUrl": book_url,
            "tocUrl": book_url,
        }}

    async def toc(self, ctx, toc_url: str):
        html = await ctx.access.http.fetch_text(toc_url)
        return [
            {{"sourceId": self.id, "index": index, "title": a.text_content().strip(), "chapterUrl": ctx.urljoin(toc_url, a.get("href", ""))}}
            for index, a in enumerate(ctx.select(html, ".chapters a"), start=1)
        ]

    async def chapter(self, ctx, chapter_url: str):
        html = await ctx.access.http.fetch_text(chapter_url)
        return {{"sourceId": self.id, "title": ctx.text(html, "h1"), "chapterUrl": chapter_url, "content": ctx.html(html, "#content")}}
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
                    "search": {"minResults": 1, "firstName": "凡人修仙传"},
                    "detail": {"name": "凡人修仙传", "author": "忘语", "hasTocUrl": True},
                    "toc": {"minChapters": 1, "firstTitleContains": "第"},
                    "chapter": {"minContentLength": 20, "titleContains": "第"},
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (fixture_dir / "search.html").write_text(
        '<html><body><a class="name" href="/book/1/">凡人修仙传</a><span class="author">忘语</span></body></html>',
        encoding="utf-8",
    )
    book_html = (
        '<html><body><h1>凡人修仙传</h1><span class="author">忘语</span>'
        '<div class="chapters"><a href="/book/1/1.html">第一章 初入修仙</a></div></body></html>'
    )
    (fixture_dir / "detail.html").write_text(book_html, encoding="utf-8")
    (fixture_dir / "toc.html").write_text(book_html, encoding="utf-8")
    (fixture_dir / "chapter.html").write_text(
        "<html><body><h1>第一章 初入修仙</h1><div id=\"content\">这是足够长的正文内容，用于验证本地 fixture smoke 可以完整走通章节解析。</div></body></html>",
        encoding="utf-8",
    )
    return plugin_dir


@pytest.mark.asyncio
async def test_fixture_smoke_passes(tmp_path):
    plugin_dir = _write_plugin(tmp_path)
    plugin = PluginLoader(plugins_dir=tmp_path).load_all()["fixture_site"]

    result = await run_fixture_smoke(plugin, plugin_dir)

    assert result["pass"] is True
    assert result["mode"] == "fixture"
    assert result["stages"]["search"]["count"] == 1
    assert result["stages"]["toc"]["count"] == 1
    assert result["stages"]["chapter"]["contentLength"] >= 20
    assert result["errors"] == []


def test_load_smoke_spec_requires_fixtures(tmp_path):
    plugin_dir = tmp_path / "bad"
    (plugin_dir / "tests").mkdir(parents=True)
    (plugin_dir / "tests" / "smoke.yaml").write_text("keyword: test\n", encoding="utf-8")

    with pytest.raises(ValueError, match="fixtures"):
        load_smoke_spec(plugin_dir)


@pytest.mark.asyncio
async def test_fixture_smoke_reports_missing_file(tmp_path):
    plugin_dir = _write_plugin(tmp_path)
    (plugin_dir / "tests" / "fixtures" / "chapter.html").unlink()
    plugin = PluginLoader(plugins_dir=tmp_path).load_all()["fixture_site"]

    result = await run_fixture_smoke(plugin, plugin_dir)

    assert result["pass"] is False
    assert result["errors"][0]["code"] == "SMOKE_FIXTURE_MISSING"






