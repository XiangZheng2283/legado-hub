"""Tests for live acceptance models, grouping, and persistence."""

from app.services.live_acceptance import group_candidates
from app.services.live_check_repository import LiveCheckRepository
from app.storage.db import initialize_database


def test_group_candidates_keeps_book_with_source_items():
    items = [
        {"sourceId": "a", "sourceName": "A", "name": "凡人修仙传", "author": "忘语", "bookUrl": "https://a/book"},
        {"sourceId": "b", "sourceName": "B", "name": "凡人修仙传", "author": "忘语", "bookUrl": "https://b/book"},
        {"sourceId": "c", "sourceName": "C", "name": "凡人修仙传外传", "author": "佚名", "bookUrl": "https://c/book"},
    ]

    groups = group_candidates(items, "凡人修仙传")

    assert len(groups) == 2
    assert groups[0]["name"] == "凡人修仙传"
    assert groups[0]["sourceCount"] == 2
    assert {item["sourceId"] for item in groups[0]["items"]} == {"a", "b"}
    assert groups[0]["scoreReasons"][0] == "exact_title"


def test_group_candidates_merges_same_title_when_one_source_lacks_author():
    items = [
        {"sourceId": "a", "sourceName": "A", "name": "剑宗外门", "author": "佚名", "bookUrl": "https://a/book"},
        {"sourceId": "b", "sourceName": "B", "name": "剑宗外门", "author": "天蚕土豆", "bookUrl": "https://b/book"},
    ]

    groups = group_candidates(items, "剑宗外门")

    assert len(groups) == 1
    assert groups[0]["name"] == "剑宗外门"
    assert groups[0]["author"] == "天蚕土豆"
    assert {item["sourceId"] for item in groups[0]["items"]} == {"a", "b"}


def test_group_candidates_prefers_official_source_as_best(monkeypatch):
    class FakePlugin:
        def __init__(self, official: bool):
            self.metadata = type("M", (), {"is_official_source": lambda self: official})()

    monkeypatch.setattr(
        "app.services.live_acceptance.PluginLoader.load_all",
        lambda self: {
            "official_a": FakePlugin(True),
            "normal_b": FakePlugin(False),
        },
    )

    items = [
        {"sourceId": "normal_b", "sourceName": "普通源", "name": "凡人修仙传", "author": "忘语", "bookUrl": "https://b/book", "score": 500},
        {"sourceId": "official_a", "sourceName": "官方源", "name": "凡人修仙传", "author": "忘语", "bookUrl": "https://a/book", "score": 120},
    ]

    groups = group_candidates(items, "凡人修仙传")

    assert len(groups) == 1
    assert groups[0]["bestSourceId"] == "official_a"
    assert groups[0]["hasOfficialSource"] is True
    assert groups[0]["primaryOfficialSourceId"] == "official_a"
    assert groups[0]["officialSourceIds"] == ["official_a"]
    assert groups[0]["isPrimarySourceOfficial"] is True


