"""Chapter content classification and cross-source alignment for aggregate processing."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any


# ── thresholds (plan §7.4) ───────────────────────────────────────────────────

TITLE_SIMILARITY_THRESHOLD = 0.80
PREVIEW_SIMILARITY_THRESHOLD = 0.70
PREVIEW_HIGH_CONFIDENCE = 0.88
PREVIEW_MIN_LENGTH = 40
PREVIEW_PREFERRED_MIN = 80
PREVIEW_PREFERRED_MAX = 200
CANDIDATE_WINDOW_SIZE = 1000
FULL_CONTENT_MIN_LENGTH = 200
HEAD_PREVIEW_SIMILARITY_THRESHOLD = 0.35
RELAXED_PREVIEW_SIMILARITY_THRESHOLD = 0.50
RELAXED_HEAD_PREVIEW_SIMILARITY_THRESHOLD = 0.50


# ── helpers ──────────────────────────────────────────────────────────────────


def _normalize_for_compare(text: str) -> str:
    """Strip whitespace, punctuation and line breaks for fuzzy comparison."""
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"""[，。！？、；："'（）《》【】\.,!\?;:\(\)<>\[\]]""", "", text)
    return text


def _title_similarity(a: str, b: str) -> float:
    """Character-level similarity between two chapter titles."""
    na = _normalize_chapter_title(a)
    nb = _normalize_chapter_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb, autojunk=False).ratio()


def _sequence_similarity(a: str, b: str) -> float:
    """Character-level LCS-based similarity (code similarity)."""
    na = _normalize_for_compare(a)
    nb = _normalize_for_compare(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb, autojunk=False).ratio()


_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def _parse_chinese_number(token: str) -> int | None:
    token = str(token or "").strip()
    if not token:
        return None
    if token.isdigit():
        return int(token)
    total = 0
    section = 0
    number = 0
    seen = False
    for char in token:
        if char in _CHINESE_DIGITS:
            number = _CHINESE_DIGITS[char]
            seen = True
            continue
        unit = _CHINESE_UNITS.get(char)
        if unit is None:
            return None
        seen = True
        if unit == 10000:
            section = (section + (number or 0)) * unit
            total += section
            section = 0
        else:
            section += (number or 1) * unit
        number = 0
    if not seen:
        return None
    return total + section + number


def _normalize_chapter_title(text: str) -> str:
    text = str(text or "")

    def replace_ordinal(match: re.Match[str]) -> str:
        number = _parse_chinese_number(match.group(1))
        return str(number) if number is not None else match.group(1)

    text = re.sub(r"第([零〇一二两三四五六七八九十百千万\d]+)([章节回卷篇部集])", replace_ordinal, text)
    text = text.replace("正文", "")
    return _normalize_for_compare(text)


def chapter_title_similarity(expected_title: str, candidate_title: str) -> float:
    return _title_similarity(expected_title, candidate_title)


def _candidate_body_head(candidate_title: str, candidate_content: str) -> str:
    stripped = str(candidate_content or "").strip()
    if not stripped:
        return stripped
    lines = stripped.splitlines()
    if not lines:
        return stripped
    if _title_similarity(candidate_title, lines[0]) >= 0.95:
        return "\n".join(lines[1:]).strip()
    return stripped


