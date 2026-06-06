"""Tests for backend realtime search progress."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_admin_search_page_uses_realtime_stream() -> None:
    response = client.get("/admin/search")
    assert response.status_code == 200
    assert "书源调用进度" in response.text
    assert "实时搜索结果" in response.text
    assert "EventSource" in response.text
    assert "/api/admin/search/stream" in response.text


def test_admin_search_stream_returns_sse_events() -> None:
    with client.stream("GET", "/api/admin/search/stream?keyword=__unlikely_keyword__&page=1&limit=0") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        chunks = []
        for chunk in response.iter_text():
            chunks.append(chunk)
            if "done" in "".join(chunks):
                break
    text = "".join(chunks)
    assert "summary" in text
    assert "done" in text
