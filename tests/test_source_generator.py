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
    assert "127.0.0.1:8765" in source["jsLib"]


def test_source_accepts_lan_base_url() -> None:
    sources = generate_aggregate_source("http://192.168.31.189:8765")
    source = sources[0]
    assert "192.168.31.189:8765" in source["searchUrl"]
    assert "192.168.31.189:8765" in source["jsLib"]
