from __future__ import annotations
import asyncio
from app.services.chapter_review_catalog import _enrich_review_media, _mapped_review_target
from app.services.reading_reviews import _review_card
from app.source_plugins.id_codec import encode_chapter_id

def test_direct_review_target_is_available_for_paged_reviews() -> None:
    chapter_url = "http://127.0.0.1:18423/__fanqie__/book/1"
    chapter_id = encode_chapter_id("fanqie_local", chapter_url)
    assert _mapped_review_target(chapter_id) == ("fanqie_local", chapter_url, chapter_id, False)

def test_fanqie_review_media_reads_completed_queue_urls(monkeypatch) -> None:
    urls={"OEBPS/images/avatar.jpg":"https://imgbed.example/avatar.jpg","OEBPS/images/comment.png":"https://imgbed.example/comment.png"}
    class Queue:
        def find_uploaded(self, *, ref="", **_kwargs): return urls.get(ref, "")
    monkeypatch.setattr("app.services.chapter_review_catalog.media_upload_queue_service", Queue())
    payload={"paragraphs":{"0":[{"id":"review-1","content":"文字","avatarRef":"OEBPS/images/avatar.jpg","imageRefs":["OEBPS/images/comment.png"]}]}}
    result=asyncio.run(_enrich_review_media(None,payload,"fanqie_local","fanqie://book/1/1"))
    review=result["paragraphs"]["0"][0]
    assert "avatarRef" not in review and "imageRefs" not in review
    assert review["avatar"] == urls["OEBPS/images/avatar.jpg"]
    assert review["imageUrls"] == [urls["OEBPS/images/comment.png"]]
    assert result["debug"]["mediaUploaded"] == 2

def test_fanqie_review_media_drops_pending_refs_without_fallback(monkeypatch) -> None:
    class Queue:
        def find_uploaded(self, **_kwargs): return ""
    monkeypatch.setattr("app.services.chapter_review_catalog.media_upload_queue_service", Queue())
    payload={"paragraphs":{"0":[{"content":"文字","avatarRef":"OEBPS/images/avatar.jpg","imageRefs":["OEBPS/images/comment.png"]}]}}
    result=asyncio.run(_enrich_review_media(None,payload,"fanqie_local","fanqie://book/1/1"))
    review=result["paragraphs"]["0"][0]
    assert "avatarRef" not in review and "imageRefs" not in review
    assert "avatar" not in review and "imageUrls" not in review and "imageUrl" not in review
    assert result["debug"]["mediaFailed"] == 2

def test_fanqie_detail_payload_comments_are_enriched_for_reviews_view(monkeypatch) -> None:
    """/reviews/view drill-down payloads (paragraph/page/chapter_say/replies) must
    carry resolved image URLs, matching the summary /reviews media contract."""
    urls = {
        "OEBPS/images/avatar.jpg": "https://res.qpic.cn/avatar.jpg",
        "OEBPS/images/comment.png": "https://qpic.qpic.cn/comment.png",
    }

    class Queue:
        def find_uploaded(self, *, ref="", **_kwargs):
            return urls.get(ref, "")

    monkeypatch.setattr("app.services.chapter_review_catalog.media_upload_queue_service", Queue())
    payload = {
        "implemented": True,
        "chapterId": "x",
        "comments": [
            {
                "id": "r1",
                "userName": "书友",
                "content": "文字",
                "avatarRef": "OEBPS/images/avatar.jpg",
                "imageRefs": ["OEBPS/images/comment.png"],
            }
        ],
        "totalCount": 1,
        "hasMore": False,
    }
    result = asyncio.run(_enrich_review_media(None, payload, "fanqie_local", "fanqie://book/1/1"))
    review = result["comments"][0]
    assert "avatarRef" not in review and "imageRefs" not in review
    assert review["avatar"] == urls["OEBPS/images/avatar.jpg"]
    assert review["imageUrls"] == [urls["OEBPS/images/comment.png"]]
    # 富化只产出结构化字段，正文保持纯文本（不自包含 contentHtml）。
    assert "contentHtml" not in review
    assert review["content"] == "文字"
    # 版式统一交 _review_card：头像框 + 用户名 + 正文 + 独立媒体框。
    card = _review_card(review)
    assert "comment-avatar" in card, "avatar box must render"
    assert "comment-media-wrap" in card, "image must render inside the framed media wrap"
    assert "comment-inline-media" not in card, "no inline images escaping the media box"
    assert "qpic.qpic.cn/comment.png" in card
