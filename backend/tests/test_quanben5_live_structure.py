from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.source_plugins.context import PluginContext
from app.source_plugins.smoke import FixtureFetcher


def _load_source():
    path = Path(__file__).resolve().parents[2] / "plugins" / "sources" / "thirdparty" / "quanben5_com" / "source.py"
    spec = importlib.util.spec_from_file_location("test_quanben5_source", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Source()


@pytest.mark.asyncio
async def test_quanben5_uses_read_link_for_toc_and_filters_hot_list() -> None:
    book_url = "https://quanben5.com/n/example/"
    toc_url = f"{book_url}xiaoshuo.html"
    ctx = PluginContext(
        fetcher=FixtureFetcher({
            "https://quanben5.com/": 'search({"id": 0, "content": "<div class=\\"pic_txt_list\\"><h3><a href=\\"/n/hot/\\">热门书</a></h3></div>"});',
            "https://quanben5.com/topallvisit/1.html": "",
            book_url: "<div class='pic_txt_list'><h3><span>示例书</span></h3></div><div class='tool_button'><a class='s1' href='xiaoshuo.html'>点击阅读</a></div>",
            toc_url: "<ul class='list'><li><a href='1.html'>第一章</a></li></ul>",
        }),
        plugin_id="quanben5_com",
    )
    source = _load_source()

    assert source._search_token("凡人")
    assert source._search_result_html('search({"content":"<p>结果</p>"});') == "<p>结果</p>"
    assert await source.search(ctx, "凡人修仙传", 1) == []
    detail = await source.detail(ctx, book_url)
    chapters = await source.toc(ctx, detail["tocUrl"])

    assert detail["tocUrl"] == toc_url
    assert chapters[0]["chapterUrl"] == f"{toc_url.rsplit('/', 1)[0]}/1.html"
