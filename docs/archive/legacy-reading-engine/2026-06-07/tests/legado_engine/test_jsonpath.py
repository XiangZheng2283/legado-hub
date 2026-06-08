"""Tests for JsonPath extraction."""

from app.legado_engine.jsonpath import extract_jsonpath, extract_jsonpath_text


def test_jsonpath_simple_key():
    data = {"name": "Test", "author": "A"}
    assert extract_jsonpath(data, "$.name") == ["Test"]


def test_jsonpath_nested():
    data = {"data": {"title": "Nested"}}
    assert extract_jsonpath(data, "$.data.title") == ["Nested"]


def test_jsonpath_array_all():
    data = {"items": [{"name": "A"}, {"name": "B"}]}
    result = extract_jsonpath(data, "$.items.*")
    assert len(result) == 2


def test_jsonpath_array_index():
    data = {"items": [{"name": "A"}, {"name": "B"}]}
    assert extract_jsonpath(data, "$.items.1.name") == ["B"]


def test_jsonpath_text():
    data = {"count": 42}
    assert extract_jsonpath_text(data, "$.count") == "42"
