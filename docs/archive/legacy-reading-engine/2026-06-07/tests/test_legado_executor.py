"""Tests for Legado executor utilities."""

from app.engine.legado_executor import encode_book_id, decode_book_id, encode_chapter_id, decode_chapter_id


def test_book_id_roundtrip() -> None:
    original = "https://example.com/book/1/"
    encoded = encode_book_id("test-source", original)
    sid, decoded = decode_book_id(encoded)
    assert sid == "test-source"
    assert decoded == original


def test_chapter_id_roundtrip() -> None:
    original = "https://example.com/chapter/1/"
    encoded = encode_chapter_id("test-source", original)
    sid, decoded = decode_chapter_id(encoded)
    assert sid == "test-source"
    assert decoded == original
