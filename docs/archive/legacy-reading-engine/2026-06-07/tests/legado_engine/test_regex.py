"""Tests for Regex extraction."""

from app.legado_engine.regex import extract_regex, extract_regex_all


def test_extract_regex_single():
    text = "Name: Alice, Age: 30"
    result = extract_regex(text, r"Name: (\w+)")
    assert result == "Alice"


def test_extract_regex_group0():
    text = "abc123def"
    result = extract_regex(text, r"(\d+)", group=0)
    assert result == "123"


def test_extract_regex_all():
    text = "a1b2c3"
    results = extract_regex_all(text, r"(\d)")
    assert results == ["1", "2", "3"]
