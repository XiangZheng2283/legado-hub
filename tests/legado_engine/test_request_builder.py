"""Tests for Legado request builder."""

import pytest
from app.legado_engine.request_builder import parse_header_config, parse_request_spec, build_search_request, merge_headers
from app.legado_engine.models import RuleContext


def test_parse_simple_url():
    spec = parse_request_spec("https://example.com/search?q=test")
    assert spec.url == "https://example.com/search?q=test"
    assert spec.method == "GET"
    assert spec.charset == "utf-8"


def test_parse_json_spec():
    spec = parse_request_spec('{"url":"https://example.com/api","method":"POST","body":"key=1","charset":"gbk"}')
    assert spec.url == "https://example.com/api"
    assert spec.method == "POST"
    assert spec.body == "key=1"
    assert spec.charset == "gbk"


def test_parse_comma_spec():
    spec = parse_request_spec('https://example.com/api,{"method":"POST","headers":{"X":"1"}}')
    assert spec.url == "https://example.com/api"
    assert spec.method == "POST"
    assert spec.headers == {"X": "1"}


def test_build_search_request():
    spec = build_search_request("https://example.com/search?key={{key}}&page={{page}}", "凡人修仙传", 1)
    assert "%E5%87%A1%E4%BA%BA%E4%BF%AE%E4%BB%99%E4%BC%A0" in spec.url
    assert "page=1" in spec.url


def test_build_search_request_with_context():
    ctx = RuleContext(variables={"category": "xianxia"})
    spec = build_search_request("https://example.com/{{category}}?p={{page}}", "", 2, context=ctx)
    assert "xianxia" in spec.url
    assert "p=2" in spec.url


def test_parse_source_header_json_and_lines():
    assert parse_header_config('{"Referer":"https://example.com","X-Test":"1"}') == {
        "Referer": "https://example.com",
        "X-Test": "1",
    }
    assert parse_header_config("Referer=https://example.com\nX-Test: 1") == {
        "Referer": "https://example.com",
        "X-Test": "1",
    }


def test_merge_headers_request_overrides_source_and_replaces_context():
    ctx = RuleContext(variables={"token": "abc"})
    merged = merge_headers(
        {"Referer": "https://source.example", "Authorization": "Bearer {{token}}"},
        {"Referer": "https://request.example"},
        ctx,
    )
    assert merged["Referer"] == "https://request.example"
    assert merged["Authorization"] == "Bearer abc"


def test_build_search_request_replaces_body_variables():
    spec = build_search_request(
        '{"url":"https://example.com/api","method":"POST","body":"key={{key}}&page={{page}}"}',
        "凡人",
        3,
    )
    assert spec.method == "POST"
    assert "key=%E5%87%A1%E4%BA%BA" in spec.body
    assert "page=3" in spec.body
