"""Tests for validate_source_plugin.py."""

from pathlib import Path

from scripts.create_source_plugin import create_plugin
from scripts.validate_source_plugin import validate_plugin


def _make_valid_plugin(tmp_path: Path) -> Path:
    plugin_dir = create_plugin(
        plugin_id="example_com",
        name="示例书源",
        domain="example.com",
        base_url="https://example.com",
        output_root=tmp_path,
    )
    fixture_dir = plugin_dir / "tests" / "fixtures"
    for name in ("search.html", "detail.html", "toc.html", "chapter.html"):
        (fixture_dir / name).write_text("<html><body>ok</body></html>", encoding="utf-8")
    return plugin_dir


def test_validate_source_plugin_accepts_scaffold(tmp_path):
    plugin_dir = _make_valid_plugin(tmp_path)

    errors = validate_plugin(plugin_dir)

    assert errors == []


def test_validate_source_plugin_rejects_forbidden_runtime(tmp_path):
    plugin_dir = _make_valid_plugin(tmp_path)
    source_path = plugin_dir / "source.py"
    source_path.write_text(source_path.read_text(encoding="utf-8") + "\n# requests.get\n", encoding="utf-8")

    errors = validate_plugin(plugin_dir)

    assert any("requests." in error for error in errors)


def test_validate_source_plugin_rejects_missing_fixture(tmp_path):
    plugin_dir = _make_valid_plugin(tmp_path)
    (plugin_dir / "tests" / "fixtures" / "chapter.html").unlink()

    errors = validate_plugin(plugin_dir)

    assert any("chapter.html" in error for error in errors)
