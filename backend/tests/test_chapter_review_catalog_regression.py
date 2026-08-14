from __future__ import annotations

import asyncio

from app.services.chapter_review_catalog import _enrich_review_media, _mapped_review_target
from app.source_plugins.id_codec import encode_chapter_id


def test_direct_review_target_is_available_for_paged_reviews() -> None:
    chapter_url = "http://127.0.0.1:18423/__fanqie__/book/1"
    chapter_id = encode_chapter_id("fanqie_local", chapter_url)

    assert _mapped_review_target(chapter_id) == (
        "fanqie_local",
        chapter_url,
        chapter_id,
        False,
    )


def test_fanqie_review_media_is_text_only_without_source_or_imgbed_fetch(monkeypatch) -> None:
    calls: list[str] = []

    class Uploader:
        class Config:
            enabled = True

        config = Config()

        async def upload(self, *_args, **_kwargs):
            calls.append("upload")
            return "https://imgbed.example/review.jpg"

    monkeypatch.setattr(
        "app.services.chapter_review_catalog.get_imgbed_uploader",
        lambda: Uploader(),
    )

    class Scheduler:
        async def chapter_review_media(self, *_args):
            calls.append("called")
            raise AssertionError("fanqie review media must not be fetched")

    payload = {
        "paragraphs": {
            "0": [
                {
                    "id": "review-1",
                    "content": "纯文字评论",
                    "avatarRef": "OEBPS/images/avatar.jpg",
                    "imageRefs": ["OEBPS/images/comment.png"],
                }
            ]
        }
    }

    result = asyncio.run(
        _enrich_review_media(
            Scheduler(),
            payload,
            "fanqie_local",
            "fanqie://book/1/1",
        )
    )

    review = result["paragraphs"]["0"][0]
    assert review == {"id": "review-1", "content": "纯文字评论"}
    assert calls == []
