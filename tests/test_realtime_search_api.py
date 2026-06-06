"""Tests for realtime search job API."""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.storage.db import initialize_database

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr("app.config.DB_PATH", db)
    monkeypatch.setattr("app.services.source_repository.DB_PATH", db)
    monkeypatch.setattr("app.services.cache.DB_PATH", db)
    initialize_database(db)
    yield


def test_create_search_job():
    response = client.post("/api/admin/search-jobs", json={"keyword": "凡人修仙传", "page": 1, "limit": 3})
    assert response.status_code == 200
    data = response.json()
    assert "jobId" in data
    assert data["status"] == "pending"


def test_get_search_job():
    create = client.post("/api/admin/search-jobs", json={"keyword": "test", "page": 1, "limit": 2})
    job_id = create.json()["jobId"]
    response = client.get(f"/api/admin/search-jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["jobId"] == job_id


def test_cancel_search_job():
    create = client.post("/api/admin/search-jobs", json={"keyword": "test", "page": 1, "limit": 2})
    job_id = create.json()["jobId"]
    response = client.post(f"/api/admin/search-jobs/{job_id}/cancel")
    assert response.status_code == 200
    data = response.json()
    assert data["cancelled"] is True


def test_search_stream():
    response = client.get("/api/admin/search/stream?keyword=test&limit=2")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
