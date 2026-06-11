"""Tests for readable novel filesystem cache."""

import json
import sqlite3

from app.services.aggregate_processor import AggregateProcessor
from app.services.aggregate_virtual_source import (
    VIRTUAL_SOURCE_ID,
    make_aggregate_book_url,
    make_aggregate_chapter_url,
    unpack_aggregate_book_url,
)
from app.services.cache import Cache
from app.source_plugins.id_codec import encode_book_id, encode_chapter_id
from app.storage.db import initialize_database


def test_chapter_cache_writes_readable_markdown_file(tmp_path):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    cache = Cache(db_path)
    book_id = encode_book_id("source_a", "https://www.69shuba.com/book/1/")
    chapter_url = "https://www.69shuba.com/txt/1/2"
    chapter_id = encode_chapter_id("source_a", chapter_url)

    cache.set_book(
        book_id,
        "source_a",
        "https://www.69shuba.com/book/1/",
        {"implemented": True, "data": {"name": "测试小说", "author": "作者甲"}},
    )
    cache.set_toc(
        book_id,
        {
            "implemented": True,
            "bookId": book_id,
            "chapters": [
                {
                    "index": 1,
                    "title": "第一章 开始",
                    "chapterUrl": f"http://127.0.0.1:8765/api/legado/chapter/{chapter_id}",
                }
            ],
        },
    )
    cache.set_chapter(
        chapter_id,
        "source_a",
        chapter_url,
        {"implemented": True, "chapterId": chapter_id, "title": "第一章 开始", "content": "正文内容"},
    )

    expected = tmp_path / "novels" / "www.69shuba.com" / "测试小说" / "000001 第一章 开始.md"
    assert expected.exists()
    assert expected.read_text(encoding="utf-8") == "# 第一章 开始\n\n正文内容\n"
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT book_id, book_name, chapter_title, file_path, content_hash FROM chapter_cache WHERE chapter_id = ?",
            (chapter_id,),
        ).fetchone()
    assert row[0] == book_id
    assert row[1] == "测试小说"
    assert row[2] == "第一章 开始"
    assert row[3] == str(expected)
    assert len(row[4]) == 64


def test_processed_aggregate_chapter_writes_readable_markdown_file(tmp_path):
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO admin_settings (key, value_json) VALUES (?, ?)",
            (
                "contentWorkflow",
                json.dumps({"aiEnabled": True, "autoAggregate": True, "processAggregateOnRead": True}, ensure_ascii=False),
            ),
        )
        conn.commit()

    group = {
        "candidateId": "candidate-1",
        "name": "聚合小说",
        "author": "作者甲",
        "items": [
            {
                "sourceId": "source_a",
                "sourceName": "Source A",
                "name": "聚合小说",
                "author": "作者甲",
                "bookUrl": "https://a.example/book/1",
                "score": 10,
            }
        ],
    }
    aggregate_book_url = make_aggregate_book_url(group)
    aggregate_book_id = encode_book_id(VIRTUAL_SOURCE_ID, aggregate_book_url)
    payload = unpack_aggregate_book_url(aggregate_book_url)
    source_chapter_id = encode_chapter_id("source_a", "https://a.example/book/1/1.html")
    aggregate_chapter_url = make_aggregate_chapter_url(
        aggregate_book_id,
        source_chapter_id,
        title="第一章 聚合",
        index=1,
    )
    aggregate_chapter_id = encode_chapter_id(VIRTUAL_SOURCE_ID, aggregate_chapter_url)
    processor = AggregateProcessor(db_path)
    processor.enqueue_book(aggregate_book_id, payload)
    processor.register_toc(
        aggregate_book_id,
        payload,
        [{"index": 1, "title": "第一章 聚合", "chapterUrl": "https://a.example/book/1/1.html"}],
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE aggregate_chapter_tasks
            SET status = 'processed', processed_content = ?, content_length = ?
            WHERE chapter_id = ?
            """,
            ("聚合正文", len("聚合正文"), aggregate_chapter_id),
        )
        conn.commit()

    response = processor.aggregate_chapter_response(aggregate_chapter_url, chapter_id=aggregate_chapter_id)

    expected = tmp_path / "novels" / VIRTUAL_SOURCE_ID / "聚合小说" / "000001 第一章 聚合.md"
    assert response["content"] == "聚合正文"
    assert expected.exists()
    assert expected.read_text(encoding="utf-8") == "# 第一章 聚合\n\n聚合正文\n"
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT response_json FROM chapter_cache WHERE chapter_id = ?",
            (aggregate_chapter_id,),
        ).fetchone()
    assert row is None






