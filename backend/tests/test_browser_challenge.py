"""Tests for manual browser challenge sessions."""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.services.browser_challenge import BrowserChallengeService
from app.services.plugin_auth_repository import PluginAuthRepository
from app.source_plugins.loader import PluginLoader
from app.source_plugins.scheduler import PluginScheduler
from app.source_plugins.models import PluginMetadata, LoadedPlugin


def test_browser_challenge_cookie_submission_roundtrip(tmp_path):
    repo = PluginAuthRepository(tmp_path / "auth.db")
    service = BrowserChallengeService(auth_repository=repo)

    cookies = service.normalize_cookies([
        {"domain": ".69shuba.com", "name": "cf_clearance", "value": "ok"},
        {"domain": "www.69shuba.com", "name": "session", "value": "abc"},
    ])

    assert cookies == {
        "69shuba.com": {"cf_clearance": "ok"},
        "www.69shuba.com": {"session": "abc"},
    }


def _write_cf_plugin(tmp_path: Path) -> str:
    plugin_id = "fixture_cf"
    plugin_dir = tmp_path / plugin_id
    plugin_dir.mkdir(parents=True)
    metadata = {
        "contractVersion": "1.0",
        "id": plugin_id,
        "name": "Fixture CF",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search", "detail", "toc", "chapter", "explore"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "proxy": {"mode": "always"},
        "browser": {"mode": "required", "reason": "cloudflare_verification"},
        "tags": ["cloudflare"],
    }
    (plugin_dir / "metadata.yaml").write_text(yaml.safe_dump(metadata, allow_unicode=True), encoding="utf-8")
    (plugin_dir / "source.py").write_text(
        '''
from app.source_plugins.errors import CloudflareRequired

class Source:
    id = "fixture_cf"
    name = "Fixture CF"
    contract_version = "1.0"

    async def search(self, ctx, keyword: str, page: int):
        raise CloudflareRequired("需要 Cloudflare 验证", url="https://example.com/search")

    async def detail(self, ctx, book_url: str):
        raise CloudflareRequired("需要 Cloudflare 验证", url=book_url)

    async def toc(self, ctx, toc_url: str):
        return []

    async def chapter(self, ctx, chapter_url: str):
        return {"title": "", "content": ""}

    async def explore_groups(self, ctx):
        return [{"groupId": "rank", "title": "排行榜", "url": "https://example.com/rank", "kind": "rank"}]

    async def explore(self, ctx, group_id=None, page: int = 1):
        raise CloudflareRequired("需要 Cloudflare 验证", url="https://example.com/rank")
''',
        encoding="utf-8",
    )
    return plugin_id


@pytest.mark.asyncio
async def test_scheduler_returns_browser_challenge_for_cloudflare(tmp_path):
    plugin_id = _write_cf_plugin(tmp_path)
    scheduler = PluginScheduler(loader=PluginLoader(plugins_dir=tmp_path), config={})

    result = await scheduler.search("凡人修仙传", 1)

    assert result["debug"]["errors"][0]["code"] == "CLOUDFLARE_REQUIRED"
    challenge = result["debug"]["browserChallenges"][0]
    assert challenge["sourceId"] == plugin_id
    assert challenge["openUrl"] == "https://example.com/search"
    assert challenge["actions"]["submitCookies"].startswith("/api/console/browser-challenges/")
    assert challenge["actions"]["legadoSubmitCookies"].startswith("/api/legado/browser-challenges/")


