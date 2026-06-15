"""Tests for OpenAI-compatible AI provider client."""

import json

import pytest

from app.ai.client import (
    AIProviderNotConfiguredError,
    AIProviderResult,
    OpenAICompatibleClient,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _sample_config(**overrides) -> dict:
    base = {
        "baseUrl": "https://api.deepseek.com/v1",
        "apiKey": "sk-test12345",
        "model": "deepseek-chat",
        "maxOutputTokens": 1024,
        "temperature": 0.3,
        "timeoutMs": 5000,
    }
    base.update(overrides)
    return base


# ── construction ─────────────────────────────────────────────────────────────


def test_client_stores_config():
    config = _sample_config()
    client = OpenAICompatibleClient(config)
    assert client.config is config


# ── validation ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_raises_when_base_url_missing():
    client = OpenAICompatibleClient(_sample_config(baseUrl=""))
    with pytest.raises(AIProviderNotConfiguredError, match="not configured"):
        await client.chat([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_raises_when_api_key_missing():
    client = OpenAICompatibleClient(_sample_config(apiKey=""))
    with pytest.raises(AIProviderNotConfiguredError, match="not configured"):
        await client.chat([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_raises_when_model_missing():
    client = OpenAICompatibleClient(_sample_config(model=""))
    with pytest.raises(AIProviderNotConfiguredError, match="not configured"):
        await client.chat([{"role": "user", "content": "hi"}])


# ── successful chat ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_returns_result_from_mocked_http(httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/chat/completions",
        json={
            "choices": [{"message": {"content": "hello world"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "deepseek-chat",
        },
        status_code=200,
    )
    client = OpenAICompatibleClient(_sample_config())

    result = await client.chat([{"role": "user", "content": "hi"}])

    assert isinstance(result, AIProviderResult)
    assert result.content == "hello world"
    assert result.model == "deepseek-chat"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.total_tokens == 15
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_chat_sends_correct_request_body(httpx_mock):
    captured_requests = []

    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/chat/completions",
        json={"choices": [{"message": {"content": "ok"}}], "usage": {}, "model": "x"},
    )
    client = OpenAICompatibleClient(_sample_config(apiKey="sk-secret123"))
    await client.chat([{"role": "user", "content": "test"}])

    sent = httpx_mock.get_requests()
    assert len(sent) == 1
    req = sent[0]
    assert req.headers["authorization"] == "Bearer sk-secret123"
    body = json.loads(req.content)
    assert body["model"] == "deepseek-chat"


# ── error handling ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chat_raises_on_401(httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/chat/completions",
        status_code=401,
        json={"error": {"message": "Invalid API key"}},
    )
    client = OpenAICompatibleClient(_sample_config())

    with pytest.raises(Exception, match="401|Unauthorized|Invalid"):
        await client.chat([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_raises_on_429_rate_limit(httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/chat/completions",
        status_code=429,
        json={"error": {"message": "Rate limit exceeded"}},
    )
    client = OpenAICompatibleClient(_sample_config())

    with pytest.raises(Exception, match="429|rate|limit"):
        await client.chat([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_raises_on_server_error(httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/chat/completions",
        status_code=500,
        json={"error": {"message": "Internal server error"}},
    )
    client = OpenAICompatibleClient(_sample_config())

    with pytest.raises(Exception, match="500|server|error"):
        await client.chat([{"role": "user", "content": "hi"}])


# ── model list ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_models_returns_model_ids(httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/models",
        json={
            "data": [
                {"id": "deepseek-chat", "object": "model"},
                {"id": "deepseek-reasoner", "object": "model"},
            ]
        },
        status_code=200,
    )
    client = OpenAICompatibleClient(_sample_config())

    models = await client.list_models()

    assert models == ["deepseek-chat", "deepseek-reasoner"]


@pytest.mark.asyncio
async def test_list_models_uses_custom_models_url(httpx_mock):
    httpx_mock.add_response(
        url="https://custom.example.com/my-models",
        json={"data": [{"id": "custom-model"}]},
        status_code=200,
    )
    config = _sample_config(modelsUrl="https://custom.example.com/my-models")
    client = OpenAICompatibleClient(config)

    models = await client.list_models()

    assert models == ["custom-model"]


@pytest.mark.asyncio
async def test_list_models_raises_when_not_configured():
    client = OpenAICompatibleClient(_sample_config(baseUrl=""))
    with pytest.raises(AIProviderNotConfiguredError):
        await client.list_models()


@pytest.mark.asyncio
async def test_list_models_works_without_model_configured(httpx_mock):
    """list_models should only require baseUrl + apiKey, not model."""
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/models",
        json={"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]},
        status_code=200,
    )
    # No model key at all — this is the normal flow before picking a model.
    client = OpenAICompatibleClient({"baseUrl": "https://api.deepseek.com/v1", "apiKey": "sk-test12345"})

    models = await client.list_models()

    assert "deepseek-chat" in models


@pytest.mark.asyncio
async def test_list_models_raises_on_http_error(httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/models",
        status_code=401,
        json={"error": {"message": "Unauthorized"}},
    )
    client = OpenAICompatibleClient(_sample_config())

    with pytest.raises(Exception, match="401|Unauthorized"):
        await client.list_models()


# ── connectivity test ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_test_connectivity_returns_ok_on_success(httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/models",
        json={"data": [{"id": "deepseek-chat"}]},
        status_code=200,
    )
    client = OpenAICompatibleClient(_sample_config())

    result = await client.test_connectivity()

    assert result["ok"] is True
    assert result["status"] == "connected"
    assert result["latencyMs"] >= 0
    assert result["modelCount"] >= 1


@pytest.mark.asyncio
async def test_test_connectivity_returns_error_on_failure(httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepseek.com/v1/models",
        status_code=401,
        json={"error": {"message": "Invalid API key"}},
    )
    client = OpenAICompatibleClient(_sample_config())

    result = await client.test_connectivity()

    assert result["ok"] is False
    assert result["status"] == "auth_error"
    assert "Invalid" in result.get("message", "")


@pytest.mark.asyncio
async def test_test_connectivity_returns_not_configured():
    client = OpenAICompatibleClient(_sample_config(baseUrl=""))

    result = await client.test_connectivity()

    assert result["ok"] is False
    assert result["status"] == "not_configured"
