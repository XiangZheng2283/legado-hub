from pathlib import Path

from app.source_plugins.smoke import _fixture_map


def test_fixture_map_loads_extra_pages(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "smoke" / "fixtures"
    fixtures_dir.mkdir(parents=True)
    for name in ("search.html", "detail.html", "toc.html", "chapter.html", "chapter-2.html"):
        (fixtures_dir / name).write_text(name, encoding="utf-8")
    spec = {
        "fixtures": {
            "search": {"url": "https://example.test/search", "file": "search.html"},
            "detail": {"url": "https://example.test/book", "file": "detail.html"},
            "toc": {"url": "https://example.test/toc", "file": "toc.html"},
            "chapter": {"url": "https://example.test/chapter", "file": "chapter.html"},
        },
        "extraFixtures": [
            {"url": "https://example.test/chapter_2", "file": "chapter-2.html"},
        ],
    }

    fixture_map = _fixture_map(tmp_path, spec)

    assert fixture_map["https://example.test/chapter_2"] == "chapter-2.html"
