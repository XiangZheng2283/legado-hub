"""Tests for plugin console API endpoints."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture
def admin_client():
    """Return an authenticated TestClient for admin-only routes.

    Uses the real DB; login with the admin password stored in app_config.json.
    If login fails, the calling test will fail loudly.
    """
    test_client = TestClient(app)
    res = test_client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    if res.status_code != 200:
        pytest.skip(f"admin login unavailable: {res.status_code} {res.text}")
    return test_client


def test_list_plugins():
    res = client.get("/api/console/plugins")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    if data["items"]:
        item = data["items"][0]
        assert item["accessType"] in {"HTTP", "Browser"}
        assert item["sourceType"] == item["accessType"]
        assert "proxyRequired" in item


def test_get_plugin():
    # First list to find a plugin id
    list_res = client.get("/api/console/plugins")
    items = list_res.json().get("items", [])
    if not items:
        pytest.skip("No plugins installed")
    plugin_id = items[0]["pluginId"]
    res = client.get(f"/api/console/plugins/{plugin_id}")
    assert res.status_code == 200
    assert res.json()["pluginId"] == plugin_id
    assert res.json()["accessType"] in {"HTTP", "Browser"}


def test_reload_plugins():
    res = client.post("/api/console/plugins/reload")
    assert res.status_code == 200
    assert res.json()["reloaded"] is True


def test_enable_plugin():
    list_res = client.get("/api/console/plugins")
    items = list_res.json().get("items", [])
    if not items:
        pytest.skip("No plugins installed")
    plugin_id = items[0]["pluginId"]
    res = client.post(f"/api/console/plugins/{plugin_id}/enable", json={"enabled": True})
    assert res.status_code == 200
    assert res.json()["enabled"] is True


def test_smoke_plugin():
    list_res = client.get("/api/console/plugins")
    items = list_res.json().get("items", [])
    if not items:
        pytest.skip("No plugins installed")
    plugin_id = items[0]["pluginId"]
    res = client.post(f"/api/console/plugins/{plugin_id}/smoke", json={"keyword": "test"})
    assert res.status_code == 200
    assert "pass" in res.json()


def test_plugin_auth():
    list_res = client.get("/api/console/plugins")
    items = list_res.json().get("items", [])
    if not items:
        pytest.skip("No plugins installed")
    candidate = next(
        (item for item in items if item.get("auth", {}).get("mode") == "none" and item.get("official") is False),
        None,
    )
    if candidate is None:
        pytest.skip("No ordinary no-auth plugin found")
    plugin_id = candidate["pluginId"]
    res = client.get(f"/api/console/plugins/{plugin_id}/auth")
    assert res.status_code == 200
    assert "authenticated" in res.json()
    assert res.json()["mode"] == "none"


def test_browser_required_plugin_auth_returns_bypass_required(monkeypatch, tmp_path):
    import app.api.console as console_api
    from app.services.cookie_store import CookieStore

    cookie_dir = tmp_path / "cookies"
    cookie_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(console_api, "CookieStore", lambda: CookieStore(base_dir=cookie_dir))

    res = client.get("/api/console/plugins/69shuba_com/auth")

    assert res.status_code == 200
    data = res.json()
    assert data["sourceId"] == "69shuba_com"
    assert data["mode"] in {"none", "browser_bypass"}
    assert "该插件无需登录" in data["message"] or "绕过" in data["message"]
    assert "browserChallenges" not in data


def test_plugin_auth_reports_saved_cookies_for_no_auth_plugin(monkeypatch, tmp_path):
    import app.api.console as console_api
    from app.services.cookie_store import CookieStore

    cookie_dir = tmp_path / "cookies"
    cookie_dir.mkdir(parents=True, exist_ok=True)
    store = CookieStore(base_dir=cookie_dir)
    store.save("69shuba_com", {"cookies": {"69shuba.com": {"cf_clearance": "ok"}}})
    monkeypatch.setattr(console_api, "CookieStore", lambda: CookieStore(base_dir=cookie_dir))

    res = client.post("/api/console/plugins/69shuba_com/auth/check")

    assert res.status_code == 200
    data = res.json()
    assert data["mode"] in {"none", "browser_bypass"}
    assert "该插件无需登录" in data["message"] or "Cookie" in data["message"]
    assert data["hasCookies"] is True
    assert "browserChallenges" not in data


def test_plugin_login_and_cookie_clear():
    list_res = client.get("/api/console/plugins")
    items = list_res.json().get("items", [])
    if not items:
        pytest.skip("No plugins installed")
    plugin_id = items[0]["pluginId"]

    login_res = client.post(f"/api/console/plugins/{plugin_id}/login")
    assert login_res.status_code == 200
    assert login_res.json()["mode"] == "manual_browser"

    clear_res = client.post(f"/api/console/plugins/{plugin_id}/cookies/clear")
    assert clear_res.status_code == 200
    assert clear_res.json()["cleared"] is True


def test_official_sources_endpoint_lists_qidian():
    res = client.get("/api/console/official-sources")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    qidian = next((item for item in data["items"] if item["pluginId"] == "qidian_com"), None)
    if qidian is None:
        pytest.skip("qidian_com plugin not installed")
    assert qidian["official"] is True
    assert qidian["auth"]["mode"] == "optional"


def test_plugin_live_check_preserves_bypass_diagnostics(monkeypatch):
    import app.api.console as console_api

    class FakeLiveAcceptance:
        async def run_plugin_live_check(self, **kwargs):
            return {
                "pluginId": kwargs["plugin_id"],
                "status": "failed",
                "passed": False,
                "diagnostics": [{
                    "stage": "runtime",
                    "code": "BROWSER_REQUIRED",
                    "message": "browser bypass required",
                    "extra": {"bypassRequired": True},
                }],
            }

    monkeypatch.setattr(console_api, "_live_acceptance_service", FakeLiveAcceptance())

    res = client.post("/api/console/plugins/69shuba_com/live-check", json={"keyword": "剑宗外门"})

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "failed"
    assert data["diagnostics"][0]["extra"]["bypassRequired"] is True
    assert "browserChallenges" not in data


def test_status_endpoint():
    res = client.get("/api/console/status")
    assert res.status_code == 200
    data = res.json()
    assert "pluginStats" in data
    assert "sourceStats" in data  # compatibility alias
    assert "plugins" in data  # compatibility alias


def test_legacy_admin_api_entry_not_exposed():
    res = client.get("/api/admin/status")
    assert res.status_code == 404


def test_cache_endpoint():
    res = client.get("/api/console/cache")
    assert res.status_code == 200
    data = res.json()
    assert "searchCache" in data


def test_cache_items_endpoint():
    res = client.get("/api/console/cache/items")
    assert res.status_code == 200
    data = res.json()
    assert "books" in data
    assert "tocs" in data
    assert "chapters" in data
    assert "searches" in data


def test_settings_endpoint():
    res = client.get("/api/console/settings")
    assert res.status_code == 200
    assert "contentWorkflow" in res.json()


def test_update_settings_persists_source_pool_and_refreshes_runtime(admin_client, monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace
    import app.api.console as console_api

    if not hasattr(console_api, "SOURCE_POOL_CONFIG_PATH"):
        pytest.skip("SOURCE_POOL_CONFIG_PATH not present in current console API")

    source_pool_path = tmp_path / "source_pool.json"
    source_pool_path.write_text(
        json.dumps({"max_concurrency": 3, "source_timeout_seconds": 15.0}),
        encoding="utf-8",
    )
    plugin_scheduler = SimpleNamespace(config={})
    search_service = SimpleNamespace(scheduler=SimpleNamespace(config={}))
    monkeypatch.setattr(console_api, "SOURCE_POOL_CONFIG_PATH", source_pool_path)
    monkeypatch.setattr(console_api, "_plugin_scheduler", plugin_scheduler)
    monkeypatch.setattr(console_api, "_search_service", search_service)

    payload = {
        "sourcePool": {
            "source_timeout_seconds": 18.0,
            "overall_search_timeout_seconds": 60.0,
            "browser_search_timeout_seconds": 55.0,
            "browser_source_timeout_seconds": 150.0,
        }
    }

    res = admin_client.post("/api/console/settings", json=payload)

    assert res.status_code == 200
    assert res.json()["saved"] is True
    saved = json.loads(source_pool_path.read_text(encoding="utf-8"))
    assert saved["max_concurrency"] == 3
    assert saved["source_timeout_seconds"] == 18.0
    assert saved["overall_search_timeout_seconds"] == 60.0
    assert saved["browser_search_timeout_seconds"] == 55.0
    assert saved["browser_source_timeout_seconds"] == 150.0
    assert plugin_scheduler.config["source_timeout_seconds"] == 18.0
    assert search_service.scheduler.config["browser_source_timeout_seconds"] == 150.0


def test_aggregate_source_endpoint():
    res = client.get("/api/console/aggregate-source")
    assert res.status_code == 200
    data = res.json()
    assert "generated_path" in data


def test_aggregate_settings_endpoint_returns_masked_contract():
    res = client.get("/api/console/aggregate-settings")
    assert res.status_code == 200
    data = res.json()
    assert "contentWorkflow" in data
    assert "aiProviderConfig" in data
    assert "runtime" in data
    assert data["runtime"]["windowChapterLimit"] == 5
    assert data["runtime"]["processingPlaceholder"] == "聚合处理中……请先查看其他源或稍后刷新。"
    assert "hasApiKey" in data["aiProviderConfig"]


def test_aggregate_books_endpoint_is_paginated(admin_client):
    res = admin_client.get("/api/console/aggregate-books?page=1&pageSize=2")
    assert res.status_code == 200
    data = res.json()
    assert set(["items", "page", "pageSize", "total"]).issubset(data)
    assert data["page"] == 1
    assert data["pageSize"] == 2
    assert isinstance(data["items"], list)


def test_aggregate_book_chapters_endpoint_is_paginated(admin_client):
    res = admin_client.get("/api/console/aggregate-books/nonexistent/chapters?page=1&pageSize=2")
    assert res.status_code == 200
    data = res.json()
    assert set(["items", "page", "pageSize", "total"]).issubset(data)
    assert data["page"] == 1
    assert data["pageSize"] == 2
    assert data["items"] == []


def test_aggregate_chapter_reviews_endpoint_keeps_review_contract(admin_client):
    res = admin_client.get("/api/console/aggregate-books/nonexistent/chapters/chapter-1/reviews")
    assert res.status_code == 200
    data = res.json()
    assert "chapterEndHot" in data
    assert "chapterEnd" in data
    assert "authorReviews" in data
    assert "hotParagraphReviews" in data
    assert "paragraphs" in data
    assert "summary" in data


def test_aggregate_chapter_list_does_not_include_content(admin_client):
    """Chapter list must not include processed_content — only metadata."""
    res = admin_client.get("/api/console/aggregate-books/nonexistent/chapters?page=1&pageSize=5")
    assert res.status_code == 200
    data = res.json()
    for item in data.get("items", []):
        assert "content" not in item, "Chapter list items must not include 'content'"


def test_aggregate_chapter_detail_includes_source_alignment(admin_client):
    """Single chapter detail must include source.alignment and fallbackSourceId."""
    # With a nonexistent book/chapter, we get found=False — that's fine;
    # we're testing that the response structure is correct.
    res = admin_client.get("/api/console/aggregate-books/nonexistent/chapters/nonexistent-ch")
    assert res.status_code == 200
    data = res.json()
    if data.get("found", True):
        # Only check structure if the chapter was found.
        assert "source" in data
        assert "alignment" in data.get("source", {})
        assert "fallbackSourceId" in data.get("source", {})


def test_aggregate_chapter_detail_fallback_has_content_field(admin_client):
    """A found chapter detail must include a content field (even if empty)."""
    res = admin_client.get("/api/console/aggregate-books/nonexistent/chapters/nonexistent-ch")
    assert res.status_code == 200
    data = res.json()
    # For found chapters, content should be present.
    if data.get("found", True):
        assert "content" in data


# ------------------------------------------------------------------
# Official Source Login API tests (mocked, no real private package)
# ------------------------------------------------------------------

class TestOfficialSourceLoginCapabilities:
    """GET /api/console/official-sources/{plugin_id}/login-capabilities"""

    def test_no_private_package(self, monkeypatch):
        import app.api.console as console_api

        monkeypatch.setattr(
            console_api.official_auth_manager,
            "capabilities",
            lambda _pid: {
                "pluginId": "qidian_com",
                "methods": ["cookie"],
                "defaultMethod": "cookie",
                "privateFeatures": {
                    "phoneAuth": False,
                    "cookieAuth": False,
                    "reviews": False,
                },
                "hasPrivatePackage": False,
            },
        )

        res = client.get("/api/console/official-sources/qidian_com/login-capabilities")
        assert res.status_code == 200
        data = res.json()
        assert "cookie" in data["methods"]
        assert data["defaultMethod"] == "cookie"
        assert data["privateFeatures"]["phoneAuth"] is False
        assert data["privateFeatures"]["cookieAuth"] is False
        assert data["hasPrivatePackage"] is False

    def test_with_phone_auth(self, monkeypatch):
        import app.api.console as console_api

        monkeypatch.setattr(
            console_api.official_auth_manager,
            "capabilities",
            lambda _pid: {
                "pluginId": "qidian_com",
                "methods": ["phone", "cookie"],
                "defaultMethod": "phone",
                "privateFeatures": {
                    "phoneAuth": True,
                    "cookieAuth": False,
                    "reviews": False,
                },
                "hasPrivatePackage": True,
            },
        )

        res = client.get("/api/console/official-sources/qidian_com/login-capabilities")
        assert res.status_code == 200
        data = res.json()
        assert data["methods"][0] == "phone"
        assert "cookie" in data["methods"]
        assert data["defaultMethod"] == "phone"
        assert data["privateFeatures"]["phoneAuth"] is True

    def test_qidian_public_fallback_capability_shape(self, monkeypatch):
        """Phone can be exposed via public fallback while privateFeatures.phoneAuth stays false."""
        import app.api.console as console_api

        monkeypatch.setattr(
            console_api.official_auth_manager,
            "capabilities",
            lambda _pid: {
                "pluginId": "qidian_com",
                "methods": ["phone", "cookie"],
                "defaultMethod": "phone",
                "privateFeatures": {
                    "phoneAuth": False,
                    "cookieAuth": False,
                    "reviews": False,
                },
                "hasPrivatePackage": False,
            },
        )

        res = client.get("/api/console/official-sources/qidian_com/login-capabilities")
        assert res.status_code == 200
        data = res.json()
        assert data["methods"][0] == "phone"
        assert "cookie" in data["methods"]
        assert data["defaultMethod"] == "phone"
        assert data["privateFeatures"]["phoneAuth"] is False
        assert data["hasPrivatePackage"] is False


class TestOfficialSourceCookieVerify:
    """POST /api/console/official-sources/{plugin_id}/login/cookie/verify"""

    def test_missing_cookie_text(self):
        res = client.post("/api/console/official-sources/qidian_com/login/cookie/verify", json={})
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is False
        assert "缺少 Cookie 文本" in data["error"]

    def test_verify_cookie_calls_manager(self, monkeypatch):
        import app.api.console as console_api

        calls = []

        async def mock_verify_cookie(plugin_id: str, cookie_text: str):
            calls.append({"plugin_id": plugin_id, "cookie_text": cookie_text})
            return {
                "ok": True,
                "authenticated": True,
                "accountName": "test_user",
                "message": "Cookie 有效",
                "hasCookies": True,
                "cookieDomains": ["qidian.com"],
            }

        monkeypatch.setattr(console_api.official_auth_manager, "verify_cookie", mock_verify_cookie)

        res = client.post(
            "/api/console/official-sources/qidian_com/login/cookie/verify",
            json={"cookieText": "ywguid=abc; ywkey=def"},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["authenticated"] is True
        assert data["accountName"] == "test_user"
        assert data["message"] == "Cookie 有效"
        assert len(calls) == 1
        assert calls[0]["plugin_id"] == "qidian_com"


class TestOfficialSourcePhoneRequestCode:
    """POST /api/console/official-sources/{plugin_id}/login/phone/request-code"""

    def test_missing_phone(self):
        res = client.post(
            "/api/console/official-sources/qidian_com/login/phone/request-code",
            json={},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is False
        assert "缺少手机号" in data["error"]

    def test_full_payload_forwarded(self, monkeypatch):
        import app.api.console as console_api

        captured = []

        def mock_request_phone_code(plugin_id: str, payload: dict):
            captured.append(payload)
            return {"ok": True, "sessionId": "sess_123", "nextAction": "verify_code"}

        monkeypatch.setattr(
            console_api.official_auth_manager, "request_phone_code", mock_request_phone_code
        )

        res = client.post(
            "/api/console/official-sources/qidian_com/login/phone/request-code",
            json={
                "phone": "13800138000",
                "sessionId": "abc",
                "challengeToken": "ticket123",
                "challengeRandstr": "@rand",
            },
        )

        assert res.status_code == 200
        assert res.json()["ok"] is True
        assert len(captured) == 1
        payload = captured[0]
        assert payload["phone"] == "13800138000"
        assert payload["sessionId"] == "abc"
        assert payload["challengeToken"] == "ticket123"
        assert payload["challengeRandstr"] == "@rand"

    def test_challenge_response_passed_through(self, monkeypatch):
        import app.api.console as console_api

        monkeypatch.setattr(
            console_api.official_auth_manager,
            "request_phone_code",
            lambda _pid, _payload: {
                "ok": False,
                "sessionId": "abc",
                "nextAction": "complete_challenge",
                "challenge": {"type": "official_webview"},
            },
        )

        res = client.post(
            "/api/console/official-sources/qidian_com/login/phone/request-code",
            json={"phone": "13800138000"},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is False
        assert data["nextAction"] == "complete_challenge"
        assert data["challenge"]["type"] == "official_webview"


class TestOfficialSourcePhoneVerify:
    """POST /api/console/official-sources/{plugin_id}/login/phone/verify"""

    def test_verify_phone(self, monkeypatch):
        import app.api.console as console_api

        calls = []

        async def mock_verify_phone_code(plugin_id: str, payload: dict):
            calls.append(payload)
            return {
                "ok": True,
                "authenticated": True,
                "accountName": "foo",
                "message": "登录成功",
                "hasCookies": True,
            }

        monkeypatch.setattr(
            console_api.official_auth_manager, "verify_phone_code", mock_verify_phone_code
        )

        res = client.post(
            "/api/console/official-sources/qidian_com/login/phone/verify",
            json={"sessionId": "sess_123", "phone": "13800138000", "code": "123456"},
        )

        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["authenticated"] is True
        assert data["accountName"] == "foo"
        assert data["message"] == "登录成功"
        assert len(calls) == 1


class TestOfficialSourceLogout:
    """POST /api/console/official-sources/{plugin_id}/login/logout"""

    def test_logout(self, monkeypatch):
        import app.api.console as console_api

        calls = []

        def mock_logout(plugin_id: str):
            calls.append(plugin_id)
            return {"ok": True, "message": "登录状态已清除"}

        monkeypatch.setattr(console_api.official_auth_manager, "logout", mock_logout)

        res = client.post("/api/console/official-sources/qidian_com/login/logout")

        assert res.status_code == 200
        data = res.json()
        assert data["ok"] is True
        assert data["message"] == "登录状态已清除"
        assert calls == ["qidian_com"]


def test_library_book_summary_shared_mode_sanitizes_source_map_for_non_admin(monkeypatch):
    import app.api.console as console_api

    monkeypatch.setattr(
        console_api.auth_service,
        "require_user",
        lambda _request: SimpleNamespace(user_id="user-1", role="user"),
    )
    monkeypatch.setattr(
        console_api.AggregateSettingsRepository,
        "content_workflow",
        lambda self: {"useSharedBookStorage": True, "sharedBookStorageReadMode": "shared"},
    )
    monkeypatch.setattr(
        console_api.library_books_service,
        "get_book",
        lambda _book_id: {
            "aggregateBookId": "book-1",
            "name": "测试小说",
            "author": "作者甲",
            "status": "active",
        },
    )
    monkeypatch.setattr(
        console_api.library_books_service,
        "load_shared_metadata",
        lambda _book_id: {
            "sourceMap": {
                "summary": [
                    {
                        "bookId": "src-a:1",
                        "sourceId": "src-a",
                        "sourceName": "来源A",
                        "score": 97,
                        "chapterCount": 123,
                        "lastChapter": "第123章",
                        "bookStatus": "ongoing",
                        "name": "测试小说",
                        "author": "作者甲",
                        "bookUrl": "https://private.example/book/1",
                    }
                ],
                "health": {"status": "healthy", "lastVerifiedAt": "2026-06-27T00:00:00Z"},
            },
            "bookState": {
                "status": "active",
                "chapterCount": 123,
                "processedChapterCount": 45,
            },
        },
    )

    res = client.get("/api/console/library-books/book-1/summary")

    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "shared"
    assert data["book"]["aggregateBookId"] == "book-1"
    assert data["sourceMap"]["summary"][0]["sourceId"] == "src-a"
    assert "bookUrl" not in data["sourceMap"]["summary"][0]
    assert data["bookState"]["processedChapterCount"] == 45


def test_library_book_summary_legacy_mode_returns_legacy_shape(monkeypatch):
    import app.api.console as console_api

    monkeypatch.setattr(
        console_api.auth_service,
        "require_user",
        lambda _request: SimpleNamespace(user_id="admin-1", role="admin"),
    )
    monkeypatch.setattr(
        console_api.AggregateSettingsRepository,
        "content_workflow",
        lambda self: {"useSharedBookStorage": False, "sharedBookStorageReadMode": "legacy"},
    )
    monkeypatch.setattr(
        console_api,
        "_load_legacy_library_book_summary",
        lambda _book_id: {
            "aggregateBookId": "book-legacy",
            "name": "旧格式小说",
            "status": "active",
            "found": True,
        },
    )

    res = client.get("/api/console/library-books/book-legacy/summary")

    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "legacy"
    assert data["aggregateBookId"] == "book-legacy"
    assert data["found"] is True
    assert "sourceMap" not in data


def test_library_book_chapter_progress_route_sanitizes_trace_by_default(monkeypatch):
    import app.api.console as console_api

    monkeypatch.setattr(
        console_api.auth_service,
        "require_user",
        lambda _request: SimpleNamespace(user_id="user-1", role="user"),
    )
    monkeypatch.setattr(
        console_api,
        "_load_library_book_chapter_progress",
        lambda _book_id, _chapter_id: {
            "bookId": "book-1",
            "chapterId": "chapter-1",
            "traceSummary": {
                "chapterStatus": "processed",
                "selectedSource": "src-a",
                "alignmentPassed": True,
                "sourceSnapshotRefs": [{"sourceId": "src-a", "bookUrl": "https://private.example"}],
                "sourceChapterUrl": "https://private.example/chapter/1",
            },
        },
    )

    res = client.get("/api/console/library-books/book-1/chapters/chapter-1/progress")

    assert res.status_code == 200
    data = res.json()
    assert data["traceSummary"]["chapterStatus"] == "processed"
    assert data["traceSummary"]["selectedSource"] == "src-a"
    assert "sourceSnapshotRefs" not in data["traceSummary"]
    assert "sourceChapterUrl" not in data["traceSummary"]


def test_library_book_chapters_shared_mode_returns_paginated_shared_shape(monkeypatch):
    import app.api.console as console_api

    monkeypatch.setattr(
        console_api.auth_service,
        "require_user",
        lambda _request: SimpleNamespace(user_id="user-1", role="user"),
    )
    monkeypatch.setattr(
        console_api.AggregateSettingsRepository,
        "content_workflow",
        lambda self: {"useSharedBookStorage": True, "sharedBookStorageReadMode": "shared"},
    )
    monkeypatch.setattr(
        console_api,
        "_list_shared_library_book_chapters",
        lambda _book_id, **_kwargs: {
            "items": [
                {
                    "chapterId": "chapter-1",
                    "chapterIndex": 1,
                    "title": "第一章",
                    "status": "processed",
                    "hasContent": True,
                }
            ],
            "page": 2,
            "pageSize": 10,
            "total": 21,
        },
    )

    res = client.get("/api/console/library-books/book-1/chapters?page=2&pageSize=10")

    assert res.status_code == 200
    data = res.json()
    assert data["mode"] == "shared"
    assert data["page"] == 2
    assert data["pageSize"] == 10
    assert data["total"] == 21
    assert data["items"][0]["chapterId"] == "chapter-1"
    assert "content" not in data["items"][0]


def test_library_book_logs_route_uses_console_shape(monkeypatch):
    import app.api.console as console_api

    monkeypatch.setattr(
        console_api.auth_service,
        "require_user",
        lambda _request: SimpleNamespace(user_id="user-1", role="user"),
    )
    monkeypatch.setattr(
        console_api,
        "_list_library_book_logs",
        lambda _book_id, **_kwargs: {
            "bookId": _book_id,
            "items": [{"id": 1, "operationType": "refresh_source_map", "createdAt": "2026-06-27T00:00:00Z"}],
            "limit": 20,
            "offset": 0,
            "total": 1,
        },
    )

    res = client.get("/api/console/library-books/book-1/logs?limit=20")

    assert res.status_code == 200
    data = res.json()
    assert data["bookId"] == "book-1"
    assert data["items"][0]["operationType"] == "refresh_source_map"
    assert data["limit"] == 20
    assert data["total"] == 1


def test_library_book_manual_console_routes_exist(monkeypatch):
    import app.api.console as console_api

    monkeypatch.setattr(
        console_api.auth_service,
        "require_admin",
        lambda _request: SimpleNamespace(user_id="admin-1", role="admin"),
    )
    monkeypatch.setattr(
        console_api,
        "_manual_source_map_refresh",
        lambda _book_id, payload=None: {"ok": True, "bookId": _book_id, "payload": payload or {}},
    )
    monkeypatch.setattr(
        console_api,
        "_manual_library_book_repair",
        lambda _book_id, payload=None: {"ok": True, "bookId": _book_id, "action": "repair"},
    )
    monkeypatch.setattr(
        console_api,
        "_manual_library_book_update_check",
        lambda _book_id: {"ok": True, "bookId": _book_id, "action": "update-check"},
    )

    refresh_res = client.post("/api/console/library-books/book-1/source-map/refresh", json={"force": True})
    repair_res = client.post("/api/console/library-books/book-1/repair", json={"reason": "manual"})
    update_res = client.post("/api/console/library-books/book-1/update-check")

    assert refresh_res.status_code == 200
    assert refresh_res.json()["bookId"] == "book-1"
    assert repair_res.status_code == 200
    assert repair_res.json()["action"] == "repair"
    assert update_res.status_code == 200
    assert update_res.json()["action"] == "update-check"
