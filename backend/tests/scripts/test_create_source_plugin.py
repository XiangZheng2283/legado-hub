"""Tests for create_source_plugin.py."""

from pathlib import Path

import pytest
import yaml

from scripts.create_source_plugin import create_plugin, validate_plugin_id


def test_create_source_plugin_writes_required_files(tmp_path):
    plugin_dir = create_plugin(
        plugin_id="example_com",
        name="示例书源",
        domain="example.com",
        base_url="https://example.com",
        output_root=tmp_path,
    )

    assert plugin_dir == tmp_path / "example_com"
    assert (plugin_dir / "metadata.yaml").exists()
    assert (plugin_dir / "source.py").exists()
    assert (plugin_dir / "README.md").exists()
    assert (plugin_dir / "tests" / "smoke.yaml").exists()
    assert (plugin_dir / "tests" / "fixtures" / "search.html").exists()
    metadata = yaml.safe_load((plugin_dir / "metadata.yaml").read_text(encoding="utf-8"))
    assert metadata["id"] == "example_com"
    assert metadata["name"] == "示例书源"
    assert metadata["domains"] == ["example.com"]
    assert metadata["baseUrls"] == ["https://example.com"]
    assert 'id = "example_com"' in (plugin_dir / "source.py").read_text(encoding="utf-8")


def test_create_source_plugin_refuses_bad_ids(tmp_path):
    with pytest.raises(ValueError):
        validate_plugin_id("DemoSite")
    with pytest.raises(ValueError):
        validate_plugin_id("demo_site")


def test_create_source_plugin_refuses_overwrite_without_force(tmp_path):
    create_plugin(
        plugin_id="example_com",
        name="示例书源",
        domain="example.com",
        base_url="https://example.com",
        output_root=tmp_path,
    )

    with pytest.raises(FileExistsError):
        create_plugin(
            plugin_id="example_com",
            name="示例书源",
            domain="example.com",
            base_url="https://example.com",
            output_root=tmp_path,
        )
