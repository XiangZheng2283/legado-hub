"""Tests for proxy fallback behavior."""

from unittest.mock import AsyncMock, patch

import pytest

from app.engine.fetcher import Fetcher
from app.engine.proxy import ProxyConfig, decide_proxy_mode, should_retry_with_proxy


def test_decide_proxy_mode() -> None:
    cfg = ProxyConfig(enabled=True, url="http://127.0.0.1:7890")
    assert decide_proxy_mode("never", cfg) == (True, False)
    assert decide_proxy_mode("always", cfg) == (False, True)
    assert decide_proxy_mode("auto", cfg) == (True, True)


def test_decide_proxy_mode_when_disabled() -> None:
    cfg = ProxyConfig(enabled=False, url="")
    assert decide_proxy_mode("always", cfg) == (False, False)
    assert decide_proxy_mode("auto", cfg) == (True, False)


def test_should_retry_with_proxy_status_code() -> None:
    cfg = ProxyConfig(enabled=True, url="http://p", retry_on_failure=True, failure_status_codes=[403, 502])
    assert should_retry_with_proxy(Exception("403 Forbidden"), cfg) is True
    assert should_retry_with_proxy(Exception("502 Bad Gateway"), cfg) is True
    assert should_retry_with_proxy(Exception("200 OK"), cfg) is False


def test_should_retry_with_proxy_keyword() -> None:
    cfg = ProxyConfig(enabled=True, url="http://p", retry_on_failure=True, failure_error_keywords=["timeout", "connection"])
    assert should_retry_with_proxy(Exception("ConnectTimeout"), cfg) is True
    assert should_retry_with_proxy(Exception("Connection reset"), cfg) is True
    assert should_retry_with_proxy(Exception("OK"), cfg) is False


@pytest.mark.anyio
async def test_fetcher_never_mode_no_proxy() -> None:
    fetcher = Fetcher(proxy_url="http://127.0.0.1:7890")
    with patch.object(fetcher, "_do_fetch", new_callable=AsyncMock) as mock_do:
        mock_do.return_value = ("ok", "http://example.com")
        result = await fetcher.fetch_with_proxy({"url": "http://example.com"}, proxy_mode="never")
        assert result.success is True
        assert result.proxy_used is False
        assert result.attempts == 1
        mock_do.assert_awaited_once()
    await fetcher.close()


@pytest.mark.anyio
async def test_fetcher_always_mode_uses_proxy() -> None:
    fetcher = Fetcher(proxy_url="http://127.0.0.1:7890")
    with patch.object(fetcher, "_do_fetch", new_callable=AsyncMock) as mock_do:
        mock_do.return_value = ("ok", "http://example.com")
        cfg = ProxyConfig(enabled=True, url="http://127.0.0.1:7890")
        result = await fetcher.fetch_with_proxy({"url": "http://example.com"}, proxy_mode="always", proxy_config=cfg)
        assert result.success is True
        assert result.proxy_used is True
        assert result.attempts == 1
    await fetcher.close()


@pytest.mark.anyio
async def test_fetcher_auto_fallback_to_proxy() -> None:
    fetcher = Fetcher(proxy_url="http://127.0.0.1:7890")
    with patch.object(fetcher, "_do_fetch", new_callable=AsyncMock) as mock_do:
        # First call (direct) fails with 403, second call (proxy) succeeds
        mock_do.side_effect = [
            Exception("403 Forbidden"),
            ("ok", "http://example.com"),
        ]
        cfg = ProxyConfig(enabled=True, url="http://127.0.0.1:7890", retry_on_failure=True, failure_status_codes=[403])
        result = await fetcher.fetch_with_proxy({"url": "http://example.com"}, proxy_mode="auto", proxy_config=cfg)
        assert result.success is True
        assert result.proxy_used is True
        assert result.attempts == 2
        assert "403" in result.direct_error
    await fetcher.close()


@pytest.mark.anyio
async def test_catalog_records_proxy_status(tmp_path) -> None:
    import sqlite3
    from app.services.cache import Cache
    from app.services.catalog import Catalog
    from app.storage.db import initialize_database

    db_path = tmp_path / "test.db"
    cache = Cache(db_path=db_path)
    initialize_database(db_path)

    from app.services.source_repository import SourceRepository
    repo = SourceRepository(db_path=db_path)

    # Insert a test source record so catalog can find it
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO source_health (source_id, book_source_name, book_source_url, enabled, health_status, proxy_mode) VALUES (?, ?, ?, ?, ?, ?)",
            ("biquges123-com", "测试书源", "https://test.com", 1, "healthy", "auto"),
        )
        conn.commit()

    catalog = Catalog(repo=repo, cache=cache)

    with patch("app.engine.fetcher.Fetcher.fetch_with_proxy", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value.text = "<html><body></body></html>"
        mock_fetch.return_value.final_url = "http://example.com"
        mock_fetch.return_value.proxy_used = False
        mock_fetch.return_value.success = True
        mock_fetch.return_value.attempts = 1
        mock_fetch.return_value.direct_error = ""
        mock_fetch.return_value.proxy_error = ""

        result = await catalog.search("test")
        attempts = repo.get_attempts("biquges123-com")
        assert len(attempts) > 0
