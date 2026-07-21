"""Reading-compatible API end-to-end fixture loop."""

import sqlite3
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.source_plugins.loader import PluginLoader
from app.source_plugins.smoke import FixtureFetcher


def _write_reading_plugin(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    plugin_id = "fixture_reading"
    plugin_dir = tmp_path / plugin_id
    fixture_dir = plugin_dir / "smoke" / "fixtures"
    fixture_dir.mkdir(parents=True)
    metadata = {
        "contractVersion": "1.0",
        "id": plugin_id,
        "name": "Fixture Reading",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search", "detail", "toc", "chapter", "chapter_reviews"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "tags": ["fixture"],
    }
    (plugin_dir / "metadata.yaml").write_text(yaml.safe_dump(metadata, allow_unicode=True), encoding="utf-8")
    (plugin_dir / "source.py").write_text(
        '''
class Source:
    id = "fixture_reading"
    name = "Fixture Reading"
    contract_version = "1.0"

    async def search(self, ctx, keyword: str, page: int):
        html = await ctx.access.http.fetch_text("https://example.com/search")
        return [{
            "sourceId": self.id,
            "name": ctx.text(html, ".name"),
            "author": ctx.text(html, ".author"),
            "bookUrl": ctx.urljoin("https://example.com", ctx.attr(html, ".name", "href")),
            "lastChapter": ctx.text(html, ".latest"),
        }]

    async def detail(self, ctx, book_url: str):
        html = await ctx.access.http.fetch_text(book_url)
        return {
            "sourceId": self.id,
            "name": ctx.text(html, "h1"),
            "author": ctx.text(html, ".author"),
            "bookUrl": book_url,
            "tocUrl": book_url,
            "lastChapter": ctx.text(html, ".latest"),
        }

    async def toc(self, ctx, toc_url: str):
        html = await ctx.access.http.fetch_text(toc_url)
        return [
            {"sourceId": self.id, "index": index, "title": a.text_content().strip(), "chapterUrl": ctx.urljoin(toc_url, a.get("href", ""))}
            for index, a in enumerate(ctx.select(html, ".chapters a"), start=1)
        ]

    async def chapter(self, ctx, chapter_url: str):
        html = await ctx.access.http.fetch_text(chapter_url)
        return {"sourceId": self.id, "title": ctx.text(html, "h1"), "chapterUrl": chapter_url, "content": ctx.html(html, "#content")}

    async def chapter_reviews(self, ctx, chapter_url: str):
        return {
            "paragraphs": {
                "1": [{
                    "id": "review-1",
                    "content": "第一段评论",
                    "userName": "读者甲",
                    "likeNum": 3,
                    "replyCount": 0,
                    "reviewTime": "刚刚",
                    "paragraphId": 1,
                    "isTop": False,
                }]
            },
            "chapterEnd": [{
                "id": "review-end",
                "content": "章末评论",
                "userName": "读者乙",
                "likeNum": 1,
                "replyCount": 0,
                "reviewTime": "刚刚",
                "paragraphId": -1,
                "isTop": False,
            }],
            "summary": {
                "totalParagraphs": 1,
                "totalReviews": 2,
                "paragraphsWithReviews": [1],
                "chapterEndCount": 1,
                "authMode": "public",
            },
        }
''',
        encoding="utf-8",
    )
    search_html = (
        '<html><body><a class="name" href="/book/1/">凡人修仙传</a>'
        '<span class="author">忘语</span><span class="latest">第一章 初入修仙</span></body></html>'
    )
    detail_html = (
        '<html><body><h1>凡人修仙传</h1><span class="author">忘语</span>'
        '<span class="latest">第一章 初入修仙</span>'
        '<div class="chapters"><a href="/book/1/1.html">第一章 初入修仙</a></div></body></html>'
    )
    chapter_html = (
        '<html><body><h1>第一章 初入修仙</h1>'
        '<div id="content">这是 Reading API 端到端 fixture 正文，长度超过二十个字符。</div></body></html>'
    )
    return plugin_dir, {
        "https://example.com/search": search_html,
        "https://example.com/book/1/": detail_html,
        "https://example.com/book/1/1.html": chapter_html,
    }


@pytest.fixture
def fixture_client(monkeypatch, tmp_path):
    _, responses = _write_reading_plugin(tmp_path)
    from app.source_plugins.scheduler import PluginScheduler
    import app.api.legado as legado_api

    original_init = PluginScheduler.__init__

    def patched_init(self, loader=None, config=None):
        loader = loader or PluginLoader(plugins_dir=tmp_path)
        original_init(self, loader=loader, config=config or {})

    monkeypatch.setattr(PluginScheduler, "__init__", patched_init)
    monkeypatch.setattr(PluginScheduler, "_make_fetcher", lambda self: FixtureFetcher(responses))
    import app.source_plugins.scheduler as scheduler_module
    monkeypatch.setattr(scheduler_module, "_scheduler_instance", None)

    from app.storage.db import initialize_database

    cache_db = tmp_path / "reading-cache.db"
    initialize_database(cache_db)
    monkeypatch.setattr("app.config.DB_PATH", cache_db)
    monkeypatch.setattr("app.services.cache.DB_PATH", cache_db)
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert login.status_code == 200
    return client


def test_reading_rejects_direct_plugin_book_without_database_side_effects(fixture_client, tmp_path):
    from app.source_plugins.id_codec import encode_book_id

    book_id = encode_book_id("fixture_reading", "https://example.com/book/1/")

    response = fixture_client.get(f"/api/legado/book/{book_id}")

    assert response.status_code == 404
    with sqlite3.connect(tmp_path / "reading-cache.db") as conn:
        row = conn.execute(
            "SELECT book_id FROM book_records WHERE book_id = ?",
            (book_id,),
        ).fetchone()
    assert row is None


def test_reading_rejects_all_direct_plugin_reader_routes(fixture_client, monkeypatch):
    from app.services.catalog import Catalog
    from app.source_plugins.id_codec import encode_book_id, encode_chapter_id

    book_id = encode_book_id("fixture_reading", "https://example.com/book/1/")
    chapter_id = encode_chapter_id("fixture_reading", "https://example.com/book/1/1.html")

    async def must_not_call(*_args, **_kwargs):
        pytest.fail("rejected direct plugin ids must not reach Catalog")

    monkeypatch.setattr(Catalog, "book_detail", must_not_call)
    monkeypatch.setattr(Catalog, "toc", must_not_call)
    monkeypatch.setattr(Catalog, "chapter", must_not_call)
    monkeypatch.setattr(Catalog, "chapter_reviews", must_not_call)

    assert fixture_client.get(f"/api/legado/book/{book_id}").status_code == 404
    assert fixture_client.get(f"/api/legado/book/{book_id}/toc").status_code == 404
    assert fixture_client.get(f"/api/legado/chapter/{chapter_id}").status_code == 404
    assert fixture_client.get(f"/api/legado/chapter/{chapter_id}/reviews").status_code == 404
    assert fixture_client.get(f"/api/legado/chapter/{chapter_id}/reviews/view").status_code == 404


def test_review_view_allows_only_same_origin_embedding(fixture_client, monkeypatch):
    import app.api.legado as legado_api
    from app.services.aggregate_virtual_source import VIRTUAL_SOURCE_ID, make_aggregate_chapter_url
    from app.source_plugins.id_codec import encode_chapter_id

    chapter_id = encode_chapter_id(
        VIRTUAL_SOURCE_ID,
        make_aggregate_chapter_url("book-1", "chapter-1", index=1),
    )
    monkeypatch.setattr(
        legado_api.library_books_service,
        "legado_chapter",
        lambda _chapter_id: {"title": "第一章"},
    )

    async def empty_reviews(_chapter_id: str) -> dict:
        return {
            "authorReviews": [],
            "chapterEnd": [],
            "hotParagraphReviews": [],
            "summary": {"totalReviews": 0, "chapterEndCount": 0},
        }

    monkeypatch.setattr(legado_api, "_chapter_reviews", empty_reviews)

    api_response = fixture_client.get(f"/api/legado/chapter/{chapter_id}/reviews")
    view_response = fixture_client.get(f"/api/legado/chapter/{chapter_id}/reviews/view")

    assert api_response.status_code == 200
    assert api_response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in api_response.headers["content-security-policy"]
    assert view_response.status_code == 200
    assert view_response.headers["x-frame-options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in view_response.headers["content-security-policy"]


def test_reading_direct_plugin_chapter_does_not_use_cached_content(fixture_client):
    from app.services.catalog import Catalog
    from app.source_plugins.id_codec import encode_chapter_id

    chapter_id = encode_chapter_id("fixture_reading", "https://example.com/book/1/1.html")
    catalog = Catalog()
    catalog.cache.set_chapter(
        chapter_id,
        "fixture_reading",
        "https://example.com/book/1/1.html",
        {
            "implemented": True,
            "chapterId": chapter_id,
            "title": "缓存章节",
            "content": "缓存正文",
            "debug": {},
        },
    )

    chapter_res = fixture_client.get(f"/api/legado/chapter/{chapter_id}")

    assert chapter_res.status_code == 404
