"""Tests for AggregateAIService — AI processing skeleton."""

import json
import pytest

from app.services.aggregate_ai_service import AggregateAIService


# ── fake client ──────────────────────────────────────────────────────────────


class FakeAIClient:
    """Minimal fake that returns canned responses."""

    def __init__(
        self,
        content: str = "AI 整理后的正文",
        *,
        fail: bool = False,
        error: Exception | None = None,
        self_score: float | None = None,
    ):
        self._content = content
        self._fail = fail
        self._error = error
        self._self_score = self_score
        self.calls: list[list[dict]] = []

    async def chat(self, messages):
        self.calls.append(messages)
        if self._fail:
            raise self._error or RuntimeError("AI provider failed")
        content = self._content
        if self._self_score is not None:
            content = f"{content}\n<self_rating>{self._self_score}</self_rating>"
        from app.ai.client import AIProviderResult
        return AIProviderResult(
            content=content,
            model="fake-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=200,
        )


class UnconfiguredClient:
    """Simulates a client where provider is not configured."""

    async def chat(self, messages):
        from app.ai.client import AIProviderNotConfiguredError
        raise AIProviderNotConfiguredError("AI provider is not configured")


# ── process_official_full ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_official_full_does_not_call_ai():
    """Official full content should be cleaned without calling AI."""
    client = FakeAIClient()
    service = AggregateAIService(client=client)

    content = "这是一段完整的官方正文内容。" * 50
    result = await service.process_official_full(
        book_name="测试书",
        author="作者",
        title="第一章",
        content=content,
    )

    assert result["status"] == "processed"
    assert len(result["content"]) > 0
    assert result["plannedAnalysis"] is True
    assert len(client.calls) == 0  # AI not called


@pytest.mark.asyncio
async def test_process_official_full_cleans_content():
    client = FakeAIClient()
    service = AggregateAIService(client=client)

    content = "正文\n\n\n\n\n多余空行  \n"
    result = await service.process_official_full(
        book_name="测试书", author="作者", title="第一章", content=content,
    )

    assert "\n\n\n" not in result["content"]


# ── process_with_candidates ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_with_candidates_calls_ai():
    """Official preview + aligned candidate should invoke AI for aggregation."""
    client = FakeAIClient(content="AI 聚合后的完整正文")
    service = AggregateAIService(client=client)

    result = await service.process_with_candidates(
        book_name="测试书",
        author="作者",
        title="第一章 风起",
        official_preview="少年站在山巅望着远方。",
        candidate_content="少年站在山巅望着远方的云海。后续正文内容很多。" * 10,
        alignment={"alignmentPassed": True, "previewSimilarity": 0.92},
    )

    assert result["status"] == "processed"
    assert result["content"] == "AI 聚合后的完整正文"
    assert result["aiModel"] == "fake-model"
    assert result["promptTokens"] == 100
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_process_with_candidates_ai_failure_raises():
    """AI failure should raise so the processor can write fallback."""
    from app.ai.client import AIProviderHTTPError
    client = FakeAIClient(fail=True, error=AIProviderHTTPError(500, "server error"))
    service = AggregateAIService(client=client)

    with pytest.raises(AIProviderHTTPError):
        await service.process_with_candidates(
            book_name="测试书", author="作者", title="第一章",
            official_preview="preview text here for testing purposes that is long enough.",
            candidate_content="candidate text " * 20,
            alignment={"alignmentPassed": True},
        )


# ── process_third_party_primary ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_third_party_primary_calls_ai_for_attribution():
    """Third-party primary source should call AI for attribution check."""
    client = FakeAIClient(content="归属校验通过，整理后的正文")
    service = AggregateAIService(client=client)

    result = await service.process_third_party_primary(
        book_name="测试书",
        author="作者",
        title="第一章",
        content="第三方源的正文内容。" * 20,
        source_id="example_com",
    )

    assert result["status"] == "processed"
    assert len(client.calls) == 1
    # The prompt should mention attribution.
    prompt_text = json.dumps(client.calls[0], ensure_ascii=False)
    assert "归属" in prompt_text or "belongs" in prompt_text.lower() or "属于" in prompt_text


@pytest.mark.asyncio
async def test_process_third_party_primary_unconfigured_returns_fallbackable():
    """When provider is not configured, should return a result the processor
    can use to write fallback content."""
    client = UnconfiguredClient()
    service = AggregateAIService(client=client)

    content = "第三方源的原始正文内容。" * 20
    result = await service.process_third_party_primary(
        book_name="测试书", author="作者", title="第一章",
        content=content, source_id="example_com",
    )

    assert result["status"] == "fallback"
    assert result["content"] == content  # original content returned as fallback
    assert result["error"] != ""


