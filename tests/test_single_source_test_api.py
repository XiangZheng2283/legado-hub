"""Tests for single source test API."""

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


def test_source_test_not_found():
    response = client.post("/api/admin/sources/fake-source/test", json={"keyword": "test", "stage": "search"})
    assert response.status_code == 200
    data = response.json()
    assert data["pass"] is False


def test_source_list():
    response = client.get("/api/admin/sources?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "stats" in data
