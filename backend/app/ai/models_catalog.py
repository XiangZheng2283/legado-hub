"""Built-in model metadata catalog for aggregate AI settings.

Entries are used to auto-fill contextWindow / maxTokens / thinkingLevelMap
when the user selects a model.  Unknown models still work — they just get
empty metadata and the system falls back to user-configured values.

Source: models.dev + provider official docs + manual verification.
Last updated: 2026-06-14.
"""

from __future__ import annotations

from typing import Any

_DEEPSEEK_COMPAT = {"thinkingFormat": "deepseek", "maxTokensField": "max_tokens"}
_OPENAI_COMPAT = {"thinkingFormat": "openai", "maxTokensField": "max_tokens"}
_OPENROUTER_COMPAT = {"thinkingFormat": "openrouter", "maxTokensField": "max_tokens"}
_QWEN_COMPAT = {"thinkingFormat": "qwen", "maxTokensField": "max_tokens"}

_REASONING_LEVELS = {
    "off": None,
    "minimal": "low",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
}

MODEL_CATALOG: dict[str, dict[str, Any]] = {
    # ── DeepSeek ────────────────────────────────────────────────────────
    "deepseek-chat": {
        "contextWindow": 65536, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _DEEPSEEK_COMPAT,
    },
    "deepseek-reasoner": {
        "contextWindow": 65536, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _DEEPSEEK_COMPAT,
    },
    "deepseek-v3": {
        "contextWindow": 163840, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _DEEPSEEK_COMPAT,
    },
    "deepseek-r1": {
        "contextWindow": 128000, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _DEEPSEEK_COMPAT,
    },
    "deepseek-v3.2": {
        "contextWindow": 163840, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _DEEPSEEK_COMPAT,
    },
    "deepseek-v4-pro": {
        "contextWindow": 163840, "maxTokens": 16384, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _DEEPSEEK_COMPAT,
    },
    "deepseek-v4-flash": {
        "contextWindow": 163840, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _DEEPSEEK_COMPAT,
    },
    "deepseek-coder": {
        "contextWindow": 128000, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _DEEPSEEK_COMPAT,
    },
    # ── OpenAI ──────────────────────────────────────────────────────────
    "gpt-4o": {
        "contextWindow": 128000, "maxTokens": 16384, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _OPENAI_COMPAT,
    },
    "gpt-4o-mini": {
        "contextWindow": 128000, "maxTokens": 16384, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _OPENAI_COMPAT,
    },
    "gpt-4-turbo": {
        "contextWindow": 128000, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _OPENAI_COMPAT,
    },
    "gpt-4.1": {
        "contextWindow": 1000000, "maxTokens": 32768, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _OPENAI_COMPAT,
    },
    "gpt-4.1-mini": {
        "contextWindow": 1000000, "maxTokens": 32768, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _OPENAI_COMPAT,
    },
    "gpt-4.1-nano": {
        "contextWindow": 1000000, "maxTokens": 32768, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _OPENAI_COMPAT,
    },
    "o3": {
        "contextWindow": 200000, "maxTokens": 100000, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {**_OPENAI_COMPAT, "supportsReasoningEffort": True},
    },
    "o3-mini": {
        "contextWindow": 200000, "maxTokens": 100000, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {**_OPENAI_COMPAT, "supportsReasoningEffort": True},
    },
    "o4-mini": {
        "contextWindow": 200000, "maxTokens": 100000, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {**_OPENAI_COMPAT, "supportsReasoningEffort": True},
    },
    "chatgpt-4o-latest": {
        "contextWindow": 128000, "maxTokens": 16384, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _OPENAI_COMPAT,
    },
    "gpt-3.5-turbo": {
        "contextWindow": 16385, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _OPENAI_COMPAT,
    },
    # ── Anthropic ───────────────────────────────────────────────────────
    "claude-3-5-sonnet-20241022": {
        "contextWindow": 200000, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"thinkingFormat": "openai", "maxTokensField": "max_tokens"},
    },
    "claude-3-5-haiku-20241022": {
        "contextWindow": 200000, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"thinkingFormat": "openai", "maxTokensField": "max_tokens"},
    },
    "claude-3-7-sonnet-20250219": {
        "contextWindow": 200000, "maxTokens": 64000, "reasoning": True,
        "thinkingLevelMap": {"off": None, "medium": "medium", "high": "high", "xhigh": "xhigh"},
        "compat": {"thinkingFormat": "openai", "maxTokensField": "max_tokens"},
    },
    "claude-3-opus-20240229": {
        "contextWindow": 200000, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"thinkingFormat": "openai", "maxTokensField": "max_tokens"},
    },
    "claude-opus-4-6": {
        "contextWindow": 1000000, "maxTokens": 32000, "reasoning": True,
        "thinkingLevelMap": {"off": None, "high": "high", "xhigh": "xhigh"},
        "compat": {"thinkingFormat": "openai", "maxTokensField": "max_tokens"},
    },
    "claude-opus-4-7": {
        "contextWindow": 1000000, "maxTokens": 128000, "reasoning": True,
        "thinkingLevelMap": {"off": None, "xhigh": "xhigh"},
        "compat": {"thinkingFormat": "openai", "maxTokensField": "max_tokens"},
    },
    "claude-opus-4-8": {
        "contextWindow": 1000000, "maxTokens": 128000, "reasoning": True,
        "thinkingLevelMap": {"off": None, "xhigh": "xhigh"},
        "compat": {"thinkingFormat": "openai", "maxTokensField": "max_tokens"},
    },
    "claude-sonnet-4-6": {
        "contextWindow": 1000000, "maxTokens": 64000, "reasoning": True,
        "thinkingLevelMap": {"off": None, "medium": "medium", "high": "high"},
        "compat": {"thinkingFormat": "openai", "maxTokensField": "max_tokens"},
    },
    # ── Moonshot / Kimi ─────────────────────────────────────────────────
    "moonshot-v1-8k": {
        "contextWindow": 8192, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "moonshot-v1-32k": {
        "contextWindow": 32768, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "moonshot-v1-128k": {
        "contextWindow": 131072, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "moonshot-v1-8k-vision-preview": {
        "contextWindow": 8192, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "moonshot-v1-32k-vision-preview": {
        "contextWindow": 32768, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "moonshot-v1-128k-vision-preview": {
        "contextWindow": 131072, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "kimi-k2": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "kimi-k2-0711-preview": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "kimi-k2-instruct": {
        "contextWindow": 262144, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "kimi-k2-instruct-0905": {
        "contextWindow": 262144, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "kimi-k2-turbo": {
        "contextWindow": 262144, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "kimi-k2-thinking": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    "kimi-k2-thinking-turbo": {
        "contextWindow": 262144, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    "kimi-k2.5": {
        "contextWindow": 262144, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    "kimi-k2.6": {
        "contextWindow": 262144, "maxTokens": 16384, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    "kimi-linear": {
        "contextWindow": 131072, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    # ── Qwen / 通义千问 ─────────────────────────────────────────────────
    "qwen-max": {
        "contextWindow": 32768, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _QWEN_COMPAT,
    },
    "qwen-plus": {
        "contextWindow": 1000000, "maxTokens": 32768, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _QWEN_COMPAT,
    },
    "qwen-plus-latest": {
        "contextWindow": 1000000, "maxTokens": 32768, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _QWEN_COMPAT,
    },
    "qwen3.5-plus": {
        "contextWindow": 1000000, "maxTokens": 65536, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _QWEN_COMPAT,
    },
    "qwen-turbo": {
        "contextWindow": 1000000, "maxTokens": 16384, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _QWEN_COMPAT,
    },
    "qwen-flash": {
        "contextWindow": 1000000, "maxTokens": 16384, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _QWEN_COMPAT,
    },
    "qwen-long": {
        "contextWindow": 10000000, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _QWEN_COMPAT,
    },
    "qwen3-max": {
        "contextWindow": 262144, "maxTokens": 16384, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _QWEN_COMPAT,
    },
    "qwen3-235b-a22b": {
        "contextWindow": 262144, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _QWEN_COMPAT,
    },
    "qwen3-235b-a22b-thinking-2507": {
        "contextWindow": 262144, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _QWEN_COMPAT,
    },
    "qwen3-coder": {
        "contextWindow": 262144, "maxTokens": 16384, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _QWEN_COMPAT,
    },
    "qwen3-coder-flash": {
        "contextWindow": 1000000, "maxTokens": 16384, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _QWEN_COMPAT,
    },
    "qwen-vl-plus": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _QWEN_COMPAT,
    },
    "qwen-vl-max": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _QWEN_COMPAT,
    },
    "qwen-mt-plus": {
        "contextWindow": 16384, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _QWEN_COMPAT,
    },
    # ── GLM / 智谱 ─────────────────────────────────────────────────────
    "glm-4": {
        "contextWindow": 131072, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "glm-4-plus": {
        "contextWindow": 131072, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "glm-4-long": {
        "contextWindow": 1000000, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "glm-4-flash": {
        "contextWindow": 131072, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "glm-4-air": {
        "contextWindow": 131072, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "glm-4-air-250414": {
        "contextWindow": 131072, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "glm-4.5": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    "glm-4.6": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    "glm-4.6V": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "glm-4.7": {
        "contextWindow": 204800, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    "glm-5": {
        "contextWindow": 202752, "maxTokens": 16384, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    "glm-5-turbo": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    "glm-z1-flash": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    "glm-z1-32b-0414": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    # ── MiniMax ─────────────────────────────────────────────────────────
    "minimax-m2": {
        "contextWindow": 204608, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "minimax-m2.5": {
        "contextWindow": 196608, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "abab7-chat": {
        "contextWindow": 256000, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    # ── Mistral ─────────────────────────────────────────────────────────
    "mistral-large-3": {
        "contextWindow": 256000, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "mistral-small-3": {
        "contextWindow": 32768, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "codestral": {
        "contextWindow": 256000, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "pixtral-large": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    # ── 百川 ────────────────────────────────────────────────────────────
    "Baichuan4": {
        "contextWindow": 32768, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "Baichuan4-Turbo": {
        "contextWindow": 32768, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    # ── 讯飞星火 ────────────────────────────────────────────────────────
    "generalv3.5": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "4.0Ultra": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "max-32k": {
        "contextWindow": 32768, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    # ── 豆包 ────────────────────────────────────────────────────────────
    "doubao-1.5-pro-32k": {
        "contextWindow": 32768, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "doubao-1.5-pro-128k": {
        "contextWindow": 131072, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "doubao-1.5-lite-32k": {
        "contextWindow": 32768, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "doubao-pro-256k": {
        "contextWindow": 262144, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "deepseek-v3-250324": {
        "contextWindow": 131072, "maxTokens": 16384, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _DEEPSEEK_COMPAT,
    },
    "deepseek-r1-250120": {
        "contextWindow": 65536, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _DEEPSEEK_COMPAT,
    },
    # ── 零一万物 Yi ─────────────────────────────────────────────────────
    "yi-large": {
        "contextWindow": 32768, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "yi-large-turbo": {
        "contextWindow": 32768, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "yi-medium": {
        "contextWindow": 16384, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "yi-spark": {
        "contextWindow": 16384, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    # ── 阶跃星辰 Step ──────────────────────────────────────────────────
    "step-1-8k": {
        "contextWindow": 8192, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "step-1-32k": {
        "contextWindow": 32768, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "step-1-128k": {
        "contextWindow": 131072, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "step-2-16k": {
        "contextWindow": 16384, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    # ── 腾讯混元 ───────────────────────────────────────────────────────
    "hunyuan-turbos-latest": {
        "contextWindow": 32768, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "hunyuan-t1-latest": {
        "contextWindow": 32768, "maxTokens": 4096, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    "hunyuan-pro": {
        "contextWindow": 32768, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "hunyuan-standard": {
        "contextWindow": 32768, "maxTokens": 2048, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    # ── 昆仑万维 天工 ──────────────────────────────────────────────────
    "SkyChat-Mega": {
        "contextWindow": 32768, "maxTokens": 4096, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "SkyChat-Mega-2": {
        "contextWindow": 32768, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    # ── 商汤日日新 ──────────────────────────────────────────────────────
    "SenseChat-5": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "SenseChat-5-Cantonese": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    # ── 小米 MiMo ──────────────────────────────────────────────────────
    "MiMo-V2-Flash": {
        "contextWindow": 262144, "maxTokens": 16384, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    "MiMo-V2.5": {
        "contextWindow": 262144, "maxTokens": 16384, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "MiMo-V2.5-Pro": {
        "contextWindow": 1000000, "maxTokens": 32768, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    "MiMo-7B-RL": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    "MiMo-7B-SFT": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "MiMo-VL-7B-RL-2508": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    "MiMo-MoE-A3B": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": {"maxTokensField": "max_tokens"},
    },
    # ── SiliconFlow / OpenRouter 兼容 ───────────────────────────────────
    "Pro/deepseek-ai/DeepSeek-V3": {
        "contextWindow": 64000, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _DEEPSEEK_COMPAT,
    },
    "Pro/deepseek-ai/DeepSeek-R1": {
        "contextWindow": 64000, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _DEEPSEEK_COMPAT,
    },
    "deepseek-ai/DeepSeek-V3": {
        "contextWindow": 64000, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _DEEPSEEK_COMPAT,
    },
    "deepseek-ai/DeepSeek-R1": {
        "contextWindow": 64000, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _DEEPSEEK_COMPAT,
    },
    "Qwen/Qwen3-235B-A22B": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _QWEN_COMPAT,
    },
    # ── Groq ────────────────────────────────────────────────────────────
    "llama-3.3-70b-versatile": {
        "contextWindow": 131072, "maxTokens": 32768, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "llama-3.1-8b-instant": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "gemma2-9b-it": {
        "contextWindow": 8192, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "mixtral-8x7b-32768": {
        "contextWindow": 32768, "maxTokens": 32768, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    # ── Together ────────────────────────────────────────────────────────
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": {
        "contextWindow": 131072, "maxTokens": 32768, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo": {
        "contextWindow": 131072, "maxTokens": 16384, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "Qwen/Qwen2.5-72B-Instruct-Turbo": {
        "contextWindow": 32768, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _QWEN_COMPAT,
    },
    # ── NVIDIA ──────────────────────────────────────────────────────────
    "meta/llama-3.3-70b-instruct": {
        "contextWindow": 131072, "maxTokens": 32768, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "deepseek-ai/deepseek-r1": {
        "contextWindow": 65536, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _DEEPSEEK_COMPAT,
    },
    "qwen/qwen2.5-72b-instruct": {
        "contextWindow": 32768, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _QWEN_COMPAT,
    },
    # ── Ollama / LM Studio (本地模型常用名) ────────────────────────────
    "llama3.1": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "llama3.2": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "qwen2.5": {
        "contextWindow": 32768, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": _QWEN_COMPAT,
    },
    "qwen3": {
        "contextWindow": 32768, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _QWEN_COMPAT,
    },
    "deepseek-r1:7b": {
        "contextWindow": 32768, "maxTokens": 8192, "reasoning": True,
        "thinkingLevelMap": _REASONING_LEVELS,
        "compat": _DEEPSEEK_COMPAT,
    },
    "phi-4": {
        "contextWindow": 16384, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
    "gemma3": {
        "contextWindow": 131072, "maxTokens": 8192, "reasoning": False,
        "thinkingLevelMap": {"off": None},
        "compat": {"maxTokensField": "max_tokens"},
    },
}


def model_metadata(model: str) -> dict[str, Any]:
    """Return metadata for a known model, or empty dict for unknown models."""
    return dict(MODEL_CATALOG.get(model, {}))
