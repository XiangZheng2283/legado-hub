"""Public deployment request and credential boundary regressions."""

from __future__ import annotations

import os
import stat
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.core.public_security import load_public_security_config
from app.main import create_app
from app.services.cookie_store import CookieStore
from app.services.user_auth import auth_service


PUBLIC_ORIGIN = "https://books.example.test"


def _public_config(monkeypatch):
    monkeypatch.setenv("LEGADOHUB_PUBLIC_MODE", "1")
    monkeypatch.setenv("LEGADOHUB_PUBLIC_BASE_URL", PUBLIC_ORIGIN)
    monkeypatch.setenv("LEGADOHUB_ALLOWED_HOSTS", "books.example.test")
    monkeypatch.setenv("LEGADOHUB_ALLOWED_ORIGINS", PUBLIC_ORIGIN)
    monkeypatch.setenv("LEGADOHUB_TRUSTED_PROXIES", "127.0.0.1/32")
    monkeypatch.setenv("LEGADOHUB_BROWSER_DISABLE_SANDBOX", "0")
    return load_public_security_config()


def test_public_config_requires_https_exact_hosts_and_trusted_proxy(monkeypatch) -> None:
    monkeypatch.setenv("LEGADOHUB_PUBLIC_MODE", "1")
    monkeypatch.delenv("LEGADOHUB_PUBLIC_BASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="PUBLIC_BASE_URL is required"):
        load_public_security_config()

    monkeypatch.setenv("LEGADOHUB_PUBLIC_BASE_URL", "http://books.example.test")
    monkeypatch.setenv("LEGADOHUB_ALLOWED_HOSTS", "books.example.test")
    monkeypatch.setenv("LEGADOHUB_ALLOWED_ORIGINS", "http://books.example.test")
    monkeypatch.setenv("LEGADOHUB_TRUSTED_PROXIES", "127.0.0.1/32")
    with pytest.raises(RuntimeError, match="must use HTTPS"):
        load_public_security_config()

    monkeypatch.setenv("LEGADOHUB_PUBLIC_BASE_URL", PUBLIC_ORIGIN)
    monkeypatch.setenv("LEGADOHUB_ALLOWED_HOSTS", "*")
    monkeypatch.setenv("LEGADOHUB_ALLOWED_ORIGINS", PUBLIC_ORIGIN)
    with pytest.raises(RuntimeError, match="without wildcards"):
        load_public_security_config()

    monkeypatch.setenv("LEGADOHUB_ALLOWED_HOSTS", "books.example.test")
    monkeypatch.delenv("LEGADOHUB_TRUSTED_PROXIES", raising=False)
    with pytest.raises(RuntimeError, match="TRUSTED_PROXIES is required"):
        load_public_security_config()


def test_public_app_rejects_host_and_forwarded_spoof_and_uses_fixed_urls(monkeypatch) -> None:
    public_app = create_app(_public_config(monkeypatch))
    secure_client = TestClient(public_app, base_url=PUBLIC_ORIGIN)

    assert secure_client.get("/health").status_code == 200
    assert secure_client.get("/health", headers={"Host": "evil.invalid"}).status_code == 400
    manifest = secure_client.get(
        "/api/subscribe/legado/source",
        headers={"X-Forwarded-Host": "evil.invalid"},
    )
    assert manifest.status_code == 200
    source = manifest.json()[0]
    assert source["searchUrl"].startswith(f"{PUBLIC_ORIGIN}/api/")
    assert "evil.invalid" not in str(source)
    assert manifest.headers["cache-control"] == "no-store"
    assert manifest.headers["x-content-type-options"] == "nosniff"
    assert "max-age=31536000" in manifest.headers["strict-transport-security"]

    insecure_client = TestClient(public_app, base_url="http://books.example.test")
    rejected = insecure_client.get(
        "/api/subscribe/legado/source",
        headers={"X-Forwarded-Proto": "https"},
    )
    assert rejected.status_code == 400


def test_public_cookie_writes_require_origin_but_bearer_does_not(monkeypatch) -> None:
    public_app = create_app(_public_config(monkeypatch))
    browser = TestClient(public_app, base_url=PUBLIC_ORIGIN)
    login = browser.post(
        "/api/auth/login",
        headers={"Origin": PUBLIC_ORIGIN},
        json={"username": "admin", "password": "admin123"},
    )
    assert login.status_code == 200
    cookie = login.headers["set-cookie"]
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie

    assert browser.post("/api/auth/logout").status_code == 403
    assert browser.post(
        "/api/auth/logout",
        headers={"Origin": "https://evil.invalid"},
    ).status_code == 403
    assert browser.post(
        "/api/auth/logout",
        headers={"Origin": PUBLIC_ORIGIN},
    ).status_code == 200

    created = auth_service.create_access_user(f"public-{uuid.uuid4().hex[:10]}")
    redemption_client = TestClient(public_app, base_url=PUBLIC_ORIGIN)
    redeemed = redemption_client.post(
        "/api/auth/access/redeem",
        json={"accessCode": created["accessCode"]},
    )
    assert redeemed.status_code == 200
    bearer = TestClient(public_app, base_url=PUBLIC_ORIGIN)
    assert bearer.post(
        "/api/auth/access/logout",
        headers={"Authorization": f"Bearer {redeemed.json()['token']}"},
    ).status_code == 200


def test_trusted_proxy_client_ip_ignores_spoofed_leftmost_values(monkeypatch) -> None:
    monkeypatch.setenv("LEGADOHUB_PUBLIC_MODE", "0")
    monkeypatch.setenv("LEGADOHUB_PUBLIC_BASE_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("LEGADOHUB_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("LEGADOHUB_ALLOWED_ORIGINS", "http://127.0.0.1:8765")
    monkeypatch.setenv("LEGADOHUB_TRUSTED_PROXIES", "10.0.0.0/24")
    security = load_public_security_config()
    request = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.2"),
        headers=Headers({"X-Forwarded-For": "203.0.113.99, 198.51.100.25"}),
    )
    assert security.client_ip(request) == "198.51.100.25"

    oversized_chain = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.2"),
        headers=Headers({"X-Forwarded-For": ", ".join(["198.51.100.1"] * 17)}),
    )
    assert security.client_ip(oversized_chain) == "10.0.0.2"

    ambiguous_proto = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.2"),
        url=SimpleNamespace(scheme="http"),
        headers=Headers({"X-Forwarded-Proto": "https,http"}),
    )
    assert security.request_is_https(ambiguous_proto) is False


def test_cookie_store_rejects_path_traversal_and_uses_private_modes(tmp_path) -> None:
    store = CookieStore(tmp_path / "cookies")
    with pytest.raises(ValueError, match="Invalid plugin id"):
        store.save("../../outside", {"secret": "no"})

    store.save("safe_plugin", {"cookie": "value"})
    assert store.load("safe_plugin") == {"cookie": "value"}
    if os.name != "nt":
        assert stat.S_IMODE(store.base_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(store.path_for("safe_plugin").stat().st_mode) == 0o600
