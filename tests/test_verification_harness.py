"""Tests for verification harness."""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.storage.db import initialize_database
from app.services.verification_harness import VerificationHarness

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr("app.config.DB_PATH", db)
    monkeypatch.setattr("app.services.source_repository.DB_PATH", db)
    monkeypatch.setattr("app.services.cache.DB_PATH", db)
    initialize_database(db)
    yield


def test_api_simulations():
    harness = VerificationHarness()
    report = harness.run_api_simulations()
    assert report["summary"]["total"] > 0
    assert report["summary"]["passed"] > 0
    assert report["summary"]["failed"] == 0


def test_ui_simulations():
    harness = VerificationHarness()
    report = harness.run_ui_simulations()
    assert report["summary"]["total"] > 0
    assert report["summary"]["passed"] > 0
    assert report["summary"]["failed"] == 0


def test_verification_records_failed_assertions():
    harness = VerificationHarness()
    harness.check("api", "forced_failure", lambda: (_ for _ in ()).throw(AssertionError("真实失败")))
    report = harness.get_report()
    assert report["summary"]["failed"] == 1
    assert report["items"][0]["passed"] is False
    assert "真实失败" in report["items"][0]["details"]


def test_verification_api():
    response = client.get("/api/admin/verification")
    assert response.status_code == 200


def test_verification_run_api():
    response = client.post("/api/admin/verification/run", json={"category": "api"})
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
