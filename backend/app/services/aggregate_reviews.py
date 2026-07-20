"""Helpers for aggregate chapter review contracts and paragraph alignment."""

from __future__ import annotations

import html
import re
from difflib import SequenceMatcher
from typing import Any


PARAGRAPH_MATCH_THRESHOLD = 0.70
PARAGRAPH_AMBIGUITY_MARGIN = 0.04
SHORT_PARAGRAPH_LENGTH = 8


def _data_root(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("Data") or payload.get("data") or payload
    return data if isinstance(data, dict) else {}


def _data_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        rows = value.get("DataList") or value.get("dataList") or []
        return rows if isinstance(rows, list) else []
    return []


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _paragraph_id(value: Any) -> int | None:
    paragraph_id = _safe_int(value, -1)
    return paragraph_id if paragraph_id >= 0 else None


def _review_item(review: dict[str, Any], paragraph_id: int) -> dict[str, Any]:
    normalized = dict(review)
    review_id = review.get("id") or review.get("Id") or review.get("ReviewId") or review.get("reviewId") or ""
    normalized["id"] = str(review_id)
    normalized["content"] = str(review.get("content") or review.get("Content") or "")
    normalized["paragraphId"] = paragraph_id
    return normalized


def normalize_hot_paragraph_reviews(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize plugin or raw Qidian hot-paragraph response shapes."""
    normalized_items = payload.get("hotParagraphReviews")
    if isinstance(normalized_items, list):
        items: list[dict[str, Any]] = []
        for raw in normalized_items:
            if not isinstance(raw, dict):
                continue
            paragraph_id = _paragraph_id(raw.get("paragraphId", raw.get("ParagraphId")))
            if paragraph_id is None:
                continue
            comment_count = _safe_int(
                raw.get("commentCount", raw.get("totalCommentCount", raw.get("hotCommentCount", 0)))
            )
            top_reviews = [
                _review_item(review, paragraph_id)
                for review in raw.get("topReviews", [])
                if isinstance(review, dict)
            ]
            items.append(
                {
                    **raw,
                    "paragraphId": paragraph_id,
                    "paragraphText": str(raw.get("paragraphText") or ""),
                    "matchedText": str(raw.get("matchedText") or ""),
                    "matchConfidence": float(raw.get("matchConfidence") or 0.0),
                    "commentCount": comment_count,
                    "hotCommentCount": _safe_int(raw.get("hotCommentCount"), comment_count),
                    "totalCommentCount": _safe_int(raw.get("totalCommentCount"), comment_count),
                    "topReviews": top_reviews,
                }
            )
        return items

    data = _data_root(payload)
    count_rows = _data_list(
        data.get("Getparagraphshotcommentcounts")
        or data.get("getparagraphshotcommentcounts")
    )
    reviews = _data_list(data.get("Reviews") or data.get("reviews"))
    reviews_by_paragraph: dict[int, list[dict[str, Any]]] = {}
    for review in reviews:
        if not isinstance(review, dict):
            continue
        paragraph_id = _paragraph_id(review.get("ParagraphId", review.get("paragraphId")))
        if paragraph_id is None:
            continue
        reviews_by_paragraph.setdefault(paragraph_id, []).append(_review_item(review, paragraph_id))

    items: list[dict[str, Any]] = []
    for row in count_rows:
        if not isinstance(row, dict):
            continue
        paragraph_id = _paragraph_id(row.get("ParagraphId", row.get("paragraphId")))
        if paragraph_id is None:
            continue
        comment_count = _safe_int(
            row.get("CommentCount", row.get("commentCount", row.get("HotCommentCount", 0)))
        )
        items.append(
            {
                "paragraphId": paragraph_id,
                "paragraphText": str(row.get("ParagraphText") or row.get("paragraphText") or ""),
                "matchedText": "",
                "matchConfidence": 0.0,
                "commentCount": comment_count,
                "hotCommentCount": _safe_int(row.get("HotCommentCount"), comment_count),
                "totalCommentCount": _safe_int(row.get("totalCommentCount"), comment_count),
                "topReviews": reviews_by_paragraph.get(paragraph_id, []),
            }
        )
    return items


def split_review_paragraphs(content: str) -> list[str]:
    """Split cleaned snapshot/Markdown content while preserving display text."""
    text = html.unescape(str(content or "")).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</?(?:p|div|section|article|li)\b[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|\n", text) if part.strip()]
    if paragraphs and paragraphs[0].startswith("# "):
        paragraphs = paragraphs[1:]
    return paragraphs


def _normalize_for_match(text: str) -> str:
    normalized = html.unescape(str(text or ""))
    normalized = re.sub(r"^[#>*\-+\s]+", "", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"[^0-9A-Za-z\u3400-\u9fff]", "", normalized)
    return normalized


def _paragraph_similarity(source_text: str, candidate_text: str) -> float:
    source = _normalize_for_match(source_text)
    candidate = _normalize_for_match(candidate_text)
    if not source or not candidate:
        return 0.0
    if source == candidate:
        return 1.0
    return SequenceMatcher(None, source, candidate, autojunk=False).ratio()


def _source_text_candidates(
    item: dict[str, Any],
    official_paragraphs: list[str],
) -> list[str]:
    explicit = str(item.get("paragraphText") or "").strip()
    if explicit:
        return [explicit]
    paragraph_id = _safe_int(item.get("paragraphId"), -1)
    indexes = [paragraph_id - 1, paragraph_id] if paragraph_id > 0 else [paragraph_id]
    candidates: list[str] = []
    for index in indexes:
        if 0 <= index < len(official_paragraphs):
            value = official_paragraphs[index]
            if value not in candidates:
                candidates.append(value)
    return candidates


def align_hot_paragraph_reviews(
    hot_reviews: list[dict[str, Any]],
    *,
    official_content: str,
    aggregate_content: str,
) -> list[dict[str, Any]]:
    """Fuzzily align official hot paragraphs to published aggregate text."""
    official_paragraphs = split_review_paragraphs(official_content)
    aggregate_paragraphs = split_review_paragraphs(aggregate_content)
    if not official_paragraphs or not aggregate_paragraphs:
        return [
            {
                **item,
                "matchedText": "",
                "matchConfidence": 0.0,
                "matchStatus": "source_text_unavailable" if not official_paragraphs else "aggregate_text_unavailable",
            }
            for item in hot_reviews
            if isinstance(item, dict)
        ]

    indexed_items = [
        (index, dict(item))
        for index, item in enumerate(hot_reviews)
        if isinstance(item, dict)
    ]
    indexed_items.sort(key=lambda pair: (_safe_int(pair[1].get("paragraphId"), 10**9), pair[0]))
    aligned_by_index: dict[int, dict[str, Any]] = {}
    next_candidate_index = 0

    for original_index, item in indexed_items:
        source_candidates = _source_text_candidates(item, official_paragraphs)
        if not source_candidates:
            aligned_by_index[original_index] = {
                **item,
                "paragraphText": "",
                "matchedText": "",
                "matchConfidence": 0.0,
                "matchStatus": "source_paragraph_not_found",
            }
            continue

        scored: list[tuple[float, int, int, str, str]] = []
        for source_text in source_candidates:
            for candidate_index in range(next_candidate_index, len(aggregate_paragraphs)):
                for paragraph_count in (1, 2):
                    end = candidate_index + paragraph_count
                    if end > len(aggregate_paragraphs):
                        continue
                    candidate_text = "\n\n".join(aggregate_paragraphs[candidate_index:end])
                    score = _paragraph_similarity(source_text, candidate_text)
                    scored.append((score, candidate_index, paragraph_count, source_text, candidate_text))

        scored.sort(key=lambda value: (value[0], -value[1], -value[2]), reverse=True)
        best = scored[0] if scored else (0.0, -1, 0, source_candidates[0], "")
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        score, candidate_index, paragraph_count, source_text, candidate_text = best
        normalized_length = len(_normalize_for_match(source_text))
        unique_enough = score >= 0.96 or score - second_score >= PARAGRAPH_AMBIGUITY_MARGIN
        short_text_ok = normalized_length >= SHORT_PARAGRAPH_LENGTH or score == 1.0
        accepted = score >= PARAGRAPH_MATCH_THRESHOLD and unique_enough and short_text_ok

        aligned = {
            **item,
            "paragraphText": source_text,
            "matchedText": candidate_text if accepted else "",
            "matchConfidence": round(score, 4),
            "matchStatus": "matched" if accepted else "low_confidence",
        }
        if accepted:
            aligned["matchedParagraphIndex"] = candidate_index
            aligned["matchedParagraphCount"] = paragraph_count
            next_candidate_index = candidate_index + paragraph_count
        aligned_by_index[original_index] = aligned

    return [aligned_by_index[index] for index, _item in enumerate(hot_reviews) if index in aligned_by_index]


def summarize_reviews(payload: dict[str, Any]) -> dict[str, int]:
    paragraphs = payload.get("paragraphs") if isinstance(payload.get("paragraphs"), dict) else {}
    paragraph_review_count = sum(
        len(reviews)
        for reviews in paragraphs.values()
        if isinstance(reviews, list)
    )
    hot_reviews = payload.get("hotParagraphReviews") or []
    matched_hot_reviews = sum(
        1
        for item in hot_reviews
        if isinstance(item, dict) and item.get("matchedText")
    )
    return {
        "chapterEndHot": len(payload.get("chapterEndHot") or []),
        "chapterEnd": len(payload.get("chapterEnd") or []),
        "authorReviews": len(payload.get("authorReviews") or []),
        "hotParagraphReviews": len(hot_reviews),
        "matchedHotParagraphReviews": matched_hot_reviews,
        "paragraphs": len(paragraphs),
        "paragraphReviewCount": paragraph_review_count,
    }


def hot_review_bubble_label(index: int) -> str:
    """Return the neutral display label used by the reading client."""
    return f"热评 {index}"


def empty_aggregate_reviews(
    *,
    chapter_id: str,
    mapped_chapter_id: str = "",
    mapped_source_id: str = "",
    mapping_reason: str = "not_mapped",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "implemented": True,
        "chapterId": chapter_id,
        "mappedChapterId": mapped_chapter_id,
        "mappedSourceId": mapped_source_id,
        "mappingReason": mapping_reason,
        "chapterEndHot": [],
        "chapterEnd": [],
        "authorReviews": [],
        "hotParagraphReviews": [],
        "paragraphs": {},
        "summary": {},
        "debug": {"aggregate": True, "reviewSource": mapping_reason},
    }
    payload["summary"] = summarize_reviews(payload)
    return payload
