"""Tests for project-managed source subscriptions and rule engine audit."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.rule_engine_audit import RuleEngineAuditService
from app.services.source_repository import SourceRepository
from app.services.source_subscriptions import SourceSubscriptionService
from app.storage.db import initialize_database


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    monkeypatch.setattr("app.config.DB_PATH", db)
    monkeypatch.setattr("app.services.source_repository.DB_PATH", db)
    monkeypatch.setattr("app.services.cache.DB_PATH", db)
    initialize_database(db)
    with TestClient(app) as c:
        yield c


def test_source_subscriptions_api_has_builtins(client) -> None:
    response = client.get("/api/admin/source-subscriptions")
    assert response.status_code == 200
    data = response.json()
    ids = {item["id"] for item in data["items"]}
    assert "xiu2_yuedu" in ids
    assert "yiove_collections" in ids


def test_admin_source_subscriptions_page(client) -> None:
    response = client.get("/admin/source-subscriptions")
    assert response.status_code == 200
    assert "订阅源管理" in response.text
    assert "项目内订阅连接" in response.text


def test_add_subscription_persists(tmp_path) -> None:
    config_path = tmp_path / "source_subscriptions.json"
    config_path.write_text(json.dumps({"version": 1, "subscriptions": []}), encoding="utf-8")
    service = SourceSubscriptionService(config_path=config_path, target_dir=tmp_path / "sources")

    item = service.add_subscription({"name": "测试订阅", "url": "https://example.com/source.json"})

    assert item["id"] == "测试订阅"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["subscriptions"][0]["url"] == "https://example.com/source.json"
    assert data["subscriptions"][0]["built_in"] is False


@pytest.mark.asyncio
async def test_sync_subscription_writes_sources_and_rescans(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    initialize_database(db_path)
    target_dir = tmp_path / "legado"
    config_path = tmp_path / "source_subscriptions.json"
    config_path.write_text(
        json.dumps({
            "version": 1,
            "rescan_after_sync": True,
            "subscriptions": [{
                "id": "demo",
                "name": "Demo",
                "engine": "legado",
                "kind": "direct_json",
                "url": "https://example.com/demo.json",
                "enabled": True,
            }],
        }),
        encoding="utf-8",
    )
    repo = SourceRepository(repo_dir=target_dir, db_path=db_path)
    service = SourceSubscriptionService(config_path=config_path, target_dir=target_dir, repo=repo)

    async def fake_fetch_text(url: str) -> str:
        return json.dumps([{
            "bookSourceName": "Demo Source",
            "bookSourceUrl": "https://demo.example",
            "searchUrl": "/search?key={{key}}",
            "ruleSearch": {"bookList": "div.book"},
            "ruleBookInfo": {"name": "h1@text"},
            "ruleToc": {"chapterList": "ul li"},
            "ruleContent": {"content": "div.content@text"},
        }])

    monkeypatch.setattr(service, "_fetch_text", fake_fetch_text)
    result = await service.sync_subscription("demo")

    assert result["ok"] is True
    assert result["count"] == 1
    assert (target_dir / "sub-demo.json").exists()
    assert repo.get_stats()["enabled"] == 1
    source = repo.get_source("sub-demo")
    assert source is not None
    assert source["subscriptionId"] == "demo"
    assert source["upstreamUrl"] == "https://example.com/demo.json"


def test_rule_engine_audit_classifies_source_defect() -> None:
    audit = RuleEngineAuditService().audit_raw_source({"bookSourceName": "Bad"})
    assert audit["classification"] == "source_defect"
    assert audit["sourceDefects"]


def test_rule_engine_audit_classifies_engine_gap() -> None:
    audit = RuleEngineAuditService().audit_raw_source({
        "bookSourceName": "JS Source",
        "bookSourceUrl": "https://js.example",
        "searchUrl": "/s?key={{key}}",
        "ruleSearch": {"bookList": "class.book", "name": "@js:result"},
        "ruleBookInfo": {"name": "h1@text"},
        "ruleToc": {"chapterList": "ul li"},
        "ruleContent": {"content": "<js>java.log('x')</js>"},
    })
    assert audit["classification"] == "engine_gap"
    assert audit["engineGaps"]


def test_rule_audit_api_and_page(client) -> None:
    api_response = client.get("/api/admin/rule-audit?limit=5")
    assert api_response.status_code == 200
    assert "items" in api_response.json()
    page_response = client.get("/admin/rule-audit")
    assert page_response.status_code == 200
    assert "规则引擎审查" in page_response.text
