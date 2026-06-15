"""OpenAI-compatible client boundary for aggregate AI processing."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.ai.request_builder import build_chat_completion_request


@dataclass(slots=True)
class AIProviderResult:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0


class AIProviderNotConfiguredError(RuntimeError):
    """Raised when a provider request is attempted without enough config."""


class AIProviderHTTPError(RuntimeError):
    """Raised when the provider returns a non-success HTTP status."""

    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        super().__init__(message or f"AI provider returned HTTP {status_code}")


def _base_url(config: dict[str, Any]) -> str:
    return str(config.get("baseUrl") or "").rstrip("/")


def _api_key(config: dict[str, Any]) -> str:
    return str(config.get("apiKey") or "")


def _model(config: dict[str, Any]) -> str:
    return str(config.get("model") or "")


def _timeout(config: dict[str, Any]) -> float:
    ms = int(config.get("timeoutMs") or 120_000)
    return max(ms / 1000.0, 5.0)


def _require_config(config: dict[str, Any]) -> None:
    if not _base_url(config) or not _api_key(config) or not _model(config):
        raise AIProviderNotConfiguredError("AI provider is not configured")


def _require_auth_config(config: dict[str, Any]) -> None:
    """Only require baseUrl + apiKey (used by list_models before model is chosen)."""
    if not _base_url(config) or not _api_key(config):
        raise AIProviderNotConfiguredError("AI provider is not configured")


def _auth_headers(config: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    key = _api_key(config)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    custom = config.get("customHeaders")
    if isinstance(custom, dict):
        headers.update(custom)
    return headers


class OpenAICompatibleClient:
    """Async OpenAI-compatible chat client using httpx."""

    def __init__(self, config: dict[str, Any]):
        self.config = config

    # ── chat completion ──────────────────────────────────────────────────

    async def chat(self, messages: list[dict[str, str]]) -> AIProviderResult:
        _require_config(self.config)
        url = f"{_base_url(self.config)}/chat/completions"
        body = build_chat_completion_request(
            config=self.config,
            messages=messages,
            stream=False,
        )
        headers = _auth_headers(self.config)
        timeout = _timeout(self.config)

        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if resp.status_code != 200:
            error_body = resp.text[:500]
            raise AIProviderHTTPError(resp.status_code, error_body)

        data = resp.json()
        choices = data.get("choices") or []
        content = ""
        if choices:
            message = choices[0].get("message") or {}
            content = str(message.get("content") or "")

        usage = data.get("usage") or {}
        return AIProviderResult(
            content=content,
            model=str(data.get("model") or _model(self.config)),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            latency_ms=elapsed_ms,
        )

    # ── model list ───────────────────────────────────────────────────────

    async def list_models(self) -> list[str]:
        _require_auth_config(self.config)
        url = str(self.config.get("modelsUrl") or "").strip()
        if not url:
            url = f"{_base_url(self.config)}/models"
        headers = _auth_headers(self.config)
        timeout = _timeout(self.config)

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code != 200:
            error_body = resp.text[:500]
            raise AIProviderHTTPError(resp.status_code, error_body)

        data = resp.json()
        models = data.get("data") or []
        return sorted(
            str(m.get("id") or "")
            for m in models
            if isinstance(m, dict) and m.get("id")
        )

    # ── connectivity test ────────────────────────────────────────────────

    async def test_connectivity(self) -> dict[str, Any]:
        if not _base_url(self.config) or not _api_key(self.config):
            return {"ok": False, "status": "not_configured", "message": "baseUrl and apiKey are required"}

        try:
            t0 = time.monotonic()
            models = await self.list_models()
            latency = int((time.monotonic() - t0) * 1000)
            return {
                "ok": True,
                "status": "connected",
                "latencyMs": latency,
                "modelCount": len(models),
                "sampleModels": models[:5],
            }
        except AIProviderHTTPError as exc:
            code = exc.status_code
            if code == 401:
                status = "auth_error"
            elif code == 429:
                status = "rate_limited"
            elif code >= 500:
                status = "server_error"
            else:
                status = "http_error"
            return {"ok": False, "status": status, "statusCode": code, "message": str(exc)}
        except Exception as exc:
            return {"ok": False, "status": "network_error", "message": str(exc)}