def _sliding_preview_similarity(preview: str, candidate_content: str) -> float:
    """Sliding window match: find where *preview* best matches inside *candidate_content*.

    Searches the first ``CANDIDATE_WINDOW_SIZE`` characters of candidate_content.
    Returns the best similarity score found.
    """
    norm_preview = _normalize_for_compare(preview)
    if not norm_preview:
        return 0.0

    search_text = _normalize_for_compare(candidate_content[:CANDIDATE_WINDOW_SIZE])
    if not search_text:
        return 0.0

    # If candidate is shorter than preview, just compare directly.
    if len(search_text) <= len(norm_preview):
        return _sequence_similarity(norm_preview, search_text)

    best = 0.0
    step = max(1, len(norm_preview) // 4)
    for i in range(0, len(search_text) - len(norm_preview) + 1, step):
        window = search_text[i : i + len(norm_preview)]
        sim = SequenceMatcher(None, norm_preview, window, autojunk=False).ratio()
        if sim > best:
            best = sim
            if best >= 1.0:
                break
    # Also check the last window position.
    if len(search_text) > len(norm_preview):
        window = search_text[-len(norm_preview):]
        sim = SequenceMatcher(None, norm_preview, window, autojunk=False).ratio()
        best = max(best, sim)
    return best


# ── classification ───────────────────────────────────────────────────────────


def classify_source_content(
    content: str | None,
    source_id: str = "",
    is_official: bool = False,
    *,
    source_word_count: int = 0,
    preview_only_hint: bool = False,
    extra: dict[str, Any] | None = None,
    is_paid: bool = False,
    is_vip: bool = False,
) -> dict[str, Any]:
    """Classify fetched chapter content as ``full`` / ``preview`` / ``empty``.

    基于 is_vip + previewOnly 判断，而非硬编码字数阈值。
    Returns a dict with keys: classification, contentLength, previewText,
    isOfficial, reason.
    """
    if not content or not content.strip():
        return {
            "classification": "empty",
            "contentLength": 0,
            "previewText": "",
            "isOfficial": is_official,
            "sourceId": source_id,
            "reason": "no_content",
        }

    stripped = content.strip()
    length = len(stripped)
    preview_text = stripped[:PREVIEW_PREFERRED_MAX]
    extra = extra if isinstance(extra, dict) else {}

    explicit_preview = bool(preview_only_hint)
    for key in ("previewOnly", "isPreview", "preview_only", "isLocked"):
        if key in extra:
            explicit_preview = explicit_preview or bool(extra.get(key))
    if is_paid:
        explicit_preview = True

    try:
        source_word_count = int(source_word_count or 0)
    except (TypeError, ValueError):
        source_word_count = 0

    # 1. 显式预览信号 → preview
    if explicit_preview:
        return {
            "classification": "preview",
            "contentLength": length,
            "previewText": preview_text,
            "isOfficial": is_official,
            "sourceId": source_id,
            "reason": "explicit_preview_signal",
            "sourceWordCount": source_word_count,
        }

    # 2. VIP 章且未付费 → preview（官方 VIP 预览）
    if is_vip and not is_paid:
        return {
            "classification": "preview",
            "contentLength": length,
            "previewText": preview_text,
            "isOfficial": is_official,
            "sourceId": source_id,
            "reason": "vip_chapter_not_paid",
            "sourceWordCount": source_word_count,
        }

    # 3. 内容明显短于官方字数 → preview
    if source_word_count > 0 and length > 0 and length + 80 < source_word_count:
        return {
            "classification": "preview",
            "contentLength": length,
            "previewText": preview_text,
            "isOfficial": is_official,
            "sourceId": source_id,
            "reason": "visible_content_shorter_than_source_word_count",
            "sourceWordCount": source_word_count,
        }

    # 4. 极短内容且无任何元数据 → preview（安全网，<40 字几乎不可能是完整章节）
    if length < PREVIEW_MIN_LENGTH and not source_word_count:
        return {
            "classification": "preview",
            "contentLength": length,
            "previewText": preview_text,
            "isOfficial": is_official,
            "sourceId": source_id,
            "reason": "content_too_short_no_metadata",
            "sourceWordCount": source_word_count,
        }

    # 5. 有内容 → full（免费章、已付费 VIP、第三方补全的完整正文）
    return {
        "classification": "full",
        "contentLength": length,
        "previewText": preview_text,
        "isOfficial": is_official,
        "sourceId": source_id,
        "reason": "content_present",
        "sourceWordCount": source_word_count,
    }


# ── alignment ────────────────────────────────────────────────────────────────


def align_candidate_chapter(
    *,
    official_preview: str,
    candidate_title: str,
    candidate_content: str,
    expected_title: str,
) -> dict[str, Any]:
    """Check whether a candidate chapter matches the official preview.

    Uses title similarity + sliding-window preview similarity per plan §7.4.

    Returns a dict with: alignmentPassed, titleSimilarity, previewSimilarity,
    alignmentReason.
    """
    if not official_preview or len(official_preview.strip()) < PREVIEW_MIN_LENGTH:
        return {
            "alignmentPassed": False,
            "titleSimilarity": 0.0,
            "previewSimilarity": 0.0,
            "headPreviewSimilarity": 0.0,
            "alignmentReason": "no_preview_available",
        }

    title_sim = _title_similarity(expected_title, candidate_title)
    preview_sim = _sliding_preview_similarity(official_preview, candidate_content)
    head_sim = _sequence_similarity(
        official_preview[:PREVIEW_PREFERRED_MAX],
        _candidate_body_head(candidate_title, candidate_content)[:PREVIEW_PREFERRED_MAX],
    )

    # High-confidence preview bypasses title check.
    if preview_sim >= PREVIEW_HIGH_CONFIDENCE and head_sim >= HEAD_PREVIEW_SIMILARITY_THRESHOLD:
        return {
            "alignmentPassed": True,
            "titleSimilarity": round(title_sim, 4),
            "previewSimilarity": round(preview_sim, 4),
            "headPreviewSimilarity": round(head_sim, 4),
            "alignmentReason": "preview_high_confidence",
        }

    # Standard check: both must pass thresholds.
    if (
        title_sim >= TITLE_SIMILARITY_THRESHOLD
        and preview_sim >= PREVIEW_SIMILARITY_THRESHOLD
        and head_sim >= HEAD_PREVIEW_SIMILARITY_THRESHOLD
    ):
        return {
            "alignmentPassed": True,
            "titleSimilarity": round(title_sim, 4),
            "previewSimilarity": round(preview_sim, 4),
            "headPreviewSimilarity": round(head_sim, 4),
            "alignmentReason": "title_and_preview_matched",
        }

    # Relaxed path: exact-ish title plus a clear body-head match.
    if (
        title_sim >= 0.95
        and preview_sim >= RELAXED_PREVIEW_SIMILARITY_THRESHOLD
        and head_sim >= RELAXED_HEAD_PREVIEW_SIMILARITY_THRESHOLD
    ):
        return {
            "alignmentPassed": True,
            "titleSimilarity": round(title_sim, 4),
            "previewSimilarity": round(preview_sim, 4),
            "headPreviewSimilarity": round(head_sim, 4),
            "alignmentReason": "title_and_head_matched",
        }

    reason_parts = []
    if title_sim < TITLE_SIMILARITY_THRESHOLD:
        reason_parts.append("title_low")
    if preview_sim < PREVIEW_SIMILARITY_THRESHOLD:
        reason_parts.append("preview_low")
    if head_sim < HEAD_PREVIEW_SIMILARITY_THRESHOLD:
        reason_parts.append("head_low")
    return {
        "alignmentPassed": False,
        "titleSimilarity": round(title_sim, 4),
        "previewSimilarity": round(preview_sim, 4),
        "headPreviewSimilarity": round(head_sim, 4),
        "alignmentReason": "+".join(reason_parts) or "alignment_failed",
    }


# ── alignment JSON builder ───────────────────────────────────────────────────


def build_source_alignment_json(
    *,
    selected_content_source: str,
    official_content_length: int = 0,
    candidate_content_length: int = 0,
    title_similarity: float = 0.0,
    preview_similarity: float = 0.0,
    head_preview_similarity: float = 0.0,
    alignment_passed: bool = False,
    alignment_reason: str = "",
    candidate_source_id: str = "",
    primary_source_id: str = "",
) -> dict[str, Any]:
    """Build the JSON structure stored in ``source_alignment_json`` column."""
    return {
        "selectedContentSource": selected_content_source,
        "primarySourceId": primary_source_id,
        "officialContentLength": official_content_length,
        "candidateSourceId": candidate_source_id,
        "candidateContentLength": candidate_content_length,
        "titleSimilarity": round(title_similarity, 4),
        "previewSimilarity": round(preview_similarity, 4),
        "headPreviewSimilarity": round(head_preview_similarity, 4),
        "alignmentPassed": alignment_passed,
        "alignmentReason": alignment_reason,
    }


# ── deviation score (plan §10) ───────────────────────────────────────────────


def compute_deviation_score(original: str, ai_output: str, ai_self_score: float | None = None) -> float:
    """Compute deviation score between original content and AI output.

    Score range: 0.0 (completely different) to 1.0 (identical).
    Uses character-level LCS similarity after normalization, blended with
    the AI self-rating when available.

    Per plan §10.1.1: code_similarity * 0.7 + AI self-rating * 0.3.
    When ai_self_score is None, fall back to code_similarity only for
    backwards compatibility.
    """
    norm_orig = _normalize_for_compare(original)
    norm_out = _normalize_for_compare(ai_output)
    if not norm_orig or not norm_out:
        code_similarity = 0.0
    else:
        code_similarity = SequenceMatcher(None, norm_orig, norm_out, autojunk=False).ratio()

    if ai_self_score is None:
        return code_similarity
    return code_similarity * 0.7 + ai_self_score * 0.3
