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
# Cookie verify — async public path
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cookie_verify_public_path():
    """CK login works via public parse+verify when deep plugin validation is unavailable."""
    from app.services.official_auth.manager import official_auth_manager

    with patch.object(
        official_auth_manager, "_deep_verify_via_plugin", return_value=None
    ):
        result = await official_auth_manager.verify_cookie(
            "qidian_com",
            "ywguid=test_guid; ywkey=test_key; _csrfToken=test_csrf",
        )

    assert result["ok"] is True
    assert result["authenticated"] is True
    assert result["hasCookies"] is True
    assert "qidian.com" in result["cookieDomains"]


@pytest.mark.asyncio
async def test_cookie_verify_deep_merge():
    """Deep verify result should be merged into the final response."""
    from app.services.official_auth.manager import OfficialAuthManager

    deep = {"authenticated": False, "accountName": "", "message": "deep says no"}
    manager = OfficialAuthManager()
    manager._deep_verify_via_plugin = AsyncMock(return_value=deep)

    with patch(
        "app.services.official_auth.manager.private_plugin_loader.load",
        return_value={"cookieAuth": None},
    ):
        result = await manager.verify_cookie(
            "qidian_com",
            "ywguid=test_guid; ywkey=test_key; _csrfToken=test_csrf",
        )

    assert result["ok"] is False
    assert result["authenticated"] is False
    assert "deep says no" in result["message"]


@pytest.mark.asyncio
async def test_cookie_verify_private_enhancement_overrides_auth():
    """Private cookie_auth.verify_cookies() can override the final authenticated state.

    Public basic verify says True, but private enhancement says False.
    The private result must win.
    """
    from app.services.official_auth.manager import OfficialAuthManager

    manager = OfficialAuthManager()
    manager._deep_verify_via_plugin = AsyncMock(return_value=None)

    mock_cookie_auth = MagicMock()
    mock_cookie_auth.verify_cookies.return_value = {
        "authenticated": False,
        "message": "private says invalid",
    }

    with patch(
        "app.services.official_auth.manager.private_plugin_loader.load",
        return_value={"cookieAuth": mock_cookie_auth},
    ):
        result = await manager.verify_cookie(
            "qidian_com",
            "ywguid=test_guid; ywkey=test_key; _csrfToken=test_csrf",
        )

    assert result["authenticated"] is False
    assert result["ok"] is False
    assert result["message"] == "private says invalid"
    mock_cookie_auth.verify_cookies.assert_called_once()


# ------------------------------------------------------------------
# Phone login challenge param forwarding
# ------------------------------------------------------------------

def test_request_code_forwards_full_payload():
    """Challenge params (sessionId, challengeToken, challengeRandstr) must be forwarded."""
    from app.services.official_auth.manager import official_auth_manager

    result = official_auth_manager.request_phone_code("qidian_com", {
        "phone": "13800138000",
        "sessionId": "test_session",
        "challengeToken": "test_ticket",
        "challengeRandstr": "@test_rand",
    })

    assert "error" in result or result.get("ok") is True


# ------------------------------------------------------------------
# Qidian public phone fallback (no private authApi)
# ------------------------------------------------------------------

def _fake_qidian_session(session_id: str = "qd_123", status: str = "captcha"):
    """Build a minimal fake QidianLoginSession for monkeypatching."""
    session = MagicMock()
    session.session_id = session_id
    session.status = status
    session.captcha_app_id = "1600000770"
    session.captcha_type = 1
    session.captcha_url = "https://turing.captcha.qcloud.com/TCaptcha.js"
    session.phone = "13800138000"
    session.message = "mock"
    session.cookies = {
        "qidian.com": {"ywguid": "guid_123", "ywkey": "key_123"},
        "yuewen.com": {"ywguid": "guid_123", "ywkey": "key_123"},
    }
    return session


def test_qidian_fallback_capabilities_exposes_phone_without_private_auth():
    """qidian_com should advertise phone login even when private authApi is absent."""
    from app.services.official_auth.manager import official_auth_manager

    with patch(
        "app.services.official_auth.manager.private_plugin_loader.load",
        return_value={"authApi": None, "cookieAuth": None, "manifest": None, "available": False},
    ):
        caps = official_auth_manager.capabilities("qidian_com")

    assert "phone" in caps["methods"]
    assert "cookie" in caps["methods"]
    assert caps["defaultMethod"] == "phone"
    assert caps["privateFeatures"]["phoneAuth"] is False
    assert caps["hasPrivatePackage"] is False