# ── prompt safety ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ai_prompt_forbids_fabrication():
    """Prompts must contain explicit instruction not to fabricate content."""
    client = FakeAIClient()
    service = AggregateAIService(client=client)

    await service.process_with_candidates(
        book_name="测试书", author="作者", title="第一章",
        official_preview="这是一段预览正文用于测试目的。",
        candidate_content="候选源正文 " * 20,
        alignment={"alignmentPassed": True},
    )

    all_text = json.dumps(client.calls, ensure_ascii=False)
    assert "不新增" in all_text or "不得新增" in all_text or "不要凭空" in all_text or "不凭空" in all_text


@pytest.mark.asyncio
async def test_lexicon_candidates_appended_to_prompt():
    """When lexicon finds masked words, candidates should be appended to prompt."""
    from app.ai.lexicon import SensitiveLexiconScanner

    lexicon = SensitiveLexiconScanner.from_word_list(["杀意"])
    client = FakeAIClient()
    service = AggregateAIService(client=client, lexicon=lexicon)

    # Content contains a masked blocked word.
    preview = "少年站在山巅，望着远方的云海，心中涌起一股莫名的悸动。他知道这一切才刚刚开始，未来路还很长。"
    candidate = "他眼中闪过一丝杀*意，手中长剑出鞘，剑光如虹划破长空。" * 5

    await service.process_with_candidates(
        book_name="测试书", author="作者", title="第一章",
        official_preview=preview,
        candidate_content=candidate,
        alignment={"alignmentPassed": True},
    )

    prompt_text = json.dumps(client.calls, ensure_ascii=False)
    assert "疑似被屏蔽" in prompt_text or "敏感词候选" in prompt_text
    assert "杀" in prompt_text


@pytest.mark.asyncio
async def test_no_lexicon_no_blocked_word_section():
    """Without lexicon, prompt should not contain blocked word section."""
    client = FakeAIClient()
    service = AggregateAIService(client=client, lexicon=None)

    await service.process_with_candidates(
        book_name="测试书", author="作者", title="第一章",
        official_preview="这是一段预览正文用于测试目的。",
        candidate_content="候选源正文 " * 20,
        alignment={"alignmentPassed": True},
    )

    prompt_text = json.dumps(client.calls, ensure_ascii=False)
    assert "疑似被屏蔽" not in prompt_text


@pytest.mark.asyncio
async def test_previous_context_included_in_prompt():
    """When previous_context is provided, it should appear in the AI prompt."""
    client = FakeAIClient()
    service = AggregateAIService(client=client)

    await service.process_with_candidates(
        book_name="测试书", author="作者", title="第二章",
        official_preview="第二章的预览正文内容。",
        candidate_content="候选源正文 " * 20,
        alignment={"alignmentPassed": True},
        previous_context="【第一章】前文参考内容，主角已经到达山巅。",
    )

    prompt_text = json.dumps(client.calls, ensure_ascii=False)
    assert "前文参考" in prompt_text
    assert "前文参考内容" in prompt_text


@pytest.mark.asyncio
async def test_self_rating_instruction_in_prompt():
    """Prompts must ask the model to output a self-rating tag."""
    client = FakeAIClient()
    service = AggregateAIService(client=client)

    await service.process_with_candidates(
        book_name="测试书", author="作者", title="第一章",
        official_preview="这是一段预览正文用于测试目的。",
        candidate_content="候选源正文 " * 20,
        alignment={"alignmentPassed": True},
    )

    all_text = json.dumps(client.calls, ensure_ascii=False)
    assert "<self_rating>" in all_text
    assert "0.XX" in all_text


@pytest.mark.asyncio
async def test_self_rating_extracted_and_content_cleaned():
    """If the model returns a self-rating tag, it should be parsed and removed."""
    client = FakeAIClient(content="整理后的正文", self_score=0.95)
    service = AggregateAIService(client=client)

    result = await service.process_with_candidates(
        book_name="测试书", author="作者", title="第一章",
        official_preview="这是一段预览正文用于测试目的。",
        candidate_content="候选源正文 " * 20,
        alignment={"alignmentPassed": True},
    )

    assert result["content"] == "整理后的正文"
    assert result["selfScore"] == 0.95


@pytest.mark.asyncio
async def test_self_rating_defaults_to_zero_when_missing():
    """If the model omits the self-rating tag, selfScore should default to 0.0."""
    client = FakeAIClient(content="整理后的正文")
    service = AggregateAIService(client=client)

    result = await service.process_with_candidates(
        book_name="测试书", author="作者", title="第一章",
        official_preview="这是一段预览正文用于测试目的。",
        candidate_content="候选源正文 " * 20,
        alignment={"alignmentPassed": True},
    )

    assert result["content"] == "整理后的正文"
    assert result["selfScore"] == 0.0


@pytest.mark.asyncio
async def test_third_party_primary_returns_self_score():
    client = FakeAIClient(content="归属校验后的正文", self_score=0.88)
    service = AggregateAIService(client=client)

    result = await service.process_third_party_primary(
        book_name="测试书", author="作者", title="第一章",
        content="第三方源正文 " * 20, source_id="example_com",
    )

    assert result["content"] == "归属校验后的正文"
    assert result["selfScore"] == 0.88
