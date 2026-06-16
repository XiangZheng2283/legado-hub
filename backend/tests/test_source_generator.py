"""Tests for aggregate source generator."""

import json

from app.core.source_generator import (
    generate_aggregate_source,
    write_aggregate_source,
)

REQUIRED_KEYS = [
    "bookSourceName",
    "bookSourceGroup",
    "bookSourceUrl",
    "bookSourceType",
    "enabled",
    "enabledCookieJar",
    "enabledExplore",
    "header",
    "searchUrl",
    "ruleSearch",
    "ruleBookInfo",
    "ruleToc",
    "ruleContent",
    "jsLib",
]


def test_generate_aggregate_source_shape() -> None:
    sources = generate_aggregate_source()
    assert isinstance(sources, list)
    assert len(sources) == 1
    source = sources[0]
    for key in REQUIRED_KEYS:
        assert key in source, f"missing key: {key}"


def test_write_aggregate_source() -> None:
    path = write_aggregate_source()
    assert path.endswith("legadohub-source.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["bookSourceName"] == "LegadoHub 聚合(0.0.1)"


def test_source_calls_local_endpoints() -> None:
    sources = generate_aggregate_source()
    source = sources[0]
    assert "127.0.0.1:8765" in source["searchUrl"]
    assert "waitMs=180000" in source["searchUrl"]
    assert "127.0.0.1:8765" in source["jsLib"]
    assert source["ruleSearch"]["lastChapter"] == "$.readingLastChapter"
    assert "@js:" in source["ruleContent"]["content"]
    assert "<br><br>" in source["ruleContent"]["content"]


def test_source_accepts_lan_base_url() -> None:
    sources = generate_aggregate_source("http://192.168.31.189:8765")
    source = sources[0]
    assert "192.168.31.189:8765" in source["searchUrl"]
    assert "192.168.31.189:8765" in source["jsLib"]


def test_source_comment_mentions_browser_challenge_bypass_policy() -> None:
    source = generate_aggregate_source()[0]

    assert "Cloudflare" in source["bookSourceComment"]
    assert "绕过" in source["bookSourceComment"]
    assert "不再提供手动验证" in source["bookSourceComment"]


def test_source_explore_excludes_ordinary_sources_until_official_sources_exist() -> None:
    source = generate_aggregate_source()[0]

    assert source["enabledExplore"] is False
    assert "69shuba_com" not in source["exploreUrl"]
    assert "聚合推荐" not in source["exploreUrl"]






