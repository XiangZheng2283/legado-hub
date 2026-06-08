"""Tests for Legado-facing API route shapes."""

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
            "bookList": "div.book",
            "name": "a@text",
            "bookUrl": "a@href",
        },
        "ruleBookInfo": {"name": "h1@text"},
        "ruleToc": {"chapterList": "ul li", "chapterName": "a@text", "chapterUrl": "a@href"},
        "ruleContent": {"content": "div.content@text"},
    },
}


def test_source_uses_request_host() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/api/legado/source",
            headers={"Host": "192.168.31.189:8765"},
        )
    assert response.status_code == 200
    source = response.json()[0]
    assert "192.168.31.189:8765" in source["searchUrl"]
    assert "192.168.31.189:8765" in source["jsLib"]


def test_routes_return_implemented() -> None:
    """Phase 2 endpoints should return implemented:true even when no results."""
    with patch("app.services.source_repository.SourceRepository.get_sources") as mock_sources, \
            patch("app.services.source_repository.SourceRepository.load_raw_source") as mock_load, \
            patch("app.engine.fetcher.Fetcher.fetch_with_proxy", new_callable=AsyncMock) as mock_fetch:
        mock_sources.return_value = [FAKE_SOURCE_INFO]
        mock_load.return_value = FAKE_SOURCE
        mock_fetch.return_value = FetchResult(
            text="<html><body></body></html>",
            final_url="http://example.com",
            success=True,
        )
        with TestClient(app) as client:
            urls = [
                "/api/legado/search?keyword=test",
                "/api/legado/book/test-book",
                "/api/legado/book/test-book/toc",
                "/api/legado/chapter/test-chapter",
            ]

            for url in urls:
                response = client.get(url)
                assert response.status_code == 200
                data = response.json()
                assert data["implemented"] is True
