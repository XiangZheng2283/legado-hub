from __future__ import annotations
import asyncio
from app.services.chapter_review_catalog import _enrich_review_media, _mapped_review_target
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
