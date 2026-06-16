"""Tests for Qidian private reviews module."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# Ensure project root is on path so `plugins.*` imports work
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class _MockHttp:
    def __init__(self, handlers: list[tuple[str, callable]] | None = None):
        self._handlers = handlers or []
        self._calls: list[dict[str, Any]] = []

    async def fetch_json(self, url: str, **kwargs):
        params = kwargs.get("params") or {}
        self._calls.append({"url": url, "params": params})
        for prefix, handler in self._handlers:
            if url.startswith(prefix):
                return handler(url, params)
        return {}


def _make_ctx(handlers: list[tuple[str, callable]] | None = None, cookies: dict[str, dict[str, str]] | None = None):
    ctx = MagicMock()
    ctx.cookies = cookies or {
        "qidian.com": {"ywguid": "123", "ywkey": "abc", "_csrfToken": "tok"},
        "m.qidian.com": {"ywguid": "123", "ywkey": "abc", "_csrfToken": "tok"},
    }
    ctx.access.http = _MockHttp(handlers)
    ctx.trace = MagicMock()
    return ctx


@pytest.mark.asyncio
async def test_chapter_reviews_returns_vip_hint_when_full_list_is_empty():
    """When logged in and reviewlist4m returns 0 but hot comments exist,
    the response should include a VIP hint."""
    from plugins.sources.official.qidian_com.private.reviews import chapter_reviews

    book_id = "103294347"
    chapter_id = "719642318"
    chapter_url = f"https://m.qidian.com/chapter/{book_id}/{chapter_id}/"

    def _handler(url: str, params: dict[str, Any]) -> dict[str, Any]:
        if url.endswith("reviewsummary4m"):
            return {
                "data": {
                    "total": 26,
                    "list": [{"paragraphId": -1, "reviewNum": 0}],
                }
            }
        if url.endswith("getchapterendcomments"):
            return {
                "data": {
                    "TotalCount": 26,
                    "DataList": [
                        {
                            "reviewId": "hot-1",
                            "content": "hot comment",
                            "UserName": "reader",
                            "AgreeAmount": 99,
                        }
                    ],
                }
            }
        if url.endswith("reviewlist4m"):
            return {"data": {"total": 0, "list": []}}
        return {}

    ctx = _make_ctx(
        [
            ("https://m.qidian.com/webcommon/chapterreview/reviewsummary4m", _handler),
            ("https://m.qidian.com/webcommon/review/getchapterendcomments", _handler),
            ("https://m.qidian.com/webcommon/chapterreview/reviewlist4m", _handler),
        ]
    )
    result = await chapter_reviews(ctx, chapter_url)

    assert result["chapterEndHot"][0]["content"] == "hot comment"
    assert result["chapterEnd"] == []
    assert result["summary"]["chapterEndReviewlistTotal"] == 0
    assert "VIP/订阅限制" in result["summary"]["vipHint"]


@pytest.mark.asyncio
async def test_chapter_reviews_no_vip_hint_when_reviewlist_has_data():
    """For a normal (free) chapter the VIP hint should not appear."""
    from plugins.sources.official.qidian_com.private.reviews import chapter_reviews

    chapter_url = "https://m.qidian.com/chapter/1043748975/830374333/"

    def _handler(url: str, params: dict[str, Any]) -> dict[str, Any]:
        if url.endswith("reviewsummary4m"):
            return {
                "data": {
                    "total": 100,
                    "list": [
                        {"paragraphId": -1, "reviewNum": 80},
                        {"paragraphId": 1, "reviewNum": 20, "isHotSegment": True},
                    ],
                }
            }
        if url.endswith("getchapterendcomments"):
            return {"data": {"TotalCount": 2, "DataList": []}}
        if url.endswith("reviewlist4m"):
            paragraph_id = params.get("paragraphId")
            page = params.get("page", 1)
            if paragraph_id == -1 and page == 1:
                return {
                    "data": {
                        "total": 80,
                        "list": [
                            {"reviewId": "ce-1", "content": "chapter end review", "nickName": "reader", "likeCount": 5}
                        ],
                    }
                }
            if paragraph_id == 1 and page == 1:
                return {
                    "data": {
                        "total": 20,
                        "list": [
                            {"reviewId": "p1-1", "content": "paragraph review", "nickName": "reader", "likeCount": 3}
                        ],
                    }
                }
            return {"data": {"total": 0, "list": []}}
        return {}

    ctx = _make_ctx(
        [
            ("https://m.qidian.com/webcommon/chapterreview/reviewsummary4m", _handler),
            ("https://m.qidian.com/webcommon/review/getchapterendcomments", _handler),
            ("https://m.qidian.com/webcommon/chapterreview/reviewlist4m", _handler),
        ]
    )
    result = await chapter_reviews(ctx, chapter_url)

    assert result["summary"]["chapterEndReviewlistTotal"] == 80
    assert result["summary"]["vipHint"] == ""
    assert len(result["chapterEnd"]) == 1
    assert result["paragraphs"]["1"][0]["content"] == "paragraph review"



@pytest.mark.asyncio
async def test_chapter_reviews_vip_hint_when_reviews_disabled():
    """When summary returns enableReview=0 while logged in, surface VIP hint."""
    from plugins.sources.official.qidian_com.private.reviews import chapter_reviews

    def _handler(url: str, params: dict[str, Any]) -> dict[str, Any]:
        if url.endswith("reviewsummary4m"):
            return {"data": {"total": 0, "enableReview": 0, "list": []}}
        return {"data": {"total": 0, "list": []}}

    ctx = _make_ctx(
        [
            ("https://m.qidian.com/webcommon/chapterreview/reviewsummary4m", _handler),
            ("https://m.qidian.com/webcommon/review/getchapterendcomments", _handler),
            ("https://m.qidian.com/webcommon/chapterreview/reviewlist4m", _handler),
        ]
    )
    result = await chapter_reviews(ctx, "https://m.qidian.com/chapter/103294347/719642318/")
    assert "评论未开启" in result["summary"]["vipHint"]
