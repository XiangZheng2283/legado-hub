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
async def test_live_acceptance_result_includes_browser_challenge():
    from types import SimpleNamespace
    from app.services.live_acceptance import LiveAcceptanceService
    from app.source_plugins.errors import CloudflareRequired

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
            metadata = SimpleNamespace(
                id="fixture_cf_live",
                name="Fixture CF Live",
                enabled=True,
                auth={"mode": "none", "cookieDomains": []},
                domains=["example.com"],
                base_urls=["https://example.com"],
                browser={"mode": "required"},
                domain_profiles=[],
            )
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
    assert result["browserChallenges"][0]["sourceId"] == "fixture_cf_live"
    assert result["browserChallenges"][0]["openUrl"] == "https://example.com/rank"
    assert result["diagnostics"][0]["extra"]["browserChallenge"]["reason"] == "CLOUDFLARE_REQUIRED"


@pytest.mark.asyncio
async def test_live_acceptance_falls_back_to_search_when_explore_requires_browser():
    from types import SimpleNamespace
    from app.services.live_acceptance import LiveAcceptanceService
    from app.source_plugins.errors import CloudflareRequired

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
            metadata = SimpleNamespace(
                id="fixture_search_fallback",
                name="Fixture Search Fallback",
                enabled=True,
                auth={"mode": "none", "cookieDomains": []},
                domains=["example.com"],
                base_urls=["https://example.com"],
                browser={"mode": "required", "searchFallback": "search_engine", "verificationUrl": "https://example.com/rank"},
                domain_profiles=[],
            )
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
async def test_live_acceptance_timeout_for_browser_optional_source_includes_challenge():
    import asyncio
    from types import SimpleNamespace
    from app.services.live_acceptance import LiveAcceptanceService

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
            metadata = SimpleNamespace(
                id="fixture_optional_browser_timeout",
                name="Fixture Optional Browser Timeout",
                enabled=True,
                auth={"mode": "none", "cookieDomains": ["example.com"]},
                domains=["example.com"],
                base_urls=["https://example.com"],
                browser={"mode": "optional", "verificationUrl": "https://example.com/rank"},
                domain_profiles=[],
            )
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
    assert result["browserChallenges"][0]["openUrl"] == "https://example.com/rank"
