import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup


sys.path.insert(0, str(Path(__file__).parents[1]))

from source import Source


def test_chapter_stem_accepts_hyphen_and_underscore_pagination():
    source = Source()

    assert source._chapter_stem("/65/28357.html") == "/65/28357"
    assert source._chapter_stem("/65/28357-2.html") == "/65/28357"
    assert source._chapter_stem("/65/28357_3.html") == "/65/28357"


@pytest.mark.asyncio
async def test_chapter_follows_relative_same_chapter_pages_without_looping_back():
    pages = {
        "https://www.sudugu.org/2431/1262356.html": """
            <div class="submenu"><h1>第58章 测试</h1></div>
            <div class="con"><p>第一页正文。</p></div>
            <div class="prenext">
              <a href="/2431/1262355.html">上一章</a>
              <a href="/2431/1262356-2.html">下一页</a>
            </div>
        """,
        "https://www.sudugu.org/2431/1262356-2.html": """
            <div class="con"><p>第二页正文。</p></div>
            <div class="prenext">
              <a href="/2431/1262356.html">上一页</a>
              <a href="/2431/1262356-3.html">下一页</a>
            </div>
        """,
        "https://www.sudugu.org/2431/1262356-3.html": """
            <div class="con"><p>第三页正文。</p></div>
            <div class="prenext"><a href="/2431/1262357.html">下一章</a></div>
        """,
    }

    class FakeHttp:
        def __init__(self):
            self.calls = []

        async def fetch_text(self, url):
            self.calls.append(url)
            return pages[url]

    class FakeContext:
        def __init__(self):
            self.http = FakeHttp()
            self.access = SimpleNamespace(http=self.http)

        @staticmethod
        def _soup(html):
            return BeautifulSoup(html, "html.parser")

        def text(self, html, selector):
            node = self._soup(html).select_one(selector)
            return node.get_text(" ", strip=True) if node else ""

        def html(self, html, selector):
            node = self._soup(html).select_one(selector)
            return str(node) if node else ""

        def select(self, html, selector):
            return self._soup(html).select(selector)

    ctx = FakeContext()
    result = await Source().chapter(ctx, "https://www.sudugu.org/2431/1262356.html")

    assert ctx.http.calls == list(pages)
    assert result["content"] == "第一页正文。\n\n第二页正文。\n\n第三页正文。"
