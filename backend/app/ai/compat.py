"""Compatibility inference for OpenAI-compatible chat endpoints."""

from __future__ import annotations

from typing import Any

from app.ai.models_catalog import model_metadata

DEFAULT_COMPAT: dict[str, Any] = {
    "maxTokensField": "max_tokens",
    "thinkingFormat": "openai",
    "supportsDeveloperRole": False,
    "supportsReasoningEffort": False,
    "supportsUsageInStreaming": False,
    "requiresReasoningContentOnAssistantMessages": False,
    "requiresThinkingAsText": False,
    "supportsStrictMode": False,
}


def infer_compat(config: dict[str, Any]) -> dict[str, Any]:
    base_url = str(config.get("baseUrl") or "").lower()
    model = str(config.get("model") or "")
    compat = dict(DEFAULT_COMPAT)
    compat.update(model_metadata(model).get("compat") or {})

    if "deepseek" in base_url or model.startswith("deepseek-"):
        compat.update(
            {
                "thinkingFormat": "deepseek",
                "maxTokensField": "max_tokens",
                "requiresReasoningContentOnAssistantMessages": model == "deepseek-reasoner",
            }
        )
    elif "openrouter" in base_url:
        compat.update({"thinkingFormat": "openrouter", "supportsUsageInStreaming": True})
    elif "api.openai.com" in base_url:
        compat.update({"thinkingFormat": "openai", "supportsReasoningEffort": model.startswith(("o", "gpt-5"))})

    overrides = config.get("compatOverrides")
    if isinstance(overrides, dict):
        compat.update(overrides)
    return compat
