"""Reader entrypoint request and credential boundary regressions."""

from __future__ import annotations

import os
import stat
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from app.core.public_security import load_admin_security_config, load_public_security_config
from app.main import EntryPoint, create_app
from app.services.cookie_store import CookieStore
from app.services.user_auth import auth_service


READER_ORIGIN = "https://books.example.test"
LAN_READER_ORIGIN = "http://192.168.31.161:8765"
LAN_ADMIN_ORIGIN = "http://192.168.31.161:8766"


def _reader_config(monkeypatch):
    monkeypatch.setenv("LEGADOHUB_PUBLIC_BASE_URL", READER_ORIGIN)
    monkeypatch.setenv("LEGADOHUB_ALLOWED_HOSTS", "books.example.test")
    monkeypatch.setenv("LEGADOHUB_ALLOWED_ORIGINS", READER_ORIGIN)
    monkeypatch.setenv("LEGADOHUB_TRUSTED_PROXIES", "127.0.0.1/32")
    return load_public_security_config()


def _clear_network_config(monkeypatch) -> None:
    for name in (
        "LEGADOHUB_EXTERNAL_HOST",
        "LEGADOHUB_PUBLIC_BASE_URL",
        "LEGADOHUB_ALLOWED_HOSTS",
        "LEGADOHUB_ALLOWED_ORIGINS",
        "LEGADOHUB_ADMIN_BASE_URL",
        "LEGADOHUB_ADMIN_ALLOWED_HOSTS",
        "LEGADOHUB_ADMIN_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_external_host_extends_lan_access_without_allowing_arbitrary_hosts(monkeypatch) -> None:
    _clear_network_config(monkeypatch)
    external_host = "203.0.113.10"
    external_reader_origin = f"http://{external_host}:8765"
    external_admin_origin = f"http://{external_host}:8766"
    monkeypatch.setenv("LEGADOHUB_EXTERNAL_HOST", external_host)

    reader_security = load_public_security_config()
    admin_security = load_admin_security_config()
    assert reader_security.dynamic_base_url is True
    assert admin_security.dynamic_base_url is True
    assert reader_security.external_host == external_host
    assert admin_security.external_host == external_host

    reader_app = create_app(reader_security, manage_runtime=False)
    external_reader = TestClient(reader_app, base_url=external_reader_origin)
    external_manifest = external_reader.get("/api/subscribe/legado/source")
    assert external_manifest.status_code == 200
    assert external_manifest.json()[0]["searchUrl"].startswith(
        f"{external_reader_origin}/api/"
    )

    lan_reader = TestClient(reader_app, base_url=LAN_READER_ORIGIN)
    lan_manifest = lan_reader.get("/api/subscribe/legado/source")
    assert lan_manifest.status_code == 200
    assert lan_manifest.json()[0]["searchUrl"].startswith(f"{LAN_READER_ORIGIN}/api/")
    assert TestClient(reader_app, base_url="http://evil.invalid:8765").get(
        "/health"
    ).status_code == 400

    admin_app = create_app(
        admin_security,
        entrypoint=EntryPoint.ADMIN,
        manage_runtime=False,
    )
    assert TestClient(admin_app, base_url=external_admin_origin).post(
        "/api/missing",
        headers={"Origin": external_admin_origin},
    ).status_code == 404
    assert TestClient(admin_app, base_url=LAN_ADMIN_ORIGIN).post(
        "/api/missing",
        headers={"Origin": LAN_ADMIN_ORIGIN},
    ).status_code == 404


@pytest.mark.parametrize(
    "value",
    ("0.0.0.0", "::", "https://books.example.test", "books.example.test:8765", "*"),
)
def test_external_host_rejects_bind_addresses_and_non_host_values(
    monkeypatch,
    value: str,
) -> None:
    _clear_network_config(monkeypatch)
    monkeypatch.setenv("LEGADOHUB_EXTERNAL_HOST", value)

    with pytest.raises(RuntimeError, match="LEGADOHUB_EXTERNAL_HOST"):
        load_public_security_config()


@pytest.mark.parametrize(
    ("configured_host", "request_host", "normalized_host"),
    (
        ("books.example.test.", "books.example.test.:8765", "books.example.test"),
        ("2001:0db8::20", "[2001:db8::20]:8765", "2001:db8::20"),
    ),
)
def test_external_host_normalizes_equivalent_dns_and_ip_forms(
    monkeypatch,
    configured_host: str,
    request_host: str,
    normalized_host: str,
) -> None:
    _clear_network_config(monkeypatch)
    monkeypatch.setenv("LEGADOHUB_EXTERNAL_HOST", configured_host)
    security = load_public_security_config()
    app = create_app(security, manage_runtime=False)

    assert security.external_host == normalized_host
    assert TestClient(app).get("/health", headers={"Host": request_host}).status_code == 200


def test_default_lan_uses_request_host_and_rejects_public_host(monkeypatch) -> None:
    _clear_network_config(monkeypatch)
    public_app = create_app(load_public_security_config())

    lan_client = TestClient(public_app, base_url=LAN_READER_ORIGIN)
    manifest = lan_client.get("/api/subscribe/legado/source")
    assert manifest.status_code == 200
    assert manifest.json()[0]["searchUrl"].startswith(f"{LAN_READER_ORIGIN}/api/")

    public_client = TestClient(public_app, base_url="http://203.0.113.10:8765")
    assert public_client.get("/health").status_code == 400

    arbitrary_name_client = TestClient(public_app, base_url="http://evil:8765")
    assert arbitrary_name_client.get("/health").status_code == 400
    assert arbitrary_name_client.get(
        "/health",
        headers={"Host": "192.168.31.161:99999"},
    ).status_code == 400
    assert arbitrary_name_client.get(
        "/health",
        headers={"Host": "[fe80::1%25eth0]:8765"},
    ).status_code == 400

    local_name_client = TestClient(public_app, base_url="http://reader.home.arpa:8765")
    assert local_name_client.get("/health").status_code == 200

    ipv6_client = TestClient(public_app)
    ipv6_manifest = ipv6_client.get(
        "/api/subscribe/legado/source",
        headers={"Host": "[fd00::20]:8765"},
    )
    assert ipv6_manifest.status_code == 200
    assert ipv6_manifest.json()[0]["searchUrl"].startswith(
        "http://[fd00::20]:8765/api/"
    )


def test_default_lan_admin_accepts_same_origin_only(monkeypatch) -> None:
    _clear_network_config(monkeypatch)
    admin_app = create_app(
        load_admin_security_config(),
        entrypoint=EntryPoint.ADMIN,
        manage_runtime=False,
    )
    client = TestClient(admin_app, base_url=LAN_ADMIN_ORIGIN)

    assert client.post("/api/missing", headers={"Origin": LAN_ADMIN_ORIGIN}).status_code == 404
    assert client.post(
        "/api/missing",
        headers={"Origin": "http://192.168.31.99:8766"},
    ).status_code == 403


def test_reader_config_derives_https_and_rejects_wildcard_hosts(monkeypatch) -> None:
    security = _reader_config(monkeypatch)
    assert security.require_https is True
    assert security.enforce_origin is True

    monkeypatch.setenv("LEGADOHUB_ALLOWED_HOSTS", "*")
    with pytest.raises(RuntimeError, match="without wildcards"):
        load_public_security_config()


def test_reader_app_rejects_host_and_forwarded_spoof_and_uses_fixed_urls(monkeypatch) -> None:
    public_app = create_app(_reader_config(monkeypatch))
    secure_client = TestClient(public_app, base_url=READER_ORIGIN)

    assert secure_client.get("/health").status_code == 200
    assert secure_client.get("/health", headers={"Host": "evil.invalid"}).status_code == 400
    manifest = secure_client.get(
        "/api/subscribe/legado/source",
        headers={"X-Forwarded-Host": "evil.invalid"},
    )
    assert manifest.status_code == 200
    source = manifest.json()[0]
    assert source["searchUrl"].startswith(f"{READER_ORIGIN}/api/")
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


def test_https_reader_cookie_writes_require_origin_but_bearer_does_not(monkeypatch) -> None:
    public_app = create_app(_reader_config(monkeypatch))
    browser = TestClient(public_app, base_url=READER_ORIGIN)
    login = browser.post(
        "/api/auth/login",
        headers={"Origin": READER_ORIGIN},
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
        headers={"Origin": READER_ORIGIN},
    ).status_code == 200

    created = auth_service.create_access_user(f"public-{uuid.uuid4().hex[:10]}")
    redemption_client = TestClient(public_app, base_url=READER_ORIGIN)
    redeemed = redemption_client.post(
        "/api/auth/access/redeem",
        json={"accessCode": created["accessCode"]},
    )
    assert redeemed.status_code == 200
    bearer = TestClient(public_app, base_url=READER_ORIGIN)
    assert bearer.post(
        "/api/auth/access/logout",
        headers={"Authorization": f"Bearer {redeemed.json()['token']}"},
    ).status_code == 200


def test_trusted_proxy_client_ip_ignores_spoofed_leftmost_values(monkeypatch) -> None:
    monkeypatch.setenv("LEGADOHUB_PUBLIC_BASE_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("LEGADOHUB_ALLOWED_HOSTS", "127.0.0.1")
    monkeypatch.setenv("LEGADOHUB_ALLOWED_ORIGINS", "http://127.0.0.1:8765")
    monkeypatch.setenv("LEGADOHUB_TRUSTED_PROXIES", "10.0.0.0/24")
    security = load_public_security_config()
    assert security.require_https is False
    assert security.enforce_origin is False
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
