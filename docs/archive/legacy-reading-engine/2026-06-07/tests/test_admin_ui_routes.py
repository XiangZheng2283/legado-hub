"""Tests for admin UI route responses (new React frontend)."""

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


PAGES = [
    "/admin",
    "/admin/plugins",
    "/admin/search",
    "/admin/cache",
    "/admin/settings",
    "/admin/aggregate-source",
    "/admin/verification",
]


@pytest.mark.parametrize("path", PAGES)
def test_admin_page_200(path):
    response = client.get(path)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "LegadoHub" in response.text


def test_admin_page_title():
    response = client.get("/admin")
    assert response.status_code == 200
    assert "LegadoHub 管理后台" in response.text
