"""Tests for plugin runtime context helpers."""

import pytest

from app.services.browser_bridge.models import BrowserFetchRequest, BrowserFetchResult
from app.services.plugin_auth_repository import PluginAuthRepository
from app.source_plugins.context import PluginContext
from app.source_plugins.fetcher import Fetcher


SAMPLE_HTML = """
<html><body>
<div class="result-item">
  <a href="/book/1">凡人修仙传</a>
  <span class="author">忘语</span>
</div>
<div class="result-item">
  <a href="/book/2">仙逆</a>
  <span class="author">耳根</span>
</div>
</body></html>
"""


@pytest.fixture
def ctx():
    return PluginContext(fetcher=Fetcher(), plugin_id="test")


def test_select(ctx):
    nodes = ctx.select(SAMPLE_HTML, ".result-item")
    assert len(nodes) == 2


def test_text_with_selector(ctx):
    text = ctx.text(SAMPLE_HTML, ".result-item a")
    assert text == "凡人修仙传"


def test_text_without_selector(ctx):
    text = ctx.text("<div>  hello   world  </div>", None)
    assert "hello" in text
    assert "world" in text


def test_attr(ctx):
    href = ctx.attr(SAMPLE_HTML, ".result-item a", "href")
    assert href == "/book/1"


def test_urljoin(ctx):
    assert ctx.urljoin("https://example.com", "/book/1") == "https://example.com/book/1"


def test_clean_html(ctx):
    raw = "<div><script>alert(1)</script><p>第一段正文</p><p>第二段正文</p></div>"
    cleaned = ctx.clean_html(raw)
    assert "script" not in cleaned.lower()
    assert "<p>" not in cleaned
    assert "第一段正文" in cleaned
    assert "第二段正文" in cleaned
    assert "\n\n" in cleaned


def test_clean_text(ctx):
    assert ctx.clean_text("  a   b  ") == "a b"


def test_json_path(ctx):
    data = {"items": [{"name": "book1"}, {"name": "book2"}]}
    assert ctx.json_path(data, "items.0.name") == "book1"
    assert ctx.json_path(data, "missing") is None


def test_regex(ctx):
    assert ctx.regex("abc123def", r"\d+") == "123"
    assert ctx.regex("abc", r"\d+") == ""
    assert ctx.regex("abc123def", r"(\d+)", group=1) == "123"


def test_trace(ctx):
    ctx.trace("search", url="https://example.com", message="ok")
    traces = ctx.get_traces()
    assert len(traces) == 1
    assert traces[0]["stage"] == "search"


class FakeBrowserBridge:
    def __init__(self):
        self.requests: list[BrowserFetchRequest] = []

    async def fetch(self, request: BrowserFetchRequest) -> BrowserFetchResult:
        self.requests.append(request)
        return BrowserFetchResult(
            ok=True,
            final_url=request.url,
            html="<html><body>browser ok</body></html>",
            cookies=[{"domain": "example.com", "name": "sid", "value": "1"}],
            profile_id=request.profile_id,
        )


@pytest.mark.asyncio
async def test_context_browser_fetch_text_persists_cookies(tmp_path):
    bridge = FakeBrowserBridge()
    repo = PluginAuthRepository(tmp_path / "auth.db")
    ctx = PluginContext(
        fetcher=Fetcher(),
        plugin_id="example",
        auth_repository=repo,
        browser_bridge=bridge,
    )

    text = await ctx.browser.fetch_text(
        "https://example.com/book/1.htm",
        stage="detail",
        profile_id="example-default",
    )

    assert "browser ok" in text
    assert bridge.requests[0].plugin_id == "example"
    assert bridge.requests[0].stage == "detail"
    assert repo.get_cookies("example")["example.com"]["sid"] == "1"
    assert ctx.get_traces()[-1]["stage"] == "browser_bridge"