def test_console_browser_challenge_cookie_api(monkeypatch, tmp_path):
    import app.api.console as console_api

    repo = PluginAuthRepository(tmp_path / "auth_console.db")
    monkeypatch.setattr(console_api, "_browser_challenge_service", BrowserChallengeService(auth_repository=repo))
    client = TestClient(app)

    created = client.post("/api/console/plugins/69shuba_com/browser-challenge", json={"stage": "search"})
    assert created.status_code == 200
    session = created.json()
    assert session["sourceId"] == "69shuba_com"

    saved = client.post(
        f"/api/console/browser-challenges/{session['sessionId']}/cookies",
        json={"cookies": [{"domain": ".69shuba.com", "name": "cf_clearance", "value": "ok"}]},
    )

    assert saved.status_code == 200
    assert saved.json()["saved"] is True
    assert "69shuba.com" in saved.json()["cookieDomains"]
    assert saved.json()["clearanceDomains"] == ["69shuba.com"]
    assert "www.69shuba.com" not in saved.json()["missingClearanceDomains"]
    assert "69shuba.cx" in saved.json()["missingClearanceDomains"]

    created_text = client.post("/api/console/plugins/69shuba_com/browser-challenge", json={"stage": "search"})
    text_session = created_text.json()
    saved_text = client.post(
        f"/api/console/browser-challenges/{text_session['sessionId']}/cookies",
        json={"cookies": "cf_clearance=text-ok; sid=1"},
    )

    assert saved_text.status_code == 200
    assert saved_text.json()["saved"] is True
    assert saved_text.json()["clearanceDomains"] == ["69shuba.com"]

    created_header = client.post("/api/console/plugins/69shuba_com/browser-challenge", json={"stage": "search"})
    header_session = created_header.json()
    saved_header = client.post(
        f"/api/console/browser-challenges/{header_session['sessionId']}/cookies",
        json={"cookies": "Cookie: cf_clearance=header-ok; sid=2"},
    )

    assert saved_header.status_code == 200
    assert saved_header.json()["saved"] is True
    assert saved_header.json()["clearanceDomains"] == ["69shuba.com"]

    created_set_cookie = client.post("/api/console/plugins/69shuba_com/browser-challenge", json={"stage": "search"})
    set_cookie_session = created_set_cookie.json()
    saved_set_cookie = client.post(
        f"/api/console/browser-challenges/{set_cookie_session['sessionId']}/cookies",
        json={
            "cookies": (
                "Set-Cookie: cf_clearance=set-cookie-ok; Path=/; Domain=.69shuba.com; Secure\n"
                "Set-Cookie: sid=3; Path=/; Domain=.69shuba.com"
            )
        },
    )

    assert saved_set_cookie.status_code == 200
    assert saved_set_cookie.json()["saved"] is True
    assert saved_set_cookie.json()["clearanceDomains"] == ["69shuba.com"]


def test_twkan_browser_challenge_uses_rank_verification_url_and_cookie_domain():
    plugin = PluginScheduler()._plugins["twkan_com"]
    service = BrowserChallengeService()

    challenge = service.create_for_plugin(plugin, stage="explore", reason="CLOUDFLARE_REQUIRED")

    assert challenge["sourceId"] == "twkan_com"
    assert challenge["openUrl"] == "https://twkan.com/novels/hot"
    assert challenge["cookieDomains"] == ["twkan.com"]


def test_console_browser_challenge_retry_live_check(monkeypatch, tmp_path):
    import app.api.console as console_api

    repo = PluginAuthRepository(tmp_path / "auth_retry.db")
    monkeypatch.setattr(console_api, "_browser_challenge_service", BrowserChallengeService(auth_repository=repo))
    client = TestClient(app)

    created = client.post("/api/console/plugins/69shuba_com/browser-challenge", json={"stage": "explore"})
    assert created.status_code == 200
    session = created.json()

    class FakeLiveAcceptance:
        async def run_plugin_live_check(self, **kwargs):
            return {
                "pluginId": kwargs["plugin_id"],
                "status": "passed",
                "passed": True,
                "explore": {"contentLength": 1200},
                "search": {"count": 1},
                "toc": {"count": 10},
                "chapter": {"contentLength": 1200},
                "diagnostics": [],
            }

    monkeypatch.setattr(console_api, "_live_acceptance_service", FakeLiveAcceptance())
    retried = client.post(f"/api/console/browser-challenges/{session['sessionId']}/retry-live-check")

    assert retried.status_code == 200
    data = retried.json()
    assert data["status"] == "retry_passed"
    assert data["retryResult"]["passed"] is True


def test_console_browser_helper_imports_cookies(monkeypatch, tmp_path):
    import app.api.console as console_api

    repo = PluginAuthRepository(tmp_path / "auth_helper.db")
    monkeypatch.setattr(console_api, "_browser_challenge_service", BrowserChallengeService(auth_repository=repo))
    client = TestClient(app)
    created = client.post("/api/console/plugins/69shuba_com/browser-challenge", json={"stage": "explore"})
    session = created.json()

    class FakeBrowserHelper:
        def start(self, session_data):
            return {
                "started": True,
                "sessionId": session_data["sessionId"],
                "pid": 123,
                "openUrl": session_data["openUrl"],
                "message": "started",
            }

        def status(self, session_id):
            return {"sessionId": session_id, "exists": True, "cookieCount": 1}

        def cookies(self, session_id):
            return [{"domain": ".69shuba.com", "name": "cf_clearance", "value": "ok"}]

    monkeypatch.setattr(console_api, "_browser_helper_service", FakeBrowserHelper())

    opened = client.post(f"/api/console/browser-challenges/{session['sessionId']}/browser/open")
    assert opened.status_code == 200
    assert opened.json()["started"] is True

    imported = client.post(f"/api/console/browser-challenges/{session['sessionId']}/browser/import-cookies")
    assert imported.status_code == 200
    assert imported.json()["saved"] is True
    assert "69shuba.com" in imported.json()["cookieDomains"]
    assert imported.json()["clearanceDomains"] == ["69shuba.com"]


