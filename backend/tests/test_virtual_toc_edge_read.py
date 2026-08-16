from __future__ import annotations

from app.api.legado import (
    VIRTUAL_SOURCE_ID,
    _aggregate_to_fanqie_book,
    _fanqie_toc_to_shared,
)
from app.services.aggregate_virtual_source import make_aggregate_book_url
from app.source_plugins.id_codec import decode_chapter_id


def test_aggregate_to_fanqie_book_extracts_fanqie_source() -> None:
    raw_url = "http://127.0.0.1:18423/__fanqie__/7552566466353040446"
    book_url = make_aggregate_book_url(
        {
            "candidateId": "cand-1",
            "name": "测试",
            "author": "作者",
            "items": [
                {
                    "sourceId": "fanqie_local",
                    "sourceName": "番茄下载器",
                    "bookUrl": raw_url,
                    "score": 100,
                    "lastChapter": "第1章",
                },
                {
                    "sourceId": "qidian_com_web",
                    "sourceName": "起点",
                    "bookUrl": "https://www.qidian.com/book/1",
                    "score": 90,
                },
            ],
        }
    )

    result = _aggregate_to_fanqie_book(book_url)

    assert result is not None
    fanqie_book_id, aggregate_book_id = result
    assert aggregate_book_id == "cand-1"
    source_id, fanqie_url = decode_chapter_id(fanqie_book_id)
    assert source_id == "fanqie_local"
    assert fanqie_url == raw_url


def test_aggregate_to_fanqie_book_needs_fanqie() -> None:
    book_url = make_aggregate_book_url(
        {
            "candidateId": "c2",
            "name": "n",
            "author": "a",
            "items": [
                {
                    "sourceId": "qidian_com_web",
                    "sourceName": "起点",
                    "bookUrl": "https://www.qidian.com/book/2",
                    "score": 90,
                },
            ],
        }
    )
    assert _aggregate_to_fanqie_book(book_url) is None


def test_fanqie_toc_to_shared_maps_to_virtual_chapter_ids() -> None:
    book_url = make_aggregate_book_url(
        {
            "candidateId": "agg-9",
            "name": "n",
            "author": "a",
            "items": [{"sourceId": "fanqie_local", "bookUrl": "http://127.0.0.1:18423/__fanqie__/999", "score": 1}],
        }
    )
    _, aggregate_book_id = _aggregate_to_fanqie_book(book_url)
    fanqie_toc = {
        "chapters": [
            {"sourceId": "fanqie_local", "index": 1, "title": "第一章", "chapterUrl": "http://127.0.0.1:18423/__fanqie__/999/1"},
            {"sourceId": "fanqie_local", "index": 2, "title": "第二章", "chapterUrl": "http://127.0.0.1:18423/__fanqie__/999/2"},
        ]
    }

    shared = _fanqie_toc_to_shared(fanqie_toc, aggregate_book_id=aggregate_book_id, book_id="bookid")

    assert [c["title"] for c in shared["chapters"]] == ["第一章", "第二章"]
    assert all(c["sourceId"] == VIRTUAL_SOURCE_ID for c in shared["chapters"])
    for c in shared["chapters"]:
        source_id, chapter_url = decode_chapter_id(c["chapterId"])
        assert source_id == VIRTUAL_SOURCE_ID
        assert isinstance(chapter_url, str) and chapter_url.startswith("legadohub://aggregate/chapter/")
