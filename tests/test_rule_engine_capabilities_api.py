"""Tests for visible rule engine capability reporting."""

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_rule_engine_capabilities_api():
    response = client.get("/api/admin/rule-engines")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    legado = next(item for item in data["items"] if item["id"] == "legado")
    capability_ids = {item["id"]: item for item in legado["capabilities"]}
    assert capability_ids["css_selector"]["status"] == "supported"
    assert capability_ids["xpath"]["status"] == "supported"
    assert capability_ids["jsonpath"]["status"] == "supported"
    assert capability_ids["safe_js_transform"]["status"] == "limited"
    assert capability_ids["webview"]["status"] == "unsupported"


def test_rule_engine_page_shows_capability_matrix():
    response = client.get("/admin/rule-engines")
    assert response.status_code == 200
    assert "能力矩阵" in response.text
    assert "JsonPath" in response.text
    assert "WebView" in response.text
