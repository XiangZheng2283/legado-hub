"""Tests for aggregate source compatibility with plugin runtime."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_aggregate_source_endpoint():
    res = client.get("/api/legado/source")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)
    assert len(data) == 1
    source = data[0]
    assert "ruleSearch" in source
    assert "exploreUrl" in source
    assert "ruleExplore" in source
    assert "ruleBookInfo" in source
    assert "ruleToc" in source
    assert "ruleContent" in source


def test_search_via_api():
    res = client.get("/api/legado/search?keyword=test")
    assert res.status_code == 200
    data = res.json()
    assert data["implemented"] is True
    assert "items" in data
    assert "debug" in data


def test_legado_search_returns_progressive_job_snapshot(monkeypatch):
    class FakeJob:
        job_id = "job-1"
        keyword = "剑宗外门"
        page = 1
        status = "running"
        candidate_groups = [
            {
                "candidateId": "book-1",
                "name": "剑宗外门",
                "author": "作者甲",
                "items": [{"name": "剑宗外门", "author": "作者甲", "sourceId": "fixture"}],
            }
        ]
        browser_challenges = []
        sources = [{"sourceId": "fixture"}]
        events = []

    class FakeSearchService:
        def find_active_job(self, keyword, page):
            return FakeJob()

        def snapshot(self, job):
            return {
                "implemented": True,
                "keyword": job.keyword,
                "page": job.page,
                "jobId": job.job_id,
                "status": job.status,
                "items": job.candidate_groups[0]["items"],
                "candidateGroups": job.candidate_groups,
                "debug": {"partial": True, "sourceCount": 1},
            }

    import app.api.legado as legado_api

    monkeypatch.setattr(legado_api, "_search_service", FakeSearchService())

    res = client.get("/api/legado/search?keyword=剑宗外门&page=1&waitMs=1")

    assert res.status_code == 200
    data = res.json()
    assert data["jobId"] == "job-1"
    assert data["debug"]["partial"] is True
    assert data["items"][0]["name"] == "剑宗外门"


def test_explore_via_api():
    res = client.get("/api/legado/explore?page=1")
    assert res.status_code == 200
    data = res.json()
    assert data["implemented"] is True
    assert "items" in data
    assert "debug" in data


def test_legado_explore_preserves_browser_challenge(monkeypatch):
    challenge = {
        "sessionId": "session-1",
        "sourceId": "fixture_cf",
        "sourceName": "Fixture CF",
        "reason": "BROWSER_REQUIRED",
        "stage": "explore",
        "openUrl": "https://example.com/rank",
        "actions": {"submitCookies": "/api/console/browser-challenges/session-1/cookies"},
    }

    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            pass

        async def explore_groups(self, source_id=None):
            return {
                "implemented": True,
                "groups": [{"sourceId": "fixture_cf", "groupId": "rank", "title": "排行榜"}],
                "debug": {},
            }

        async def explore(self, source_id, group_id=None, page=1):
            err = {
                "sourceId": source_id,
                "stage": "explore",
                "code": "BROWSER_REQUIRED",
                "message": "browser verification required",
                "extra": {"browserChallenge": challenge},
            }
            return {
                "implemented": True,
                "sourceId": source_id,
                "groupId": group_id or "",
                "page": page,
                "items": [],
                "debug": {"error": err, "errors": [err], "browserChallenges": [challenge]},
            }

    monkeypatch.setattr("app.services.catalog.PluginScheduler", FakeScheduler)

    res = client.get("/api/legado/explore?sourceId=fixture_cf&page=1")

    assert res.status_code == 200
    data = res.json()
    assert data["debug"]["error"]["code"] == "BROWSER_REQUIRED"
    assert data["debug"]["browserChallenges"][0]["openUrl"] == "https://example.com/rank"


def test_legado_detail_preserves_browser_challenge(monkeypatch):
    from app.source_plugins.id_codec import encode_book_id

    challenge = {
        "sessionId": "session-detail",
        "sourceId": "fixture_cf_detail",
        "sourceName": "Fixture CF Detail",
        "reason": "BROWSER_REQUIRED",
        "stage": "detail",
        "openUrl": "https://example.com/book/1",
        "actions": {"submitCookies": "/api/console/browser-challenges/session-detail/cookies"},
    }

    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            pass

        async def detail(self, source_id, book_url):
            err = {
                "sourceId": source_id,
                "stage": "detail",
                "code": "BROWSER_REQUIRED",
                "message": "browser verification required",
                "extra": {"browserChallenge": challenge},
            }
            return {"implemented": True, "data": None, "debug": {"error": err, "browserChallenges": [challenge]}}

    monkeypatch.setattr("app.services.catalog.PluginScheduler", FakeScheduler)

    book_id = encode_book_id("fixture_cf_detail", "https://example.com/book/1")
    res = client.get(f"/api/legado/book/{book_id}")

    assert res.status_code == 200
    data = res.json()
    assert data["data"] is None
    assert data["debug"]["error"]["code"] == "BROWSER_REQUIRED"
    assert data["debug"]["browserChallenges"][0]["stage"] == "detail"
    assert data["debug"]["browserChallenges"][0]["openUrl"] == "https://example.com/book/1"


def test_legado_toc_preserves_browser_challenge(monkeypatch):
    from app.source_plugins.id_codec import encode_book_id

    challenge = {
        "sessionId": "session-toc",
        "sourceId": "fixture_cf_toc",
        "sourceName": "Fixture CF Toc",
        "reason": "BROWSER_REQUIRED",
        "stage": "toc",
        "openUrl": "https://example.com/book/2",
        "actions": {"submitCookies": "/api/console/browser-challenges/session-toc/cookies"},
    }

    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            pass

        async def toc(self, source_id, toc_url):
            err = {
                "sourceId": source_id,
                "stage": "toc",
                "code": "BROWSER_REQUIRED",
                "message": "browser verification required",
                "extra": {"browserChallenge": challenge},
            }
            return {
                "implemented": True,
                "bookId": "",
                "chapters": [],
                "debug": {"error": err, "browserChallenges": [challenge]},
            }

    monkeypatch.setattr("app.services.catalog.PluginScheduler", FakeScheduler)

    book_id = encode_book_id("fixture_cf_toc", "https://example.com/book/2")
    res = client.get(f"/api/legado/book/{book_id}/toc")

    assert res.status_code == 200
    data = res.json()
    assert data["chapters"] == []
    assert data["debug"]["error"]["code"] == "BROWSER_REQUIRED"
    assert data["debug"]["browserChallenges"][0]["stage"] == "toc"
    assert data["debug"]["browserChallenges"][0]["openUrl"] == "https://example.com/book/2"


def test_legado_chapter_preserves_browser_challenge(monkeypatch):
    from app.source_plugins.id_codec import encode_chapter_id

    challenge = {
        "sessionId": "session-chapter",
        "sourceId": "fixture_cf_chapter",
        "sourceName": "Fixture CF Chapter",
        "reason": "BROWSER_REQUIRED",
        "stage": "chapter",
        "openUrl": "https://example.com/chapter/1",
        "actions": {"submitCookies": "/api/console/browser-challenges/session-chapter/cookies"},
    }

    class FakeScheduler:
        def __init__(self, *args, **kwargs):
            pass

        async def chapter(self, source_id, chapter_url):
            err = {
                "sourceId": source_id,
                "stage": "chapter",
                "code": "BROWSER_REQUIRED",
                "message": "browser verification required",
                "extra": {"browserChallenge": challenge},
            }
            return {
                "implemented": True,
                "chapterId": "",
                "title": "",
                "content": "",
                "debug": {"error": err, "browserChallenges": [challenge]},
            }

    monkeypatch.setattr("app.services.catalog.PluginScheduler", FakeScheduler)

    chapter_id = encode_chapter_id("fixture_cf_chapter", "https://example.com/chapter/1")
    res = client.get(f"/api/legado/chapter/{chapter_id}")

    assert res.status_code == 200
    data = res.json()
    assert data["content"] == ""
    assert data["debug"]["error"]["code"] == "BROWSER_REQUIRED"
    assert data["debug"]["browserChallenges"][0]["stage"] == "chapter"
    assert data["debug"]["browserChallenges"][0]["openUrl"] == "https://example.com/chapter/1"


def test_legado_browser_challenge_cookie_api(monkeypatch, tmp_path):
    import app.api.legado as legado_api
    from app.services.browser_challenge import BrowserChallengeService
    from app.services.plugin_auth_repository import PluginAuthRepository
    from app.source_plugins.scheduler import PluginScheduler

    service = BrowserChallengeService(auth_repository=PluginAuthRepository(tmp_path / "auth.db"))
    monkeypatch.setattr(legado_api, "_browser_challenge_service", service)
    plugin = PluginScheduler()._plugins["69shuba_com"]
    challenge = service.create_for_plugin(plugin, stage="search", url="https://www.69shuba.com/newhot_0_1_1.htm")

    listed = client.get("/api/legado/browser-challenges?sourceId=69shuba_com")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["sessionId"] == challenge["sessionId"]

    saved = client.post(
        f"/api/legado/browser-challenges/{challenge['sessionId']}/cookies",
        json={"cookies": [{"domain": ".69shuba.com", "name": "cf_clearance", "value": "ok"}]},
    )

    assert saved.status_code == 200
    data = saved.json()
    assert data["saved"] is True
    assert data["clearanceDomains"] == ["69shuba.com"]
    assert "www.69shuba.com" not in data["missingClearanceDomains"]

    challenge_text = service.create_for_plugin(plugin, stage="search", url="https://www.69shuba.com/newhot_0_1_1.htm")
    saved_text = client.post(
        f"/api/legado/browser-challenges/{challenge_text['sessionId']}/cookies",
        json={"cookies": "cf_clearance=text-ok; sid=1"},
    )

    assert saved_text.status_code == 200
    assert saved_text.json()["saved"] is True
    assert saved_text.json()["clearanceDomains"] == ["69shuba.com"]


def test_legado_browser_challenge_retry_live_check(monkeypatch, tmp_path):
    import app.api.legado as legado_api
    from app.services.browser_challenge import BrowserChallengeService
    from app.services.plugin_auth_repository import PluginAuthRepository
    from app.source_plugins.scheduler import PluginScheduler

    service = BrowserChallengeService(auth_repository=PluginAuthRepository(tmp_path / "auth.db"))
    monkeypatch.setattr(legado_api, "_browser_challenge_service", service)
    plugin = PluginScheduler()._plugins["69shuba_com"]
    challenge = service.create_for_plugin(plugin, stage="search", url="https://www.69shuba.com/newhot_0_1_1.htm")

    class FakeLiveAcceptance:
        async def run_plugin_live_check(self, **kwargs):
            return {
                "pluginId": kwargs["plugin_id"],
                "status": "failed",
                "passed": False,
                "browserChallenges": [],
                "diagnostics": [{"stage": "runtime", "code": "BROWSER_REQUIRED", "message": "browser verification required"}],
            }

    monkeypatch.setattr(legado_api, "_live_acceptance_service", FakeLiveAcceptance())

    retried = client.post(
        f"/api/legado/browser-challenges/{challenge['sessionId']}/retry-live-check",
        json={"keyword": "剑宗外门"},
    )

    assert retried.status_code == 200
    data = retried.json()
    assert data["status"] == "retry_failed"
    assert data["retryResult"]["pluginId"] == "69shuba_com"


def test_legado_browser_challenge_browser_helper_flow(monkeypatch, tmp_path):
    import app.api.legado as legado_api
    from app.services.browser_challenge import BrowserChallengeService
    from app.services.plugin_auth_repository import PluginAuthRepository
    from app.source_plugins.scheduler import PluginScheduler

    service = BrowserChallengeService(auth_repository=PluginAuthRepository(tmp_path / "auth.db"))
    monkeypatch.setattr(legado_api, "_browser_challenge_service", service)
    plugin = PluginScheduler()._plugins["69shuba_com"]
    challenge = service.create_for_plugin(plugin, stage="search", url="https://www.69shuba.com/newhot_0_1_1.htm")

    class FakeBrowserHelper:
        def start(self, session):
            return {"started": True, "sessionId": session["sessionId"], "pid": 123, "openUrl": session["openUrl"]}

        def status(self, session_id):
            return {"sessionId": session_id, "exists": True, "cookieCount": 1}

        def cookies(self, session_id):
            return [{"domain": ".69shuba.com", "name": "cf_clearance", "value": "ok"}]

    monkeypatch.setattr(legado_api, "_browser_helper_service", FakeBrowserHelper())

    opened = client.post(f"/api/legado/browser-challenges/{challenge['sessionId']}/browser/open")
    assert opened.status_code == 200
    assert opened.json()["started"] is True

    status = client.get(f"/api/legado/browser-challenges/{challenge['sessionId']}/browser/status")
    assert status.status_code == 200
    assert status.json()["cookieCount"] == 1

    imported = client.post(f"/api/legado/browser-challenges/{challenge['sessionId']}/browser/import-cookies")
    assert imported.status_code == 200
    assert imported.json()["saved"] is True
    assert imported.json()["clearanceDomains"] == ["69shuba.com"]


def test_aggregate_source_generation():
    from app.core.source_generator import write_aggregate_source
    path = write_aggregate_source()
    assert path
    import json, pathlib
    p = pathlib.Path(path)
    assert p.exists()
    content = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(content, list)
    assert len(content) == 1
    assert content[0]["enabledExplore"] is True
    assert "ruleExplore" in content[0]
    assert "waitMs=1200" in content[0]["searchUrl"]
