"""Tests for book reader API."""

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
    monkeypatch.setattr("app.services.cache.DB_PATH", db)
    initialize_database(db)
    yield


def test_get_book_not_found():
    response = client.get("/api/console/books/fake-book")
    assert response.status_code == 200
    data = response.json()
    assert "detail" in data


def test_get_chapter_invalid():
    response = client.get("/api/console/chapter/invalid")
    assert response.status_code == 200
    data = response.json()
    assert "content" in data


def test_chapter_navigation():
    response = client.get("/api/console/books/fake/chapters/fake-chapter/navigation")
    assert response.status_code == 200
    data = response.json()
    assert "prev" in data
    assert "next" in data


def test_chapter_fallback():
    response = client.get("/api/console/chapter/fake/fallback")
    assert response.status_code == 200
    data = response.json()
    assert "fallbackUsed" in data






