"""AI processing service for aggregate chapter content."""

from __future__ import annotations

import re
from typing import Any

from app.ai.client import AIProviderNotConfiguredError, AIProviderResult


# ── prompt fragments ─────────────────────────────────────────────────────────

_SELF_RATING_INSTRUCTION = (
    "\n\n整理完成后，请在正文最后单独输出一行：<self_rating>0.XX</self_rating>。"
    "0.00 表示完全偏离原文/新增大量无依据内容，1.00 表示完全保留原文语义且仅做格式整理。"
    "不要输出解释。"
)

_SYSTEM_PROMPT_AGGREGATE = (
    "你是一个小说正文整理助手。你的任务是对输入的章节正文进行去广告、纠错、敏感词恢复和格式整理。\n"
    "严格规则：只基于输入正文整理，不新增无依据的剧情、角色、场景或对话。"
    "未在输入正文中出现或无法从上下文确定的内容不得新增。"
    "输出整理后的纯正文，不要输出解释或元信息。"
    f"{_SELF_RATING_INSTRUCTION}"
)

_SYSTEM_PROMPT_ATTRIBUTION = (
    "你是一个小说章节归属校验助手。你需要判断给定的章节正文是否确实属于指定的小说。\n"
    "检查要点：主角名、核心设定、上下文衔接、章节标题、叙事风格、是否混入其他小说正文。\n"
    "严格规则：只基于输入正文判断，不要臆测。"
)


_SELF_RATING_RE = re.compile(r"<self_rating>\s*([0-9]*\.?[0-9]+)\s*</self_rating>", re.IGNORECASE)


def _purify_lightweight(content: str) -> str:
    """Lightweight cleanup: whitespace normalization, blank-line compression."""
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_self_rating(content: str) -> tuple[str, float | None]:
    """Extract AI self-rating tag and return cleaned content + score."""
    match = _SELF_RATING_RE.search(content)
    if not match:
        return content, None
    try:
        score = float(match.group(1))
    except ValueError:
        return content, None
    score = max(0.0, min(1.0, score))
    cleaned = _SELF_RATING_RE.sub("", content).strip()
    return cleaned, score


