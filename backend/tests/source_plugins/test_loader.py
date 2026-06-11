"""Tests for plugin loader."""

import pytest
from pathlib import Path

from app.source_plugins.loader import PluginLoader
from app.source_plugins.errors import PluginValidationError


def _write_plugin(tmp_path: Path, plugin_id: str, capabilities: list[str], extra_meta: dict | None = None):
    d = tmp_path / plugin_id
    d.mkdir(parents=True, exist_ok=True)
    meta = {
        "contractVersion": "1.0",
        "id": plugin_id,
        "name": f"Test {plugin_id}",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": capabilities,
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "tags": ["html"],
    }
    if extra_meta:
        meta.update(extra_meta)
    import yaml
    (d / "metadata.yaml").write_text(yaml.dump(meta), encoding="utf-8")

    methods = []
    for cap in capabilities:
        if cap == "search":
            methods.append("""    async def search(self, ctx, keyword: str, page: int):
        return []
""")
        elif cap == "detail":
            methods.append("""    async def detail(self, ctx, book_url: str):
        return {}
""")
        elif cap == "toc":
            methods.append("""    async def toc(self, ctx, toc_url: str):
        return []
""")
        elif cap == "chapter":
            methods.append("""    async def chapter(self, ctx, chapter_url: str):
        return {}
""")
        elif cap == "explore":
            methods.append("""    async def explore_groups(self, ctx):
        return []

    async def explore(self, ctx, group_id=None, page: int = 1):
        return []
""")
        elif cap == "auth":
            methods.append("""    async def auth_status(self, ctx):
        return {}
""")

    source_py = f'''class Source:
    id = "{plugin_id}"
    name = "Test {plugin_id}"
    contract_version = "1.0"
'''
    source_py += "\n".join(methods)
    (d / "source.py").write_text(source_py, encoding="utf-8")
    return d


def test_valid_plugin_load(tmp_path):
    _write_plugin(tmp_path, "good_plugin", ["search", "detail"])
    loader = PluginLoader(plugins_dir=tmp_path)
    plugins = loader.load_all()
    assert "good_plugin" in plugins
    assert plugins["good_plugin"].metadata.id == "good_plugin"


def test_missing_metadata_fails(tmp_path):
    d = tmp_path / "bad_plugin"
    d.mkdir()
    (d / "source.py").write_text("class Source:\n    pass\n", encoding="utf-8")
    loader = PluginLoader(plugins_dir=tmp_path)
    plugins = loader.load_all()
    assert "bad_plugin" not in plugins


def test_declared_capability_without_method_fails(tmp_path):
    _write_plugin(tmp_path, "bad_cap", ["search"])
    # overwrite source.py without search method
    (tmp_path / "bad_cap" / "source.py").write_text(
        'class Source:\n    id = "bad_cap"\n', encoding="utf-8"
    )
    loader = PluginLoader(plugins_dir=tmp_path)
    with pytest.raises(PluginValidationError) as exc_info:
        loader.load_all()
    assert "search" in str(exc_info.value)


def test_explore_requires_groups_and_items_methods(tmp_path):
    _write_plugin(tmp_path, "bad_explore", ["explore"], extra_meta={"tags": ["official"]})
    (tmp_path / "bad_explore" / "source.py").write_text(
        'class Source:\n'
        '    id = "bad_explore"\n'
        '    async def explore(self, ctx, group_id=None, page=1):\n'
        '        return []\n',
        encoding="utf-8",
    )
    loader = PluginLoader(plugins_dir=tmp_path)
    with pytest.raises(PluginValidationError) as exc_info:
        loader.load_all()
    assert "explore_groups" in str(exc_info.value)


def test_domain_profile_metadata_is_loaded(tmp_path):
    _write_plugin(
        tmp_path,
        "profiled",
        ["search"],
        extra_meta={
            "domainProfiles": [
                {
                    "id": "mobile",
                    "baseUrl": "https://m.example.com",
                    "domains": ["m.example.com"],
                    "role": "mobile",
                    "fallback": True,
                }
            ],
            "proxy": {"mode": "always", "required": True},
        },
    )
    loader = PluginLoader(plugins_dir=tmp_path)
    plugin = loader.load_all()["profiled"]
    assert plugin.metadata.domain_profiles[0]["id"] == "mobile"
    assert plugin.metadata.proxy["mode"] == "always"


def test_duplicate_plugin_id_fails(tmp_path):
    _write_plugin(tmp_path, "dup", ["search"])
    # Create second directory with same metadata id
    second = tmp_path / "dup2"
    second.mkdir()
    import yaml
    meta = {
        "contractVersion": "1.0",
        "id": "dup",
        "name": "Test dup2",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "tags": ["html"],
    }
    (second / "metadata.yaml").write_text(yaml.dump(meta), encoding="utf-8")
    (second / "source.py").write_text(
        'class Source:\n    id = "dup"\n    async def search(self, ctx, keyword, page):\n        return []\n',
        encoding="utf-8",
    )
    loader = PluginLoader(plugins_dir=tmp_path)
    with pytest.raises(PluginValidationError) as exc_info:
        loader.load_all()
    assert "Duplicate" in str(exc_info.value)






