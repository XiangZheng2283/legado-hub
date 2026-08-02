import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup


SOURCE_PATH = Path(__file__).parents[1] / "source.py"
SPEC = importlib.util.spec_from_file_location("test_sudugu_org_source", SOURCE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
Source = MODULE.Source


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


@pytest.mark.asyncio
async def test_backup_search_parses_sudugu_co_results():
    html = """
        <div class="bookbox"><div class="bookinfo">
          <h4 class="bookname"><a href="https://www.sudugu.co/191/">凡人修仙传</a></h4>
          <div class="author">作者：忘语</div>
          <div class="cat"><a>第2487章 新书</a></div>
          <div class="update">简介：一个普通山村小子。</div>
        </div></div>
    """

    class FakeHttp:
        async def fetch_text(self, url, **kwargs):
            assert url == "https://www.sudugu.co/modules/article/search.php"
            assert kwargs["params"] == {"searchkey": "凡人"}
            return html

    class Context:
        access = SimpleNamespace(http=FakeHttp())

        @staticmethod
        def _soup(value):
            return value if hasattr(value, "select") else BeautifulSoup(value, "html.parser")

        def select(self, value, selector):
            return self._soup(value).select(selector)

        def text(self, value, selector):
            node = self._soup(value).select_one(selector)
            return node.get_text(" ", strip=True) if node else ""

        @staticmethod
        def clean_text(value):
            return " ".join(str(value).split())

        @staticmethod
        def trace(*args, **kwargs):
            pass

    result = await Source()._search_backup(Context(), "凡人", 1)

    assert result == [{
        "sourceId": "sudugu_org",
        "name": "凡人修仙传",
        "author": "忘语",
        "bookUrl": "https://www.sudugu.co/191/",
        "intro": "一个普通山村小子。",
        "lastChapter": "第2487章 新书",
    }]
