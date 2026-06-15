"""Build OpenAI-compatible chat completion requests."""

from __future__ import annotations

from typing import Any

from app.ai.compat import infer_compat
from app.ai.models_catalog import model_metadata

THINKING_LEVEL_ORDER = ["off", "minimal", "low", "medium", "high", "xhigh"]


def _mapped_thinking_level(model: str, level: str) -> str | None:
    metadata = model_metadata(model)
    if not metadata.get("reasoning"):
        return None
    level_map = metadata.get("thinkingLevelMap") or {}
    if level in level_map:
        return level_map[level]
    try:
        index = THINKING_LEVEL_ORDER.index(level)
    except ValueError:
        index = THINKING_LEVEL_ORDER.index("medium")
    for fallback in reversed(THINKING_LEVEL_ORDER[: index + 1]):
        if fallback in level_map:
            return level_map[fallback]
    return None


def build_chat_completion_request(
    *,
    config: dict[str, Any],
    messages: list[dict[str, str]],
    stream: bool = False,
) -> dict[str, Any]:
    model = str(config.get("model") or "")
    compat = infer_compat(config)
    max_tokens_field = compat.get("maxTokensField") or "max_tokens"
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": config.get("temperature", 0.3),
        "top_p": config.get("topP", 1.0),
        max_tokens_field: int(config.get("maxOutputTokens") or 8192),
        "stream": stream,
    }
    custom = config.get("customBodyParams")
    if isinstance(custom, dict):
        body.update(custom)

    thinking_level = str(config.get("thinkingLevel") or "off")
    mapped_level = _mapped_thinking_level(model, thinking_level)
    if mapped_level:
        thinking_format = compat.get("thinkingFormat")
        if compat.get("supportsReasoningEffort") or thinking_format == "openai":
            body["reasoning_effort"] = mapped_level
        elif thinking_format == "deepseek":
            body["thinking"] = {"type": "enabled"}
            body["reasoning_effort"] = mapped_level
        elif thinking_format == "openrouter":
            body["reasoning"] = {"effort": mapped_level}
        elif thinking_format == "qwen":
            body["enable_thinking"] = True
        else:
            body["thinking"] = mapped_level
    elif compat.get("thinkingFormat") == "deepseek":
        body["thinking"] = {"type": "disabled"}

    if stream and compat.get("supportsUsageInStreaming"):
        body["stream_options"] = {"include_usage": True}
    return body
