"""Tests for health and metadata endpoints."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_info() -> None:
    response = client.get("/api/info")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "LegadoHub"
    assert data["version"] == "0.0.1"
    assert data["phase"] == "plugin-runtime-stage-3"
    assert "paths" in data
    assert "project_root" in data["paths"]
