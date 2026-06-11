"""Tests for plugin data contract models."""

import pytest

from app.source_plugins.models import PluginMetadata, SearchResult, BookDetail, ChapterItem, ChapterContent
from app.source_plugins.errors import PluginValidationError


def test_valid_metadata():
    meta = PluginMetadata(
        contract_version="1.0",
        id="test_plugin",
        name="测试书源",
        version="0.1.0",
        type="source",
        domains=["example.com"],
        base_urls=["https://example.com"],
        capabilities=["search", "detail", "toc", "chapter"],
        auth={"mode": "none", "cookieDomains": []},
        content={"access": "free"},
        tags=["html", "no-login"],
    )
    errors = meta.validate()
    assert not errors


def test_invalid_contract_version():
    meta = PluginMetadata(
        contract_version="2.0",
        id="test",
        name="Test",
        version="0.1.0",
        type="source",
        domains=["example.com"],
        base_urls=["https://example.com"],
        capabilities=["search"],
        auth={"mode": "none"},
        content={"access": "free"},
        tags=[],
    )
    errors = meta.validate()
    assert any("contractVersion" in e for e in errors)


def test_invalid_capability():
    meta = PluginMetadata(
        contract_version="1.0",
        id="test",
        name="Test",
        version="0.1.0",
        type="source",
        domains=["example.com"],
        base_urls=["https://example.com"],
        capabilities=["search", "magic"],
        auth={"mode": "none"},
        content={"access": "free"},
        tags=[],
    )
    errors = meta.validate()
    assert any("magic" in e for e in errors)


def test_invalid_auth_mode():
    meta = PluginMetadata(
        contract_version="1.0",
        id="test",
        name="Test",
        version="0.1.0",
        type="source",
        domains=["example.com"],
        base_urls=["https://example.com"],
        capabilities=["search"],
        auth={"mode": "unknown"},
        content={"access": "free"},
        tags=[],
    )
    errors = meta.validate()
    assert any("auth.mode" in e for e in errors)


def test_official_source_metadata():
    meta = PluginMetadata(
        contract_version="1.0",
        id="qidian",
        name="起点中文网",
        version="0.1.0",
        type="source",
        domains=["qidian.com"],
        base_urls=["https://www.qidian.com"],
        capabilities=["search", "detail", "toc", "chapter"],
        auth={
            "mode": "optional",
            "loginUrl": "https://www.qidian.com",
            "accountRequiredFor": ["paid_chapter"],
            "cookieDomains": ["qidian.com"],
        },
        content={"access": "mixed", "paid": "supported_after_login"},
        tags=["official", "login", "paid", "json-api"],
    )
    errors = meta.validate()
    assert not errors


def test_metadata_rejects_explore_for_ordinary_source():
    meta = PluginMetadata(
        contract_version="1.0",
        id="ordinary",
        name="普通书源",
        version="0.1.0",
        type="source",
        domains=["example.com"],
        base_urls=["https://example.com"],
        capabilities=["search", "detail", "toc", "chapter", "explore"],
        auth={"mode": "none"},
        content={"access": "free"},
        tags=["html"],
    )

    assert "explore capability is only allowed for official sources" in meta.validate()


def test_metadata_accepts_access_strategy():
    meta = PluginMetadata.from_dict({
        "contractVersion": "1.0",
        "id": "example",
        "name": "示例",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search", "detail", "toc", "chapter"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "tags": ["html"],
        "accessBridge": {
            "search": {"providers": ["duckduckgo_ddgs", "bing_html"]},
            "browser": {"runtime": "chromium", "headless": True},
        },
        "accessStrategy": {
            "search": "search_provider",
            "detail": "stealth_http",
            "toc": "stealth_http",
            "chapter": "stealth_http",
        },
        "searchProvider": {
            "providerOrder": ["duckduckgo_ddgs", "bing_html"],
            "targetDomain": "www.example.com",
            "urlPatterns": [r"/book/\d+\.htm"],
        },
    })

    assert meta.access_strategy["search"] == "search_provider"
    assert meta.access_bridge["browser"]["runtime"] == "chromium"
    assert meta.search_provider["targetDomain"] == "www.example.com"
    assert meta.validate() == []


def test_metadata_rejects_invalid_access_strategy():
    meta = PluginMetadata.from_dict({
        "contractVersion": "1.0",
        "id": "example",
        "name": "示例",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "tags": [],
        "accessStrategy": {"search": "random_fallback"},
    })

    assert "invalid accessStrategy.search: random_fallback" in meta.validate()


def test_metadata_rejects_invalid_access_strategy_stage():
    meta = PluginMetadata.from_dict({
        "contractVersion": "1.0",
        "id": "example",
        "name": "示例",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "tags": [],
        "accessStrategy": {"login": "browser"},
    })

    assert "invalid accessStrategy stage: login" in meta.validate()


def test_metadata_uses_search_provider_from_access_strategy():
    meta = PluginMetadata.from_dict({
        "contractVersion": "1.0",
        "id": "example",
        "name": "示例",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "tags": [],
        "browser": {"mode": "required"},
        "accessStrategy": {"search": "search_provider"},
    })

    assert meta.access_mode("search") == "search_provider"
    assert meta.uses_search_provider("search") is True


def test_metadata_does_not_use_old_browser_search_fallback():
    meta = PluginMetadata.from_dict({
        "contractVersion": "1.0",
        "id": "example",
        "name": "示例",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "tags": [],
        "browser": {"searchFallback": "search_provider"},
    })

    assert meta.uses_search_provider("search") is False


def test_metadata_rejects_old_search_engine_strategy():
    meta = PluginMetadata.from_dict({
        "contractVersion": "1.0",
        "id": "example",
        "name": "示例",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "tags": [],
        "accessStrategy": {"search": "search_engine"},
    })

    assert "invalid accessStrategy.search: search_engine" in meta.validate()


def test_paid_chapter_serialization():
    ch = ChapterContent(
        source_id="qidian",
        title="第1章",
        chapter_url="https://example.com/1",
        content="",
        auth_required=True,
        is_paid=True,
    )
    d = ch.to_dict()
    assert d["authRequired"] is True
    assert d["isPaid"] is True
    assert d["content"] == ""


def test_search_result_serialization():
    sr = SearchResult(
        source_id="test",
        name="凡人修仙传",
        author="忘语",
        book_url="https://example.com/book/1",
    )
    d = sr.to_dict()
    assert d["sourceId"] == "test"
    assert d["name"] == "凡人修仙传"
    assert d["author"] == "忘语"






