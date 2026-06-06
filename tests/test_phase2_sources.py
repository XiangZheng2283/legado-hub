"""Tests for Phase 2 source pool configuration."""

from pathlib import Path

from app.services.source_pool import SourcePool


def test_source_pool_loads_20_sources() -> None:
    pool = SourcePool()
    config = pool.get_config()
    sources = config.get("sources", [])
    assert len(sources) == 20


def test_enabled_sources_have_required_fields() -> None:
    pool = SourcePool()
    pool.load()
    for sid, source in pool.get_enabled_sources():
        assert source.get("sourceName")
        assert source.get("sourceUrl")
        assert source.get("searchUrl")
        assert source.get("ruleSearch")
        assert source.get("ruleBookInfo")
        assert source.get("ruleToc")
        assert source.get("ruleContent")


def test_all_source_files_exist() -> None:
    pool = SourcePool()
    config = pool.get_config()
    for entry in config["sources"]:
        assert Path(entry["path"]).exists(), f"missing: {entry['path']}"