def test_live_check_repository_records_latest(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.storage.db.DB_PATH", db_path)
    monkeypatch.setattr("app.services.live_check_repository.DB_PATH", db_path)
    initialize_database(db_path)
    repo = LiveCheckRepository()

    stored = repo.record(
        {
            "pluginId": "22biqu_com",
            "keyword": "凡人修仙传",
            "status": "passed",
            "search": {"count": 1},
            "selectedCandidate": {"name": "凡人修仙传", "author": "忘语"},
            "toc": {"chapterCount": 10},
            "chapter": {"title": "第1章", "contentLength": 1200},
            "diagnostics": [],
        }
    )

    latest = repo.latest_by_plugin("22biqu_com")
    assert stored["id"] > 0
    assert latest is not None
    assert latest["status"] == "passed"
    assert latest["searchCount"] == 1
    assert latest["contentLength"] == 1200


def test_live_acceptance_result_exposes_reader_payload():
    from app.services.live_acceptance import LiveAcceptanceService

    service = LiveAcceptanceService()
    result = service._result(
        "source_a",
        "凡人修仙传",
        "passed",
        [{"sourceId": "source_a", "sourceName": "书源A", "name": "凡人修仙传", "author": "忘语", "bookUrl": "https://a/book"}],
        {"sourceId": "source_a", "sourceName": "书源A", "name": "凡人修仙传", "author": "忘语", "bookUrl": "https://a/book"},
        {"name": "凡人修仙传", "author": "忘语", "coverUrl": "https://a/cover.jpg", "intro": "简介", "tocUrl": "https://a/book"},
        [{"title": "第一章", "chapterUrl": "https://a/1.html"}],
        {"title": "第一章", "chapterUrl": "https://a/1.html", "content": "第一段\n\n第二段"},
        0,
        [],
        explore_groups=[{"sourceId": "source_a", "groupId": "rank_all", "title": "总排行榜"}],
        explore_items=[{"sourceId": "source_a", "name": "凡人修仙传", "bookUrl": "https://a/book"}],
        explore_selected={"sourceId": "source_a", "name": "凡人修仙传", "bookUrl": "https://a/book", "groupId": "rank_all", "groupTitle": "总排行榜"},
        explore_detail={"name": "凡人修仙传", "tocUrl": "https://a/book"},
        explore_toc_items=[{"title": "第一章", "chapterUrl": "https://a/1.html"}],
        explore_chapter={"title": "第一章", "content": "正文" * 300},
    )

    assert result["detail"]["coverUrl"] == "https://a/cover.jpg"
    assert result["detail"]["intro"] == "简介"
    assert result["toc"]["items"][0]["title"] == "第一章"
    assert result["chapter"]["content"] == "第一段\n\n第二段"
    assert result["explore"]["groupCount"] == 1
    assert result["explore"]["selected"]["groupId"] == "rank_all"
    assert result["explore"]["passed"] is True


import pytest


@pytest.mark.asyncio
async def test_live_acceptance_result_marks_browser_bypass_required():
    from types import SimpleNamespace
    from app.services.live_acceptance import LiveAcceptanceService
    from app.source_plugins.errors import CloudflareRequired
    from app.source_plugins.models import PluginMetadata

    class FakeFetcher:
        async def close(self):
            return None

    class FakeSource:
        async def explore_groups(self, ctx):
            return [{"groupId": "rank", "title": "排行榜"}]

        async def explore(self, ctx, group_id, page):
            raise CloudflareRequired("需要验证", url="https://example.com/rank")

        async def search(self, ctx, keyword, page):
            return []

    class FakeScheduler:
        config = {"source_timeout_seconds": 1.0}

        def __init__(self):
            metadata = PluginMetadata.from_dict({
                "contractVersion": "1.0",
                "id": "fixture_cf_live",
                "name": "Fixture CF Live",
                "version": "0.1.0",
                "type": "source",
                "domains": ["example.com"],
                "baseUrls": ["https://example.com"],
                "capabilities": ["search", "detail", "toc", "chapter", "explore"],
                "auth": {"mode": "none", "cookieDomains": []},
                "content": {"access": "free"},
                "browser": {"mode": "required"},
                "tags": [],
            })
            self._plugins = {
                "fixture_cf_live": SimpleNamespace(
                    metadata=metadata,
                    capabilities=["search", "detail", "toc", "chapter", "explore"],
                    source=FakeSource(),
                )
            }

        def _make_ctx(self, plugin_id):
            return SimpleNamespace(_fetcher=FakeFetcher())

    service = LiveAcceptanceService(scheduler=FakeScheduler())
    result = await service.run_plugin_live_check("fixture_cf_live", persist=False)

    assert result["status"] == "failed"
    assert "browserChallenges" not in result
    assert result["diagnostics"][0]["extra"]["bypassRequired"] is True


@pytest.mark.asyncio
async def test_live_acceptance_falls_back_to_search_when_explore_requires_browser():
    from types import SimpleNamespace
    from app.services.live_acceptance import LiveAcceptanceService
    from app.source_plugins.errors import CloudflareRequired
    from app.source_plugins.models import PluginMetadata

    class FakeFetcher:
        async def close(self):
            return None

    class FakeSource:
        async def explore_groups(self, ctx):
            return [{"groupId": "rank", "title": "排行榜"}]

        async def explore(self, ctx, group_id, page):
            raise CloudflareRequired("榜单需要验证", url="https://example.com/rank")

        async def search(self, ctx, keyword, page):
            return [{"sourceId": "fixture_search_fallback", "name": keyword, "bookUrl": "https://example.com/book/1"}]

        async def detail(self, ctx, book_url):
            return {"name": "剑宗外门", "tocUrl": "https://example.com/book/1"}

        async def toc(self, ctx, toc_url):
            return [{"title": "第一章", "chapterUrl": "https://example.com/chapter/1"}]

        async def chapter(self, ctx, chapter_url):
            return {"title": "第一章", "content": "正文" * 300}

    class FakeScheduler:
        config = {"source_timeout_seconds": 1.0}

        def __init__(self):
            metadata = PluginMetadata.from_dict({
                "contractVersion": "1.0",
                "id": "fixture_search_fallback",
                "name": "Fixture Search Fallback",
                "version": "0.1.0",
                "type": "source",
                "domains": ["example.com"],
                "baseUrls": ["https://example.com"],
                "capabilities": ["search", "detail", "toc", "chapter", "explore"],
                "auth": {"mode": "none", "cookieDomains": []},
                "content": {"access": "free"},
                    "browser": {"mode": "required"},
                "accessStrategy": {"search": "search_provider"},
                "tags": [],
            })
            self._plugins = {
                "fixture_search_fallback": SimpleNamespace(
                    metadata=metadata,
                    capabilities=["search", "detail", "toc", "chapter", "explore"],
                    source=FakeSource(),
                )
            }

        def _make_ctx(self, plugin_id):
            return SimpleNamespace(_fetcher=FakeFetcher())

    service = LiveAcceptanceService(scheduler=FakeScheduler())
    result = await service.run_plugin_live_check("fixture_search_fallback", keyword="剑宗外门", persist=False)

    assert result["passed"] is True
    assert result["diagnostics"][0]["stage"] == "explore"
    assert result["search"]["count"] == 1
    assert result["toc"]["count"] == 1
    assert result["chapter"]["contentLength"] > 500


@pytest.mark.asyncio
async def test_live_acceptance_timeout_for_browser_optional_source_marks_bypass_required():
    import asyncio
    from types import SimpleNamespace
    from app.services.live_acceptance import LiveAcceptanceService
    from app.source_plugins.models import PluginMetadata

    class FakeFetcher:
        async def close(self):
            return None

    class SlowSource:
        async def explore_groups(self, ctx):
            await asyncio.sleep(1)
            return []

        async def search(self, ctx, keyword, page):
            return []

    class FakeScheduler:
        config = {"source_timeout_seconds": 0.01}

        def __init__(self):
            metadata = PluginMetadata.from_dict({
                "contractVersion": "1.0",
                "id": "fixture_optional_browser_timeout",
                "name": "Fixture Optional Browser Timeout",
                "version": "0.1.0",
                "type": "source",
                "domains": ["example.com"],
                "baseUrls": ["https://example.com"],
                "capabilities": ["search", "detail", "toc", "chapter", "explore"],
                "auth": {"mode": "none", "cookieDomains": ["example.com"]},
                "content": {"access": "free"},
                    "browser": {"mode": "optional"},
                "tags": [],
            })
            self._plugins = {
                "fixture_optional_browser_timeout": SimpleNamespace(
                    metadata=metadata,
                    capabilities=["search", "detail", "toc", "chapter", "explore"],
                    source=SlowSource(),
                )
            }

        def _make_ctx(self, plugin_id):
            return SimpleNamespace(_fetcher=FakeFetcher())

        def timeout_for_plugin(self, plugin):
            return 0.01

    service = LiveAcceptanceService(scheduler=FakeScheduler())
    result = await service.run_plugin_live_check("fixture_optional_browser_timeout", persist=False)

    assert result["status"] == "timeout"
    assert result["diagnostics"][0]["code"] == "BROWSER_REQUIRED"
    assert result["diagnostics"][0]["extra"]["bypassRequired"] is True
    assert "browserChallenges" not in result


@pytest.mark.asyncio
async def test_verify_candidate_bypasses_stale_chapter_cache(monkeypatch):
    from types import SimpleNamespace
    from app.services.live_acceptance import LiveAcceptanceService
    from app.source_plugins.models import PluginMetadata

    class FakeFetcher:
        async def close(self):
            return None

    class FakeSource:
        async def detail(self, ctx, book_url):
            return {"name": "剑宗外门", "tocUrl": "https://example.com/book/1"}

        async def toc(self, ctx, toc_url):
            return [{"title": "第一章", "chapterUrl": "https://example.com/chapter/1"}]

        async def chapter(self, ctx, chapter_url):
            return {"title": "第一章", "content": "新正文\n\n第二段" * 200}

    class FakeScheduler:
        config = {"source_timeout_seconds": 1.0}

        def __init__(self):
            metadata = PluginMetadata.from_dict({
                "contractVersion": "1.0",
                "id": "fixture_verify_refresh",
                "name": "Fixture Verify Refresh",
                "version": "0.1.0",
                "type": "source",
                "domains": ["example.com"],
                "baseUrls": ["https://example.com"],
                "capabilities": ["search", "detail", "toc", "chapter"],
                "auth": {"mode": "none", "cookieDomains": []},
                "content": {"access": "free"},
                "tags": [],
            })
            self._plugins = {
                "fixture_verify_refresh": SimpleNamespace(
                    metadata=metadata,
                    capabilities=["search", "detail", "toc", "chapter"],
                    source=FakeSource(),
                )
            }

        def _make_ctx(self, plugin_id):
            return SimpleNamespace(_fetcher=FakeFetcher())

    class FakeCache:
        def get_book(self, book_id):
            return {"data": {"name": "剑宗外门", "tocUrl": "https://example.com/book/1"}}

        def get_toc(self, book_id):
            return {"chapters": [{"title": "第一章", "chapterUrl": "https://example.com/chapter/1"}]}

        def get_chapter(self, chapter_id):
            return {"title": "第一章", "content": "旧正文没有空行"}

        def set_chapter(self, *args, **kwargs):
            return None

        def set_book(self, *args, **kwargs):
            return None

        def set_toc(self, *args, **kwargs):
            return None

    class FakeCatalog:
        def __init__(self):
            self.cache = FakeCache()

    monkeypatch.setattr("app.services.catalog.Catalog", FakeCatalog)

    service = LiveAcceptanceService(scheduler=FakeScheduler())
    result = await service.verify_candidate(
        {"sourceId": "fixture_verify_refresh", "name": "剑宗外门", "bookUrl": "https://example.com/book/1"},
        keyword="剑宗外门",
        chapter_index=0,
    )

    assert "新正文" in result["chapter"]["content"]
    assert "\n\n" in result["chapter"]["content"]
    assert any(item["code"] == "chapter_cache_bypassed" for item in result["diagnostics"])


@pytest.mark.asyncio
async def test_verify_candidate_transmits_chapter_reviews():
    from types import SimpleNamespace
    from app.services.live_acceptance import LiveAcceptanceService
    from app.source_plugins.models import PluginMetadata

    class FakeFetcher:
        async def close(self):
            return None

    class FakeSource:
        async def detail(self, ctx, book_url):
            return {"name": "凡人修仙传", "tocUrl": "https://example.com/book/1"}

        async def toc(self, ctx, toc_url):
            return [{"title": "第一章", "chapterUrl": "https://example.com/chapter/1"}]

        async def chapter(self, ctx, chapter_url):
            return {"title": "第一章", "content": "正文" * 300, "chapterUrl": chapter_url}

        async def chapter_reviews(self, ctx, chapter_url):
            return {
                "paragraphs": {
                    "0": [{"id": "r1", "content": "段评1", "userName": "读者甲", "likeNum": 3, "replyCount": 0, "reviewTime": "2026-06-11"}]
                },
                "chapterEnd": [{"id": "r2", "content": "章末评", "userName": "读者乙", "likeNum": 5, "replyCount": 1, "reviewTime": "2026-06-11"}],
                "summary": {"totalReviews": 2, "totalParagraphs": 1, "chapterEndCount": 1, "authMode": "public"},
                "debug": {"fetched": True},
            }

    class FakeScheduler:
        config = {"source_timeout_seconds": 1.0}

        def __init__(self):
            metadata = PluginMetadata.from_dict({
                "contractVersion": "1.0",
                "id": "fixture_reviews",
                "name": "Fixture Reviews",
                "version": "0.1.0",
                "type": "source",
                "domains": ["example.com"],
                "baseUrls": ["https://example.com"],
                "capabilities": ["search", "detail", "toc", "chapter", "chapter_reviews"],
                "auth": {"mode": "none", "cookieDomains": []},
                "content": {"access": "free"},
                "tags": [],
            })
            self._plugins = {
                "fixture_reviews": SimpleNamespace(
                    metadata=metadata,
                    capabilities=["search", "detail", "toc", "chapter", "chapter_reviews"],
                    source=FakeSource(),
                )
            }

        def _make_ctx(self, plugin_id):
            return SimpleNamespace(_fetcher=FakeFetcher())

    service = LiveAcceptanceService(scheduler=FakeScheduler())
    result = await service.verify_candidate(
        {"sourceId": "fixture_reviews", "name": "凡人修仙传", "bookUrl": "https://example.com/book/1"},
        keyword="凡人修仙传",
        chapter_index=0,
    )

    assert result["status"] == "passed"
    assert result["chapter"]["contentLength"] > 500
    reviews = result["reviews"]
    assert reviews["paragraphs"]["0"][0]["content"] == "段评1"
    assert reviews["chapterEnd"][0]["content"] == "章末评"
    assert reviews["summary"]["totalReviews"] == 2
    assert reviews["summary"]["authMode"] == "public"
    assert reviews["debug"]["fetched"] is True
    assert reviews["passed"] is True


def test_qidian_com_plugin_has_chapter_reviews_capability():
    from app.source_plugins.loader import PluginLoader

    loader = PluginLoader()
    plugins = loader.load_all()
    qidian = plugins.get("qidian_com")
    assert qidian is not None, "qidian_com plugin should be loadable"
    assert "chapter_reviews" in qidian.capabilities, "qidian_com should advertise chapter_reviews capability"
    assert qidian.metadata.is_official_source() is True
    assert qidian.metadata.enabled is True, "qidian_com should be enabled by default for search jobs"
