"""Tests for AI provider request contract."""

from app.ai.compat import infer_compat
from app.ai.request_builder import build_chat_completion_request


def test_deepseek_reasoner_request_enables_thinking():
    config = {
        "baseUrl": "https://api.deepseek.com/v1",
        "model": "deepseek-reasoner",
        "maxOutputTokens": 4096,
        "temperature": 0.2,
        "topP": 0.9,
        "thinkingLevel": "medium",
    }

    body = build_chat_completion_request(
        config=config,
        messages=[{"role": "user", "content": "整理这一章"}],
    )

    assert body["model"] == "deepseek-reasoner"
    assert body["max_tokens"] == 4096
    assert body["thinking"] == {"type": "enabled"}
    assert body["reasoning_effort"] == "medium"


def test_openrouter_compat_supports_usage_in_streaming():
    compat = infer_compat({"baseUrl": "https://openrouter.ai/api/v1", "model": "gpt-4o"})

    assert compat["thinkingFormat"] == "openrouter"
    assert compat["supportsUsageInStreaming"] is True