def test_browser_helper_uses_source_pool_proxy(tmp_path, monkeypatch):
    from app.services.browser_helper import BrowserHelperService

    root = tmp_path
    backend = root / "backend"
    frontend = root / "frontend"
    (backend / "scripts").mkdir(parents=True)
    (backend / "config").mkdir(parents=True)
    (frontend / "node_modules" / "playwright").mkdir(parents=True)
    script = backend / "scripts" / "browser_challenge_helper.mjs"
    script.write_text("", encoding="utf-8")
    (backend / "config" / "source_pool.json").write_text(
        '{"proxy": {"enabled": true, "url": "http://127.0.0.1:7890"}}',
        encoding="utf-8",
    )
    captured = {}

    class FakeProcess:
        pid = 456

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return FakeProcess()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    service = BrowserHelperService(root_dir=root)
    result = service.start({"sessionId": "s1", "openUrl": "https://example.com"})

    assert result["started"] is True
    assert result["proxyUsed"] is True
    assert "--proxy" in captured["cmd"]
    assert "http://127.0.0.1:7890" in captured["cmd"]


def test_browser_fetch_service_builds_playwright_cookies():
    from app.services.browser_fetch import BrowserFetchService

    service = BrowserFetchService(cookies={"69shuba.com": {"cf_clearance": "ok"}})

    assert service._playwright_cookies() == [
        {"name": "cf_clearance", "value": "ok", "domain": "69shuba.com", "path": "/"}
    ]


def test_browser_fetch_service_merges_returned_cookies_for_next_fetch():
    from app.services.browser_fetch import BrowserFetchService

    service = BrowserFetchService()

    service._merge_browser_cookies([{"domain": ".69shuba.com", "name": "cf_clearance", "value": "ok"}])

    assert service.cookies == {"69shuba.com": {"cf_clearance": "ok"}}
    assert service._playwright_cookies() == [
        {"name": "cf_clearance", "value": "ok", "domain": "69shuba.com", "path": "/"}
    ]


def test_scheduler_injects_auth_cookies_into_browser_fetch(monkeypatch):
    class FakeAuthRepository:
        def get_cookies(self, plugin_id):
            return {"69shuba.com": {"cf_clearance": "ok"}}

    monkeypatch.setattr("app.services.plugin_auth_repository.PluginAuthRepository", FakeAuthRepository)
    scheduler = PluginScheduler(loader=PluginLoader(plugins_dir=Path("/nonexistent")), config={})

    ctx = scheduler._make_ctx("missing_plugin")

    assert ctx._browser_fetcher.cookies == {"69shuba.com": {"cf_clearance": "ok"}}


def test_scheduler_uses_browser_timeout_for_browser_required_or_optional_plugin():
    metadata = PluginMetadata.from_dict({
        "contractVersion": "1.0",
        "id": "browser_source",
        "name": "Browser Source",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "browser": {"mode": "required"},
        "tags": [],
    })
    optional_metadata = PluginMetadata.from_dict({
        "contractVersion": "1.0",
        "id": "optional_browser_source",
        "name": "Optional Browser Source",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "browser": {"mode": "optional"},
        "tags": [],
    })
    scheduler = PluginScheduler(loader=PluginLoader(plugins_dir=Path("/nonexistent")), config={
        "source_timeout_seconds": 8,
        "browser_source_timeout_seconds": 90,
        "browser_search_timeout_seconds": 30,
    })
    plugin = LoadedPlugin(metadata=metadata, module=None, source=None, capabilities=["search"])
    optional_plugin = LoadedPlugin(metadata=optional_metadata, module=None, source=None, capabilities=["search"])

    assert scheduler.timeout_for_plugin(plugin) == 90
    assert scheduler.search_timeout_for_plugin(plugin) == 30
    assert scheduler.timeout_for_plugin(optional_plugin) == 90
    assert scheduler.search_timeout_for_plugin(optional_plugin) == 30
    assert scheduler.timeout_for_plugin(None) == 8
    assert scheduler.search_timeout_for_plugin(None) == 8
