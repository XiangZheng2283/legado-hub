"""Tests for Qidian official source auth_status intermediate states."""

import json
import sys
from pathlib import Path

import pytest

# Ensure project root is on path so `plugins.*` imports work
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.source_plugins.context import PluginContext
from app.source_plugins.fetcher import Fetcher
from plugins.sources.official.qidian_com.source import Source as QidianSource


def _make_ctx(cookies: dict):
    return PluginContext(fetcher=Fetcher(), plugin_id="qidian_com", auth_repository=None)


class _FakeFetcher:
    def __init__(self, html: str):
        self._html = html

    async def fetch_text(self, url, **kwargs):
        return self._html

    def set_cookie(self, domain, name, value):
        pass


@pytest.mark.asyncio
async def test_auth_status_missing_critical_cookie_returns_not_logged_in():
    source = QidianSource()
    ctx = _make_ctx({})
    ctx._fetcher = _FakeFetcher("")
    # Only set incomplete cookies
    ctx.cookies.set("qidian.com", {"ywguid": "123"})

    result = await source.auth_status(ctx)

    assert result["authenticated"] is False
    assert result["authStatus"] == "unknown"
    assert "ywkey" in result["message"]


@pytest.mark.asyncio
async def test_auth_status_with_cookies_but_no_user_identity_returns_pending():
    """Critical cookies exist, page returns pageContext but no nick/userId -> pending."""
    source = QidianSource()
    ctx = _make_ctx({})
    ctx._fetcher = _FakeFetcher(
        f'<html><script id="vite-plugin-ssr_pageContext" type="application/json">{json.dumps({"pageContext": {"pageProps": {"pageData": {"userInfo": {}}}}})}</script></html>'
    )
    ctx.cookies.set("qidian.com", {"ywguid": "123", "ywkey": "abc", "_csrfToken": "tok"})

    result = await source.auth_status(ctx)

    assert result["authenticated"] is False
    assert result["authStatus"] == "pending"
    assert result["requiredActions"] == ["check_auth_status"]
    assert result["hasCookies"] is True


@pytest.mark.asyncio
async def test_auth_status_with_nickname_returns_authenticated():
    source = QidianSource()
    ctx = _make_ctx({})
    ctx._fetcher = _FakeFetcher(
        f'<html><script id="vite-plugin-ssr_pageContext" type="application/json">{json.dumps({"pageContext": {"pageProps": {"pageData": {"user": {"isLogin": True, "nickName": "TestUser", "guid": 12345}}}}})}</script></html>'
    )
    ctx.cookies.set("qidian.com", {"ywguid": "123", "ywkey": "abc"})

    result = await source.auth_status(ctx)

    assert result["authenticated"] is True
    assert result["authStatus"] == "authenticated"
    assert result["accountName"] == "TestUser"


@pytest.mark.asyncio
async def test_auth_status_page_probe_failure_with_cookies_returns_pending():
    source = QidianSource()
    ctx = _make_ctx({})

    class FailingFetcher:
        async def fetch_text(self, url, **kwargs):
            raise RuntimeError("network error")

        def set_cookie(self, domain, name, value):
            pass

    ctx._fetcher = FailingFetcher()
    ctx.cookies.set("qidian.com", {"ywguid": "123", "ywkey": "abc"})

    result = await source.auth_status(ctx)

    assert result["authenticated"] is False
    assert result["authStatus"] == "pending"
    assert result["requiredActions"] == ["check_auth_status"]
