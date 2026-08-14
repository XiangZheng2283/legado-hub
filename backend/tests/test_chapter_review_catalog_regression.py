from app.services.chapter_review_catalog import _mapped_review_target
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
