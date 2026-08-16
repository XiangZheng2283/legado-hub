from __future__ import annotations

import textwrap
from pathlib import Path

from app.source_plugins.loader import PluginLoader

META = textwrap.dedent(
    """\
    contractVersion: "1.0"
    id: {pid}
    name: {pid}
    author: t
    version: 0.1.0
    type: source
    domains:
      - example.com
    baseUrls:
      - https://example.com
    capabilities:
      - search
    enabled: true
    """
)

GOOD_SRC = textwrap.dedent(
    """\
    async def search(self, ctx, keyword, page):
        return []
    class Source:
        pass
    Source.search = search
    """
)

BAD_SRC = 'x = rf"a{b or r\'c\'}"\n'


def test_bad_plugin_does_not_abort_the_whole_fleet(tmp_path: Path) -> None:
    good = tmp_path / "goodsrc"
    bad = tmp_path / "badsrc"
    good.mkdir()
    bad.mkdir()
    (good / "metadata.yaml").write_text(META.format(pid="goodsrc"), encoding="utf-8")
    (good / "source.py").write_text(GOOD_SRC, encoding="utf-8")
    (bad / "metadata.yaml").write_text(META.format(pid="badsrc"), encoding="utf-8")
    (bad / "source.py").write_text(BAD_SRC, encoding="utf-8")

    loader = PluginLoader(plugins_dir=tmp_path)
    plugins = loader.load_all()  # must NOT raise

    assert "goodsrc" in plugins, "a good plugin must still load"
    assert "badsrc" not in plugins
    assert any("badsrc" in error for error in loader.errors), "broken plugin collected in errors"
