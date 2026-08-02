import base64
import importlib.util
from pathlib import Path

import pytest
from lxml import html as lxml_html


SOURCE_PATH = Path(__file__).parents[1] / "source.py"
SPEC = importlib.util.spec_from_file_location("test_0xs_net_source", SOURCE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
Source = MODULE.Source


@pytest.mark.asyncio
async def test_chapter_uses_catalog_referer_and_merges_encoded_pages(monkeypatch):
    encoded = base64.b64encode("<p>第二段正文。</p>".encode()).decode()
    pages = {
        "https://www.0xs.net/txt_1/30/1.html": f"""
            <h1>第一章 山边小村(1/2)</h1>
            <div class="content">
              <p>【凡人修仙传】小说免费阅读，请收藏 零点小说【0xs.net】</p>
              <p>第一段正文。</p><p>本章未完，点击[下一页]继续阅读-->></p>
              <p id="prompt">内容无法显示时请更换浏览器。</p>
            </div>
            <script>const p_key='{encoded}'</script>
            <div class="page"><a href="/txt_1/30/1/2.html">下一页</a></div>
        """,
        "https://www.0xs.net/txt_1/30/1/2.html": """
            <div class="content"><p>第三段正文。</p></div>
            <div class="page"><a href="/txt_1/30/2.html">下一章</a></div>
        """,
    }
    calls = []
    source = Source()

    async def fake_fetch(ctx, url, **kwargs):
        calls.append((url, kwargs))
        return pages[url]

    monkeypatch.setattr(source, "_fetch", fake_fetch)

    class Context:
        def text(self, value, selector):
            nodes = self.select(value, selector)
            return " ".join(nodes[0].text_content().split()) if nodes else ""

        def html(self, value, selector):
            nodes = self.select(value, selector)
            return lxml_html.tostring(nodes[0], encoding="unicode") if nodes else ""

        def select(self, value, selector):
            root = value if hasattr(value, "cssselect") else lxml_html.fromstring(value)
            return root.cssselect(selector)

        @staticmethod
        def clean_text(value):
            return " ".join(str(value).split())

    result = await source.chapter(Context(), "https://www.0xs.net/txt_1/30/1.html")

    assert calls[0][1]["headers"]["Referer"] == "https://www.0xs.net/la_1/30.html"
    assert calls[1][1]["headers"]["Referer"] == calls[0][0]
    assert result["title"] == "第一章 山边小村"
    assert result["content"] == "第一段正文。\n\n第二段正文。\n\n第三段正文。"


@pytest.mark.asyncio
async def test_chapter_keeps_continuation_marker_when_pagination_cycles(monkeypatch):
    source = Source()

    async def fake_fetch(ctx, url, **kwargs):
        return """
            <h1>第一章</h1>
            <div class="content"><p>第一段正文。</p><p>（本章未完，请点击下一页继续阅读）</p></div>
            <div class="page"><a href="/txt_1/30/1.html">下一页</a></div>
        """

    monkeypatch.setattr(source, "_fetch", fake_fetch)

    class Context:
        def text(self, value, selector):
            nodes = self.select(value, selector)
            return " ".join(nodes[0].text_content().split()) if nodes else ""

        def html(self, value, selector):
            nodes = self.select(value, selector)
            return lxml_html.tostring(nodes[0], encoding="unicode") if nodes else ""

        def select(self, value, selector):
            root = value if hasattr(value, "cssselect") else lxml_html.fromstring(value)
            return root.cssselect(selector)

        @staticmethod
        def clean_text(value):
            return " ".join(str(value).split())

    result = await source.chapter(Context(), "https://www.0xs.net/txt_1/30/1.html")

    assert "本章未完" in result["content"]