def test_qidian_fallback_request_code_init_returns_challenge(monkeypatch):
    """Fresh request-code for qidian_com fallback returns a captcha challenge."""
    from app.services.official_auth.manager import official_auth_manager
    from app.services.official_auth.sessions import session_store

    fake_session = _fake_qidian_session(status="captcha")
    monkeypatch.setattr(
        "app.services.official_auth.manager.qidian_login_service.init",
        lambda: fake_session,
    )

    with patch(
        "app.services.official_auth.manager.private_plugin_loader.load",
        return_value={"authApi": None, "cookieAuth": None, "manifest": None, "available": False},
    ):
        result = official_auth_manager.request_phone_code("qidian_com", {"phone": "13800138000"})

    assert result["ok"] is False
    assert result["nextAction"] == "complete_challenge"
    assert result["challenge"]["appId"] == "1600000770"
    assert result["challenge"]["type"] == "tencent_captcha"

    # Official session should be created and hold qidian internal session id
    official_session = session_store.get(result["sessionId"])
    assert official_session is not None
    assert official_session.private_payload["qidian_session_id"] == "qd_123"
    session_store.remove(result["sessionId"])


def test_qidian_fallback_request_code_retry_sends_sms(monkeypatch):
    """Retry with challenge token should call send_sms and return verify_code."""
    from app.services.official_auth.manager import official_auth_manager
    from app.services.official_auth.sessions import session_store

    fake_init = _fake_qidian_session(status="captcha")
    calls = []

    def fake_send_sms(session_id, phone, ticket, randstr):
        calls.append({"session_id": session_id, "phone": phone, "ticket": ticket, "randstr": randstr})
        return _fake_qidian_session(session_id=session_id, status="sms_sent")

    monkeypatch.setattr(
        "app.services.official_auth.manager.qidian_login_service.init",
        lambda: fake_init,
    )
    monkeypatch.setattr(
        "app.services.official_auth.manager.qidian_login_service.send_sms",
        fake_send_sms,
    )

    with patch(
        "app.services.official_auth.manager.private_plugin_loader.load",
        return_value={"authApi": None, "cookieAuth": None, "manifest": None, "available": False},
    ):
        init_result = official_auth_manager.request_phone_code("qidian_com", {"phone": "13800138000"})
        retry_result = official_auth_manager.request_phone_code("qidian_com", {
            "phone": "13800138000",
            "sessionId": init_result["sessionId"],
            "challengeToken": "ticket_123",
            "challengeRandstr": "@rand",
        })

    assert retry_result["ok"] is True
    assert retry_result["nextAction"] == "verify_code"
    assert len(calls) == 1
    assert calls[0]["session_id"] == "qd_123"
    assert calls[0]["ticket"] == "ticket_123"
    assert calls[0]["randstr"] == "@rand"

    session_store.remove(init_result["sessionId"])


def test_qidian_fallback_verify_phone_code_persists_cookies(monkeypatch, tmp_path):
    """Successful qidian fallback verify persists cookies and auth status."""
    from app.services.official_auth.manager import official_auth_manager
    from app.services.official_auth.sessions import session_store
    from app.services.plugin_auth_repository import PluginAuthRepository

    fake_init = _fake_qidian_session(status="captcha")
    fake_submit = _fake_qidian_session(status="success")
    fake_submit.message = "登录成功"

    monkeypatch.setattr(
        "app.services.official_auth.manager.qidian_login_service.init",
        lambda: fake_init,
    )
    monkeypatch.setattr(
        "app.services.official_auth.manager.qidian_login_service.send_sms",
        lambda _sid, _phone, _ticket, _randstr: _fake_qidian_session(status="sms_sent"),
    )
    monkeypatch.setattr(
        "app.services.official_auth.manager.qidian_login_service.submit",
        lambda _sid, _code: fake_submit,
    )

    repo = PluginAuthRepository(tmp_path / "auth.db")
    monkeypatch.setattr(
        "app.services.official_auth.manager.PluginAuthRepository",
        lambda: repo,
    )

    with patch(
        "app.services.official_auth.manager.private_plugin_loader.load",
        return_value={"authApi": None, "cookieAuth": None, "manifest": None, "available": False},
    ):
        init_result = official_auth_manager.request_phone_code("qidian_com", {"phone": "13800138000"})
        sms_result = official_auth_manager.request_phone_code("qidian_com", {
            "phone": "13800138000",
            "sessionId": init_result["sessionId"],
            "challengeToken": "ticket_123",
            "challengeRandstr": "@rand",
        })
        verify_result = official_auth_manager.verify_phone_code("qidian_com", {
            "sessionId": sms_result["sessionId"],
            "phone": "13800138000",
            "code": "123456",
        })

    assert verify_result["ok"] is True
    assert verify_result["authenticated"] is True
    assert verify_result["hasCookies"] is True

    # Verify persistence
    cookies = repo.get_cookies("qidian_com")
    assert "qidian.com" in cookies
    assert cookies["qidian.com"]["ywguid"] == "guid_123"

    status = repo.get_status("qidian_com")
    assert status["authenticated"] is True
    assert status["authStatus"] == "authenticated"
    assert status["accountName"] == "13800138000"
    assert status["hasCookies"] is True

    # Session should be cleaned up
    assert session_store.get(sms_result["sessionId"]) is None


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
