"""Tests for aggregate review response normalization."""

from app.services.aggregate_reviews import (
    empty_aggregate_reviews,
    hot_review_bubble_label,
    normalize_hot_paragraph_reviews,
    summarize_reviews,
)


def test_normalize_hot_paragraph_reviews_from_qidian_summary_sample():
    summary = {
        "Data": {
            "Getparagraphshotcommentcounts": [
                {"ParagraphId": 59, "HotCommentCount": 34, "CommentCount": 45},
                {"ParagraphId": 83, "HotCommentCount": 2, "CommentCount": 9},
            ],
            "Reviews": [
                {
                    "ParagraphId": 59,
                    "ReviewId": "r1",
                    "Content": "这一段太燃了",
                    "Type": 1,
                },
                {
                    "ParagraphId": 83,
                    "ReviewId": "r2",
                    "Content": "伏笔来了",
                    "Type": 1,
                },
            ],
        }
    }

    hot_reviews = normalize_hot_paragraph_reviews(summary)

    assert hot_reviews == [
        {
            "paragraphId": 59,
            "paragraphText": "",
            "matchedText": "",
            "matchConfidence": 0.0,
            "hotCommentCount": 34,
            "totalCommentCount": 45,
            "topReviews": [
                {
                    "reviewId": "r1",
                    "content": "这一段太燃了",
                    "type": 1,
                    "paragraphId": 59,
                }
            ],
        },
        {
            "paragraphId": 83,
            "paragraphText": "",
            "matchedText": "",
            "matchConfidence": 0.0,
            "hotCommentCount": 2,
            "totalCommentCount": 9,
            "topReviews": [
                {
                    "reviewId": "r2",
                    "content": "伏笔来了",
                    "type": 1,
                    "paragraphId": 83,
                }
            ],
        },
    ]


def test_empty_aggregate_reviews_keeps_required_contract_fields():
    reviews = empty_aggregate_reviews(
        chapter_id="aggregate:chapter",
        mapped_chapter_id="qidian:chapter",
        mapped_source_id="qidian_com",
    )

    assert reviews["chapterId"] == "aggregate:chapter"
    assert reviews["mappedChapterId"] == "qidian:chapter"
    assert reviews["mappedSourceId"] == "qidian_com"
    assert reviews["chapterEndHot"] == []
    assert reviews["chapterEnd"] == []
    assert reviews["authorReviews"] == []
    assert reviews["hotParagraphReviews"] == []
    assert reviews["paragraphs"] == {}
    assert reviews["summary"] == summarize_reviews(reviews)


def test_hot_review_bubble_label_uses_correct_format():
    assert hot_review_bubble_label(1) == "热评 1"
    assert hot_review_bubble_label(5) == "热评 5"
    assert hot_review_bubble_label(99) == "热评 99"


def test_hot_review_bubble_label_not_qidian_prefix():
    """The label must be '热评 N', not '起点热评 N'."""
    label = hot_review_bubble_label(1)
    assert "起点" not in label
    assert label == "热评 1"
