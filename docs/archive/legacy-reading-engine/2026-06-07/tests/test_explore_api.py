"""Tests for explore API."""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.storage.db import initialize_database
import sqlite3

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr("app.config.DB_PATH", db)
    monkeypatch.setattr("app.services.source_repository.DB_PATH", db)
    initialize_database(db)
    yield


def test_list_explore_sources_empty():
    response = client.get("/api/admin/explore/sources")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data


def test_get_explore_groups_missing():
    response = client.get("/api/admin/explore/sources/fake/groups")
    assert response.status_code == 200
    data = response.json()
    assert data["groups"] == []


def test_explore_items_missing():
    response = client.post("/api/admin/explore/sources/fake/items", json={"exploreUrl": "", "page": 1})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
