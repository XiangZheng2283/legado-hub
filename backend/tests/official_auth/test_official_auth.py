"""Tests for official-auth login flow.

Covers:
- login-capabilities (with/without private package)
- cookie/verify (public path, no private dependency)
- phone/request-code (challenge param forwarding)
- phone/verify (session lifecycle)
- chapter_reviews routing (private vs fallback)

All tests are designed to run WITHOUT a real private package.
Private-package tests use tmp_path injection.
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is on path so `plugins.*` imports work
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ------------------------------------------------------------------
# Public cookie tools
# ------------------------------------------------------------------

def test_public_cookie_parse_semicolon():
    from app.services.official_auth.manager import PublicCookieTools

    text = "ywguid=abc123; ywkey=def456; _csrfToken=xyz789"
    jar = PublicCookieTools.parse_cookie_text(text)

    assert "qidian.com" in jar
    assert jar["qidian.com"]["ywguid"] == "abc123"
    assert jar["qidian.com"]["ywkey"] == "def456"
    assert "yuewen.com" in jar
    assert jar["yuewen.com"]["ywguid"] == "abc123"


def test_public_cookie_parse_json():
    from app.services.official_auth.manager import PublicCookieTools

    text = '{"ywguid": "abc", "ywkey": "def"}'
    jar = PublicCookieTools.parse_cookie_text(text)

    assert jar["qidian.com"]["ywguid"] == "abc"


def test_public_cookie_verify_valid():
    from app.services.official_auth.manager import PublicCookieTools

    jar = {"qidian.com": {"ywguid": "abc", "ywkey": "def"}, "yuewen.com": {"ywguid": "abc"}}
    result = PublicCookieTools.basic_verify(jar)

    assert result["authenticated"] is True
    assert "ywguid" in result["message"]


def test_public_cookie_verify_missing_critical():
    from app.services.official_auth.manager import PublicCookieTools

    jar = {"qidian.com": {"foo": "bar"}}
    result = PublicCookieTools.basic_verify(jar)

    assert result["authenticated"] is False
    assert "ywguid" in result["message"] or "ywkey" in result["message"]


# ------------------------------------------------------------------
# Login capabilities — NO real private package dependency
# ------------------------------------------------------------------

def test_capabilities_without_private_package():
    """When no private package exists, cookie must still be available."""
    from app.services.official_auth.manager import official_auth_manager

    caps = official_auth_manager.capabilities("__nonexistent_plugin_for_test__")

    assert "cookie" in caps["methods"]
    assert "phone" not in caps["methods"]
    assert caps["privateFeatures"]["phoneAuth"] is False
    assert caps["privateFeatures"]["cookieAuth"] is False  # no private enhancement
    assert caps["hasPrivatePackage"] is False


# ------------------------------------------------------------------
# Cookie verify — async public path with qidian_com Cookie.json
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cookie_verify_public_path_saves_cookie_json():
    """CK login parses cookies, writes Cookie.json, and returns the auth_status probe result."""
    from app.services.official_auth.manager import official_auth_manager
    from app.services import plugin_cookie_file_store

    plugin_cookie_file_store.clear("qidian_com")

    with patch.object(
        official_auth_manager,
        "_deep_verify_via_plugin",
        new=AsyncMock(return_value={
            "authenticated": True,
            "accountName": "reader_1",
            "message": "已登录",
            "authStatus": "authenticated",
        }),
    ):
        result = await official_auth_manager.verify_cookie(
            "qidian_com",
            "ywguid=test_guid; ywkey=test_key; _csrfToken=test_csrf",
        )

    assert result["ok"] is True
    assert result["authenticated"] is True
    assert result["hasCookies"] is True
    assert "qidian.com" in result["cookieDomains"]

    saved = plugin_cookie_file_store.load("qidian_com")
    assert saved["qidian.com"]["ywguid"] == "test_guid"
    assert saved["qidian.com"]["_csrfToken"] == "test_csrf"


@pytest.mark.asyncio
async def test_cookie_verify_auth_status_anonymous():
    """When the plugin auth_status probe says anonymous, verify_cookie reports not authenticated."""
    from app.services.official_auth.manager import official_auth_manager
    from app.services import plugin_cookie_file_store

    plugin_cookie_file_store.clear("qidian_com")

    with patch.object(
        official_auth_manager,
        "_deep_verify_via_plugin",
        new=AsyncMock(return_value={
            "authenticated": False,
            "accountName": "",
            "message": "未登录",
            "authStatus": "anonymous",
        }),
    ):
        result = await official_auth_manager.verify_cookie(
            "qidian_com",
            "ywguid=test_guid; ywkey=test_key; _csrfToken=test_csrf",
        )

    assert result["ok"] is False
    assert result["authenticated"] is False
    assert result["hasCookies"] is True
    assert plugin_cookie_file_store.exists("qidian_com")


@pytest.mark.asyncio
async def test_cookie_verify_auth_status_pending():
    """When auth_status cannot decide, cookies are still saved and status stays pending."""
    from app.services.official_auth.manager import official_auth_manager
    from app.services import plugin_cookie_file_store

    plugin_cookie_file_store.clear("qidian_com")

    with patch.object(
        official_auth_manager,
        "_deep_verify_via_plugin",
        new=AsyncMock(return_value={
            "authenticated": False,
            "accountName": "",
            "message": "探测失败",
            "authStatus": "pending",
        }),
    ):
        result = await official_auth_manager.verify_cookie(
            "qidian_com",
            "ywguid=test_guid; ywkey=test_key; _csrfToken=test_csrf",
        )

    assert result["ok"] is False
    assert result["hasCookies"] is True
    assert plugin_cookie_file_store.exists("qidian_com")


# ------------------------------------------------------------------
# Phone login challenge param forwarding
# ------------------------------------------------------------------

def test_request_code_forwards_full_payload():
    """Challenge params (challengeToken, challengeRandstr) must be forwarded to private auth_api."""
    from app.services.official_auth.manager import official_auth_manager

    mock_auth_api = MagicMock()
    mock_auth_api.request_code = MagicMock(return_value={
        "ok": False,
        "sessionId": "private_session_123",
        "nextAction": "complete_challenge",
        "challenge": {"type": "tencent_captcha"},
    })

    with patch(
        "app.services.official_auth.manager.private_plugin_loader.load",
        return_value={"authApi": mock_auth_api, "cookieAuth": None, "manifest": None, "available": True},
    ):
        result = official_auth_manager.request_phone_code("fake_phone_plugin", {
            "phone": "13800138000",
            "challengeToken": "test_ticket",
            "challengeRandstr": "@test_rand",
        })

    assert result["nextAction"] == "complete_challenge"
    mock_auth_api.request_code.assert_called_once()
    call_args = mock_auth_api.request_code.call_args[0][0]
    assert call_args["challengeToken"] == "test_ticket"
    assert call_args["challengeRandstr"] == "@test_rand"


# ------------------------------------------------------------------
# Private phone auth path
# ------------------------------------------------------------------

def test_capabilities_exposes_phone_when_private_auth_exists():
    """Phone login is advertised only when the plugin provides a private auth_api."""
    from app.services.official_auth.manager import official_auth_manager

    with patch(
        "app.services.official_auth.manager.private_plugin_loader.load",
        return_value={"authApi": MagicMock(), "cookieAuth": None, "manifest": None, "available": True},
    ):
        caps = official_auth_manager.capabilities("fake_phone_plugin")

    assert "phone" in caps["methods"]
    assert "cookie" in caps["methods"]
    assert caps["defaultMethod"] == "phone"
    assert caps["privateFeatures"]["phoneAuth"] is True
    assert caps["hasPrivatePackage"] is True


def test_request_code_private_returns_challenge():
    """Fresh request-code with a private auth_api returns a captcha challenge."""
    from app.services.official_auth.manager import official_auth_manager
    from app.services.official_auth.sessions import session_store

    mock_auth_api = MagicMock()
    mock_auth_api.request_code = MagicMock(return_value={
        "ok": False,
        "sessionId": "private_session_123",
        "nextAction": "complete_challenge",
        "challenge": {"appId": "1600000770", "type": "tencent_captcha"},
    })

    with patch(
        "app.services.official_auth.manager.private_plugin_loader.load",
        return_value={"authApi": mock_auth_api, "cookieAuth": None, "manifest": None, "available": True},
    ):
        result = official_auth_manager.request_phone_code("fake_phone_plugin", {"phone": "13800138000"})

    assert result["ok"] is False
    assert result["nextAction"] == "complete_challenge"
    assert result["challenge"]["appId"] == "1600000770"
    assert result["challenge"]["type"] == "tencent_captcha"

    # Official session should be created and hold the private session id
    official_session = session_store.get(result["sessionId"])
    assert official_session is not None
    assert official_session.private_payload["sessionId"] == "private_session_123"
    session_store.remove(result["sessionId"])


def test_request_code_retry_sends_sms():
    """Retry with challenge token should call private auth_api again and return verify_code."""
    from app.services.official_auth.manager import official_auth_manager
    from app.services.official_auth.sessions import session_store

    mock_auth_api = MagicMock()
    mock_auth_api.request_code = MagicMock(side_effect=[
        {"ok": False, "sessionId": "private_session_123", "nextAction": "complete_challenge", "challenge": {}},
        {"ok": True, "sessionId": "private_session_123", "nextAction": "verify_code"},
    ])

    with patch(
        "app.services.official_auth.manager.private_plugin_loader.load",
        return_value={"authApi": mock_auth_api, "cookieAuth": None, "manifest": None, "available": True},
    ):
        init_result = official_auth_manager.request_phone_code("fake_phone_plugin", {"phone": "13800138000"})
        retry_result = official_auth_manager.request_phone_code("fake_phone_plugin", {
            "phone": "13800138000",
            "sessionId": init_result["sessionId"],
            "challengeToken": "ticket_123",
            "challengeRandstr": "@rand",
        })

    assert retry_result["ok"] is True
    assert retry_result["nextAction"] == "verify_code"
    assert mock_auth_api.request_code.call_count == 2
    second_call = mock_auth_api.request_code.call_args_list[1][0][0]
    assert second_call["sessionId"] == "private_session_123"
    assert second_call["challengeToken"] == "ticket_123"
    assert second_call["challengeRandstr"] == "@rand"

    session_store.remove(init_result["sessionId"])


@pytest.mark.asyncio
async def test_verify_phone_code_private_saves_cookie_json(monkeypatch, tmp_path):
    """Successful private verify writes Cookie.json and caches probe status."""
    from app.services.official_auth.manager import official_auth_manager
    from app.services.official_auth.sessions import session_store
    from app.services.plugin_auth_repository import PluginAuthRepository
    from app.services import plugin_cookie_file_store

    plugin_id = "qidian_com"
    plugin_cookie_file_store.clear(plugin_id)

    mock_auth_api = MagicMock()
    mock_auth_api.request_code = MagicMock(return_value={
        "ok": True,
        "sessionId": "private_session_123",
        "nextAction": "verify_code",
    })
    mock_auth_api.verify_code = MagicMock(return_value={
        "ok": True,
        "authenticated": True,
        "accountName": "13800138000",
        "cookies": {
            "qidian.com": {"ywguid": "guid_123", "ywkey": "key_123"},
            "yuewen.com": {"ywguid": "guid_123", "ywkey": "key_123"},
        },
        "message": "登录成功",
    })

    repo = PluginAuthRepository(tmp_path / "auth.db")
    monkeypatch.setattr(
        "app.services.official_auth.manager.PluginAuthRepository",
        lambda: repo,
    )

    with patch(
        "app.services.official_auth.manager.private_plugin_loader.load",
        return_value={"authApi": mock_auth_api, "cookieAuth": None, "manifest": None, "available": True},
    ):
        with patch.object(
            official_auth_manager,
            "_deep_verify_via_plugin",
            new=AsyncMock(return_value={
                "authenticated": True,
                "accountName": "13800138000",
                "message": "登录成功",
                "authStatus": "authenticated",
            }),
        ):
            sms_result = official_auth_manager.request_phone_code(plugin_id, {"phone": "13800138000"})
            verify_result = await official_auth_manager.verify_phone_code(plugin_id, {
                "sessionId": sms_result["sessionId"],
                "phone": "13800138000",
                "code": "123456",
            })

    assert verify_result["ok"] is True
    assert verify_result["authenticated"] is True
    assert verify_result["hasCookies"] is True

    # Cookie truth source is Cookie.json, not DB cookie_json.
    saved = plugin_cookie_file_store.load(plugin_id)
    assert "qidian.com" in saved
    assert saved["qidian.com"]["ywguid"] == "guid_123"

    status = repo.get_status(plugin_id)
    assert status["authenticated"] is True
    assert status["authStatus"] == "authenticated"
    assert status["accountName"] == "13800138000"
    assert status["hasCookies"] is True

    # Session should be cleaned up
    assert session_store.get(sms_result["sessionId"]) is None


@pytest.mark.asyncio
async def test_probe_saved_cookie_file_refreshes_status_from_cookie_json(monkeypatch, tmp_path):
    from app.services.official_auth.manager import official_auth_manager
    from app.services.plugin_auth_repository import PluginAuthRepository
    from app.services import plugin_cookie_file_store

    plugin_cookie_file_store.clear("qidian_com")
    plugin_cookie_file_store.save("qidian_com", {"qidian.com": {"ywguid": "1", "ywkey": "2"}})

    repo = PluginAuthRepository(tmp_path / "auth.db")
    monkeypatch.setattr(
        "app.services.official_auth.manager.PluginAuthRepository",
        lambda: repo,
    )

    with patch.object(
        official_auth_manager,
        "_deep_verify_via_plugin",
        new=AsyncMock(return_value={
            "authenticated": True,
            "accountName": "reader_1",
            "message": "已登录",
            "authStatus": "authenticated",
            "requiredActions": [],
        }),
    ):
        result = await official_auth_manager.probe_saved_cookie_file("qidian_com")

    assert result["authenticated"] is True
    status = repo.get_status("qidian_com")
    assert status["authenticated"] is True
    assert status["accountName"] == "reader_1"
    assert status["hasCookies"] is True


@pytest.mark.asyncio
async def test_probe_saved_cookie_file_without_file_marks_anonymous_and_clears_db_cookie(monkeypatch, tmp_path):
    from app.services.official_auth.manager import official_auth_manager
    from app.services.plugin_auth_repository import PluginAuthRepository
    from app.services import plugin_cookie_file_store

    plugin_cookie_file_store.clear("qidian_com")

    repo = PluginAuthRepository(tmp_path / "auth.db")
    repo.set_cookies("qidian_com", {"qidian.com": {"legacy": "cookie"}})
    repo.update_status(
        "qidian_com",
        {
            "authenticated": True,
            "accountName": "reader_1",
            "message": "旧状态",
        },
    )
    monkeypatch.setattr(
        "app.services.official_auth.manager.PluginAuthRepository",
        lambda: repo,
    )

    result = await official_auth_manager.probe_saved_cookie_file("qidian_com")

    assert result["authStatus"] == "anonymous"
    assert repo.get_cookies("qidian_com") == {}
    status = repo.get_status("qidian_com")
    assert status["authenticated"] is False
    assert status["authStatus"] == "anonymous"
    assert status["hasCookies"] is False


# ------------------------------------------------------------------
# Session lifecycle
# ------------------------------------------------------------------

def test_session_expiry():
    from app.services.official_auth.sessions import OfficialLoginSession

    session = OfficialLoginSession(plugin_id="qidian_com")
    assert session.expired() is False

    session.created_at = 0
    assert session.expired() is True


def test_session_store_create_and_get():
    from app.services.official_auth.sessions import session_store

    s = session_store.create("qidian_com", "phone")
    assert s.plugin_id == "qidian_com"
    assert s.method == "phone"

    found = session_store.get(s.session_id)
    assert found is not None
    assert found.session_id == s.session_id

    session_store.remove(s.session_id)
    assert session_store.get(s.session_id) is None


# ------------------------------------------------------------------
# Chapter reviews — no real private package dependency
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chapter_reviews_without_private():
    """Without private reviews.py, should use the public fallback implementation."""
    from plugins.sources.official.qidian_com.source import Source

    source = Source()

    class MockCookies:
        def get(self, domain, name=None):
            if name == "_csrfToken":
                return "test_csrf"
            return {"_csrfToken": "test_csrf"} if name is None else None

    class MockHTTP:
        async def fetch_json(self, url, *, params=None, headers=None, **kwargs):
            params = params or {}
            if "reviewsummary4m" in url:
                return {
                    "code": 0,
                    "data": {
                        "total": 2,
                        "list": [
                            {"paragraphId": 1, "reviewNum": 1, "textCount": 88},
                            {"paragraphId": -1, "reviewNum": 1, "textCount": 0},
                        ],
                    },
                }
            if "reviewlist4m" in url and params.get("paragraphId") == 1:
                return {
                    "code": 0,
                    "data": {
                        "list": [
                            {
                                "reviewId": "p1",
                                "content": "这一段写得真好",
                                "userName": "读者甲",
                                "likeAmount": 3,
                                "replyCount": 1,
                                "createTimeStr": "1小时前",
                                "isTop": 1,
                            }
                        ]
                    },
                }
            if "reviewlist4m" in url and params.get("paragraphId") == -1:
                return {
                    "code": 0,
                    "data": {
                        "list": [
                            {
                                "reviewId": "end1",
                                "content": "章末评论",
                                "userName": "读者乙",
                                "likeAmount": 2,
                                "replyCount": 0,
                                "createTimeStr": "刚刚",
                                "isTop": 0,
                            }
                        ]
                    },
                }
            raise AssertionError(f"unexpected url: {url} params={params}")

    class MockCtx:
        cookies = MockCookies()
        access = MagicMock(http=MockHTTP())

        def trace(self, event, **kwargs):
            pass

    with patch(
        "app.services.official_auth.loader.private_plugin_loader.load",
        return_value={"reviews": None},
    ):
        result = await source.chapter_reviews(MockCtx(), "https://m.qidian.com/chapter/123/456/")

    assert result["paragraphs"]["1"][0]["content"] == "这一段写得真好"
    assert result["chapterEnd"][0]["content"] == "章末评论"
    assert result["summary"]["totalParagraphs"] == 1
    assert result["summary"]["chapterEndCount"] == 1


@pytest.mark.asyncio
async def test_chapter_reviews_private_success():
    """With private reviews.py, should route to it and return its result."""
    from plugins.sources.official.qidian_com.source import Source

    source = Source()
    mock_reviews = MagicMock()
    mock_reviews.chapter_reviews = AsyncMock(return_value={
        "paragraphs": {"1": [{"content": "great"}]},
        "chapterEnd": [],
        "summary": {"totalReviews": 1},
    })

    with patch(
        "app.services.official_auth.loader.private_plugin_loader.load",
        return_value={"reviews": mock_reviews},
    ):
        result = await source.chapter_reviews(None, "https://m.qidian.com/chapter/123/456/")

    assert result["paragraphs"]["1"][0]["content"] == "great"
    mock_reviews.chapter_reviews.assert_awaited_once()


@pytest.mark.asyncio
async def test_chapter_reviews_private_error():
    """When private reviews.py exists but throws, should report 'private plugin error'."""
    from plugins.sources.official.qidian_com.source import Source

    source = Source()
    mock_reviews = MagicMock()
    mock_reviews.chapter_reviews = AsyncMock(side_effect=RuntimeError("network timeout"))

    class MockCtx:
        def trace(self, event, **kwargs):
            pass

    with patch(
        "app.services.official_auth.loader.private_plugin_loader.load",
        return_value={"reviews": mock_reviews},
    ):
        result = await source.chapter_reviews(MockCtx(), "https://m.qidian.com/chapter/123/456/")

    assert result.get("debug", {}).get("error") == "reviews private plugin error: network timeout"


# ------------------------------------------------------------------
# Private plugin loader — tmp_path injection (no real private dir dependency)
# ------------------------------------------------------------------

def test_private_loader_nonexistent_plugin():
    from app.services.official_auth.loader import private_plugin_loader

    result = private_plugin_loader.load("__totally_missing__")

    assert result["available"] is False
    assert result["methods"] == []


def test_private_loader_with_injected_package(tmp_path, monkeypatch):
    """Inject a fake private package via tmp_path to verify loader logic."""
    from app.services.official_auth.loader import PrivatePluginLoader

    # Build fake private package
    fake_plugin_dir = tmp_path / "official" / "fake_src" / "private"
    fake_plugin_dir.mkdir(parents=True)

    manifest = {
        "pluginId": "fake_src",
        "version": "1.0.0",
        "capabilities": {
            "phoneAuth": True,
            "cookieAuth": True,
            "reviews": True,
        },
    }
    (fake_plugin_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Minimal auth_api.py
    (fake_plugin_dir / "auth_api.py").write_text(
        "def request_code(payload): return {'ok': True}\n"
        "def verify_code(payload): return {'ok': True, 'authenticated': True}\n",
        encoding="utf-8",
    )

    # Minimal cookie_auth.py
    (fake_plugin_dir / "cookie_auth.py").write_text(
        "def verify_cookies(jar): return {'message': 'enhanced'}\n",
        encoding="utf-8",
    )

    # Minimal reviews.py (async)
    (fake_plugin_dir / "reviews.py").write_text(
        "async def chapter_reviews(ctx, url): return {'paragraphs': {}, 'chapterEnd': [], 'summary': {}}\n",
        encoding="utf-8",
    )

    loader = PrivatePluginLoader()
    monkeypatch.setattr(loader, "BASE_DIR", tmp_path)
    loader.invalidate("fake_src")

    result = loader.load("fake_src")

    assert result["available"] is True
    assert result["pluginId"] == "fake_src"
    assert "phone" in result["methods"]
    assert "cookie" in result["methods"]
    assert result["authApi"] is not None
    assert result["cookieAuth"] is not None
    assert result["reviews"] is not None


@pytest.mark.asyncio
async def test_get_plugin_auth_preserves_account_name_on_probe_failure(monkeypatch):
    """If auth_status probe fails but cookies exist, don't wipe stored accountName."""
    from app.api.console import get_plugin_auth, _plugin_scheduler
    from app.services.plugin_auth_repository import PluginAuthRepository
    from app.services import plugin_cookie_file_store

    repo = PluginAuthRepository()
    plugin_cookie_file_store.save("qidian_com", {"qidian.com": {"_csrfToken": "test", "ywguid": "g", "ywkey": "k"}})
    repo.update_status(
        "qidian_com",
        {
            "authenticated": True,
            "accountName": "158****1035",
            "message": "登录成功",
        },
    )

    async def failing_auth_status(ctx):
        return {
            "sourceId": "qidian_com",
            "authenticated": False,
            "accountName": "",
            "message": "probe failed",
        }

    fake_plugin = MagicMock()
    fake_plugin.metadata.auth = {"mode": "optional"}
    fake_plugin.capabilities = ["auth"]
    fake_plugin.source.auth_status = failing_auth_status
    monkeypatch.setitem(_plugin_scheduler._plugins, "qidian_com", fake_plugin)

    result = await get_plugin_auth("qidian_com")
    assert result["authenticated"] is False
    assert result["accountName"] == "158****1035"
    # DB should still know cookies exist even though probe failed.
    assert repo.get_status("qidian_com")["hasCookies"] is True
