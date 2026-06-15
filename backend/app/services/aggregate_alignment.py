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


# ── helpers ──────────────────────────────────────────────────────────────────


def _normalize_for_compare(text: str) -> str:
    """Strip whitespace, punctuation and line breaks for fuzzy comparison."""
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。！？、；：""''（）《》【】\.\,\!\?\;\:\"\'\(\)\<\>\[\]]", "", text)
    return text


def _title_similarity(a: str, b: str) -> float:
    """Character-level similarity between two chapter titles."""
    na = _normalize_for_compare(a)
    nb = _normalize_for_compare(b)
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
) -> dict[str, Any]:
    """Classify fetched chapter content as ``full`` / ``preview`` / ``empty``.

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

    if length >= FULL_CONTENT_MIN_LENGTH:
        return {
            "classification": "full",
            "contentLength": length,
            "previewText": preview_text,
            "isOfficial": is_official,
            "sourceId": source_id,
            "reason": "content_length_sufficient",
        }

    # Short content — likely a VIP preview.
    return {
        "classification": "preview",
        "contentLength": length,
        "previewText": preview_text,
        "isOfficial": is_official,
        "sourceId": source_id,
        "reason": "content_too_short_likely_preview",
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
            "alignmentReason": "no_preview_available",
        }

    title_sim = _title_similarity(expected_title, candidate_title)
    preview_sim = _sliding_preview_similarity(official_preview, candidate_content)

    # High-confidence preview bypasses title check.
    if preview_sim >= PREVIEW_HIGH_CONFIDENCE:
        return {
            "alignmentPassed": True,
            "titleSimilarity": round(title_sim, 4),
            "previewSimilarity": round(preview_sim, 4),
            "alignmentReason": "preview_high_confidence",
        }

    # Standard check: both must pass thresholds.
    if title_sim >= TITLE_SIMILARITY_THRESHOLD and preview_sim >= PREVIEW_SIMILARITY_THRESHOLD:
        return {
            "alignmentPassed": True,
            "titleSimilarity": round(title_sim, 4),
            "previewSimilarity": round(preview_sim, 4),
            "alignmentReason": "title_and_preview_matched",
        }

    reason_parts = []
    if title_sim < TITLE_SIMILARITY_THRESHOLD:
        reason_parts.append("title_low")
    if preview_sim < PREVIEW_SIMILARITY_THRESHOLD:
        reason_parts.append("preview_low")
    return {
        "alignmentPassed": False,
        "titleSimilarity": round(title_sim, 4),
        "previewSimilarity": round(preview_sim, 4),
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
        "alignmentPassed": alignment_passed,
        "alignmentReason": alignment_reason,
    }


# ── deviation score (plan §10) ───────────────────────────────────────────────


def compute_deviation_score(original: str, ai_output: str) -> float:
    """Compute deviation score between original content and AI output.

    Score range: 0.0 (completely different) to 1.0 (identical).
    Uses character-level LCS similarity after normalization.

    Per plan §10.1.1: code_similarity * 0.7 + placeholder for AI self-rating * 0.3.
    Since AI self-rating requires an extra API call, first version uses
    code_similarity only (weight 1.0) and reserves self-rating for later.
    """
    norm_orig = _normalize_for_compare(original)
    norm_out = _normalize_for_compare(ai_output)
    if not norm_orig or not norm_out:
        return 0.0
    return SequenceMatcher(None, norm_orig, norm_out, autojunk=False).ratio()
