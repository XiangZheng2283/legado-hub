"""Reading-compatible API end-to-end fixture loop."""

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
    fixture_dir = plugin_dir / "tests" / "fixtures"
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
    monkeypatch.setattr(legado_api, "_search_service", None)
    monkeypatch.setattr(legado_api, "_search_service_init_token", None)
    return TestClient(app)


def test_reading_api_fixture_loop(fixture_client):
    source_res = fixture_client.get("/api/legado/source")
    assert source_res.status_code == 200
    assert len(source_res.json()) >= 1

    search_res = fixture_client.get("/api/legado/search", params={"keyword": "凡人修仙传-stage2", "page": 1})
    assert search_res.status_code == 200
    search_data = search_res.json()
    assert search_data["implemented"] is True
    assert len(search_data["items"]) >= 1
    # Filter out aggregate virtual source, keep original plugin results
    original_items = [i for i in search_data["items"] if not i.get("aggregate")]
    assert len(original_items) >= 1
    book_url = original_items[0]["bookUrl"]
    assert "/api/legado/book/" in book_url

    detail_res = fixture_client.get(book_url.replace("http://127.0.0.1:8765", ""))
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["data"]["name"] == "凡人修仙传"
    assert detail["data"]["author"] == "忘语"
    assert "/api/legado/book/" in detail["data"]["tocUrl"]

    toc_res = fixture_client.get(detail["data"]["tocUrl"].replace("http://127.0.0.1:8765", ""))
    assert toc_res.status_code == 200
    toc = toc_res.json()
    assert len(toc["chapters"]) == 1
    chapter_url = toc["chapters"][0]["chapterUrl"]
    assert "/api/legado/chapter/" in chapter_url

    chapter_res = fixture_client.get(chapter_url.replace("http://127.0.0.1:8765", ""))
    assert chapter_res.status_code == 200
    chapter = chapter_res.json()
    assert "第一章" in chapter["title"]
    assert len(chapter["content"]) > 20

    chapter_id = chapter_url.rsplit("/", 1)[-1]
    reviews_res = fixture_client.get(f"/api/legado/chapter/{chapter_id}/reviews")
    assert reviews_res.status_code == 200
    reviews = reviews_res.json()
    assert reviews["paragraphs"]["1"][0]["content"] == "第一段评论"
    assert reviews["chapterEnd"][0]["content"] == "章末评论"


def test_reading_api_chapter_falls_back_to_cache_on_timeout(fixture_client, monkeypatch):
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

    async def timeout_chapter(self, source_id: str, chapter_url: str):
        return {
            "implemented": True,
            "chapterId": "",
            "title": "",
            "content": "",
            "debug": {"error": {"code": "PLUGIN_TIMEOUT", "message": "timeout"}},
        }

    monkeypatch.setattr("app.services.catalog.PluginScheduler.chapter", timeout_chapter)

    chapter_res = fixture_client.get(f"/api/legado/chapter/{chapter_id}")

    assert chapter_res.status_code == 200
    chapter = chapter_res.json()
    assert chapter["title"] == "缓存章节"
    assert chapter["debug"]["cacheHit"] is True
    assert chapter["debug"]["cacheReason"] == "timeout"


