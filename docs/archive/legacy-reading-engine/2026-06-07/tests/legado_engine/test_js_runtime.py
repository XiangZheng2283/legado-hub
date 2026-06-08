"""Tests for restricted JS runtime."""

from app.legado_engine.js_runtime import classify_js_rule, apply_safe_js_transform


def test_classify_js_safe():
    can_emulate, reason = classify_js_rule("result.trim()")
    assert can_emulate is True


def test_classify_js_unsafe_ajax():
    can_emulate, reason = classify_js_rule("java.ajax(url)")
    assert can_emulate is False
    assert "ajax" in reason


def test_apply_trim():
    result = apply_safe_js_transform("  hello  ", "result.trim()")
    assert result == "hello"


def test_apply_replace():
    result = apply_safe_js_transform("hello world", "result.replace(/world/, 'earth')")
    assert result == "hello earth"
