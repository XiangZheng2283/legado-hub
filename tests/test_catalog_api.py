"""Tests for catalog service API wiring."""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.engine.proxy import FetchResult


FAKE_SOURCE_INFO = {
    "sourceId": "fake-source",
    "bookSourceName": "Fake Source",
    "proxyMode": "never",
}

FAKE_SOURCE = {
    "sourceName": "Fake Source",
    "sourceUrl": "http://example.com",
    "proxyMode": "never",
    "raw": {
        "bookSourceName": "Fake Source",
        "bookSourceUrl": "http://example.com",
        "searchUrl": "/search?keyword={{key}}",
        "ruleSearch": {
            "bookList": "div.hot_4@li",
            "name": "span.hot_name@text",
            "author": "span.author@text",
            "bookUrl": "a@href",
        },
        "ruleBookInfo": {"name": "h1@text"},
        "ruleToc": {"chapterList": "ul li"},
        "ruleContent": {"content": "div.content@text"},
    },
}


def test_search_returns_real_shape() -> None:
    with patch("app.services.source_repository.SourceRepository.get_sources") as mock_sources, \
            patch("app.services.source_repository.SourceRepository.load_raw_source") as mock_load, \
            patch("app.engine.fetcher.Fetcher.fetch_with_proxy", new_callable=AsyncMock) as mock_fetch:
        mock_sources.return_value = [FAKE_SOURCE_INFO]
        mock_load.return_value = FAKE_SOURCE
        mock_fetch.return_value = FetchResult(
            text='<html><body><div class="hot_4"><li><span class="hot_name">Test Book</span>'
            '<span class="author">Author</span><a href="/123"></a></li></div></body></html>',
            final_url="http://example.com",
            success=True,
        )
        with TestClient(app) as client:
            response = client.get("/api/legado/search?keyword=test")
        assert response.status_code == 200
        data = response.json()
        assert data["implemented"] is True
        assert "items" in data
        assert "debug" in data


def test_book_detail_invalid_id() -> None:
    with TestClient(app) as client:
        response = client.get("/api/legado/book/invalid-id")
    assert response.status_code == 200
    data = response.json()
    assert data["implemented"] is True
    assert data["data"] is None