class AggregateAIService:
    """Orchestrates AI calls for aggregate chapter processing.

    Accepts any object with an async ``chat(messages)`` method as *client*,
    making it easy to test with a fake.

    If *lexicon* is provided (a :class:`SensitiveLexiconScanner`), chapter
    content is scanned for masked blocked-word candidates before each AI
    call.  Candidates are appended to the prompt so the AI can restore
    masked words based on context.
    """

    def __init__(self, client: Any, lexicon: Any = None):
        self._client = client
        self._lexicon = lexicon

    # ── official full content path ────────────────────────────────────────

    async def process_official_full(
        self,
        *,
        book_name: str,
        author: str,
        title: str,
        content: str,
    ) -> dict[str, Any]:
        """Process an official-source chapter that has full content.

        First version: lightweight cleanup only. AI analysis is planned but
        not executed (``plannedAnalysis=True``).
        """
        cleaned = _purify_lightweight(content)
        return {
            "status": "processed",
            "content": cleaned,
            "aiModel": "",
            "promptTokens": 0,
            "completionTokens": 0,
            "totalTokens": 0,
            "latencyMs": 0,
            "plannedAnalysis": True,
        }

    # ── official preview + candidate aggregation ──────────────────────────

    async def process_with_candidates(
        self,
        *,
        book_name: str,
        author: str,
        title: str,
        official_preview: str,
        candidate_content: str,
        alignment: dict[str, Any],
        previous_context: str = "",
    ) -> dict[str, Any]:
        """Aggregate official preview + aligned candidate content via AI.

        Raises on AI failure so the caller can write fallback content.
        """
        user_prompt = (
            f"书名：{book_name}\n"
            f"作者：{author}\n"
            f"章节标题：{title}\n\n"
        )
        if previous_context:
            user_prompt += f"--- 前文参考 ---\n{previous_context}\n\n"
        user_prompt += (
            f"--- 官方预览正文 ---\n{official_preview}\n\n"
            f"--- 候选源正文 ---\n{candidate_content}\n\n"
            "请基于以上内容整理出完整的章节正文。"
            "只保留小说正文，去除广告、站点提示和重复内容。"
            "不新增无依据的剧情，只做格式整理、敏感词恢复和错字修正。"
            f"{_SELF_RATING_INSTRUCTION}"
        )
        blocked = self._scan_blocked_words(official_preview, candidate_content)
        if blocked:
            user_prompt += "\n\n" + blocked

        result, self_score = await self._call_ai(user_prompt)
        return {
            "status": "processed",
            "content": result.content,
            "selfScore": self_score if self_score is not None else 0.0,
            "aiModel": result.model,
            "promptTokens": result.prompt_tokens,
            "completionTokens": result.completion_tokens,
            "totalTokens": result.total_tokens,
            "latencyMs": result.latency_ms,
            "plannedAnalysis": False,
        }

    # ── third-party primary source ────────────────────────────────────────

    async def process_third_party_primary(
        self,
        *,
        book_name: str,
        author: str,
        title: str,
        content: str,
        source_id: str,
        previous_context: str = "",
    ) -> dict[str, Any]:
        """Run attribution check + cleanup on third-party primary content.

        If AI is not configured, returns the original content as fallback
        instead of raising.
        """
        user_prompt = (
            f"书名：{book_name}\n"
            f"作者：{author}\n"
            f"章节标题：{title}\n"
            f"来源：{source_id}\n\n"
        )
        if previous_context:
            user_prompt += f"--- 前文参考 ---\n{previous_context}\n\n"
        user_prompt += (
            f"--- 章节正文 ---\n{content}\n\n"
            "请先判断这段正文是否属于上述小说（检查主角名、设定、叙事连贯性），"
            "然后整理出最终章节正文。"
            "不新增无依据的剧情，只做格式整理、敏感词恢复和错字修正。"
            f"{_SELF_RATING_INSTRUCTION}"
        )
        blocked = self._scan_blocked_words(content)
        if blocked:
            user_prompt += "\n\n" + blocked

        try:
            result, self_score = await self._call_ai(user_prompt)
            return {
                "status": "processed",
                "content": result.content,
                "selfScore": self_score if self_score is not None else 0.0,
                "aiModel": result.model,
                "promptTokens": result.prompt_tokens,
                "completionTokens": result.completion_tokens,
                "totalTokens": result.total_tokens,
                "latencyMs": result.latency_ms,
                "plannedAnalysis": False,
            }
        except AIProviderNotConfiguredError as exc:
            return {
                "status": "fallback",
                "content": content,
                "selfScore": 0.0,
                "aiModel": "",
                "promptTokens": 0,
                "completionTokens": 0,
                "totalTokens": 0,
                "latencyMs": 0,
                "plannedAnalysis": False,
                "error": str(exc),
            }

    # ── internal ──────────────────────────────────────────────────────────

    def _scan_blocked_words(self, *texts: str) -> str:
        """Scan texts for masked blocked words; return prompt fragment or empty."""
        if not self._lexicon:
            return ""
        candidates = []
        for text in texts:
            if text:
                candidates.extend(self._lexicon.scan(text))
        if not candidates:
            return ""
        lines = ["以下是正文中疑似被屏蔽符号遮盖的敏感词候选，请结合上下文语义判断并恢复（仅在有充分依据时恢复，否则保留原文）："]
        for c in candidates[:20]:  # Cap at 20 to keep prompt manageable.
            lines.append(
                f"- 位置 {c.offset}：「{c.masked_text}」→ 候选 {c.candidates} "
                f"(前文：{c.context_before}…，后文：…{c.context_after})"
            )
        return "\n".join(lines)

    async def _call_ai(self, user_prompt: str) -> tuple[AIProviderResult, float | None]:
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT_AGGREGATE},
            {"role": "user", "content": user_prompt},
        ]
        result = await self._client.chat(messages)
        cleaned_content, self_score = _extract_self_rating(result.content)
        cleaned_result = AIProviderResult(
            content=cleaned_content,
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            latency_ms=result.latency_ms,
        )
        return cleaned_result, self_score
