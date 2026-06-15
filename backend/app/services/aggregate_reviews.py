"""Helpers for aggregate chapter review contracts."""

from __future__ import annotations

from typing import Any


def _data_root(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("Data") or payload.get("data") or payload
    return data if isinstance(data, dict) else {}


def _paragraph_id(value: Any) -> int | None:
    try:
        paragraph_id = int(value)
    except (TypeError, ValueError):
        return None
    return paragraph_id if paragraph_id >= 0 else None


def _review_item(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "reviewId": str(review.get("ReviewId") or review.get("reviewId") or ""),
        "content": str(review.get("Content") or review.get("content") or ""),
        "type": review.get("Type", review.get("type", "")),
        "paragraphId": _paragraph_id(review.get("ParagraphId", review.get("paragraphId"))) or 0,
    }


def normalize_hot_paragraph_reviews(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize Qidian hot paragraph review summary payloads.

    This only creates the backend contract. Fuzzy matching against aggregate
    Markdown text is intentionally left for the full implementation.
    """

    data = _data_root(payload)
    count_rows = data.get("Getparagraphshotcommentcounts") or data.get("getparagraphshotcommentcounts") or []
    reviews = data.get("Reviews") or data.get("reviews") or []
    reviews_by_paragraph: dict[int, list[dict[str, Any]]] = {}
    for review in reviews:
        if not isinstance(review, dict):
            continue
        paragraph_id = _paragraph_id(review.get("ParagraphId", review.get("paragraphId")))
        if paragraph_id is None:
            continue
        reviews_by_paragraph.setdefault(paragraph_id, []).append(_review_item(review))

    items: list[dict[str, Any]] = []
    for row in count_rows:
        if not isinstance(row, dict):
            continue
        paragraph_id = _paragraph_id(row.get("ParagraphId", row.get("paragraphId")))
        if paragraph_id is None:
            continue
        hot_count = int(row.get("HotCommentCount", row.get("hotCommentCount", 0)) or 0)
        total_count = int(row.get("CommentCount", row.get("totalCommentCount", hot_count)) or 0)
        items.append(
            {
                "paragraphId": paragraph_id,
                "paragraphText": str(row.get("ParagraphText") or row.get("paragraphText") or ""),
                "matchedText": "",
                "matchConfidence": 0.0,
                "hotCommentCount": hot_count,
                "totalCommentCount": total_count,
                "topReviews": reviews_by_paragraph.get(paragraph_id, []),
            }
        )
    return items


def summarize_reviews(payload: dict[str, Any]) -> dict[str, int]:
    paragraphs = payload.get("paragraphs") if isinstance(payload.get("paragraphs"), dict) else {}
    paragraph_review_count = 0
    for reviews in paragraphs.values():
        if isinstance(reviews, list):
            paragraph_review_count += len(reviews)
    return {
        "chapterEndHot": len(payload.get("chapterEndHot") or []),
        "chapterEnd": len(payload.get("chapterEnd") or []),
        "authorReviews": len(payload.get("authorReviews") or []),
        "hotParagraphReviews": len(payload.get("hotParagraphReviews") or []),
        "paragraphs": len(paragraphs),
        "paragraphReviewCount": paragraph_review_count,
    }


def hot_review_bubble_label(index: int) -> str:
    """Return the display label for a hot review bubble.

    Uses "热评 N" format — NOT "起点热评 N".
    """
    return f"热评 {index}"


def empty_aggregate_reviews(
    *,
    chapter_id: str,
    mapped_chapter_id: str = "",
    mapped_source_id: str = "",
    mapping_reason: str = "not_mapped",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
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
