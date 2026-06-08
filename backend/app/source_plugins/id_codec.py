"""Encode/decode book_id and chapter_id for URL-safe transport."""

from __future__ import annotations

import base64


def encode_book_id(source_id: str, book_url: str) -> str:
    encoded = base64.urlsafe_b64encode(book_url.encode("utf-8")).decode("utf-8").rstrip("=")
    return f"{source_id}:{encoded}"


def decode_book_id(book_id: str) -> tuple[str, str]:
    source_id, encoded = book_id.split(":", 1)
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += "=" * padding
    book_url = base64.urlsafe_b64decode(encoded).decode("utf-8")
    return source_id, book_url


def encode_chapter_id(source_id: str, chapter_url: str) -> str:
    encoded = base64.urlsafe_b64encode(chapter_url.encode("utf-8")).decode("utf-8").rstrip("=")
    return f"{source_id}:{encoded}"


def decode_chapter_id(chapter_id: str) -> tuple[str, str]:
    source_id, encoded = chapter_id.split(":", 1)
    padding = 4 - len(encoded) % 4
    if padding != 4:
        encoded += "=" * padding
    chapter_url = base64.urlsafe_b64decode(encoded).decode("utf-8")
    return source_id, chapter_url
