"""Reader/admin request, URL, proxy, and filesystem security boundaries."""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import config

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SESSION_COOKIE_NAME = "legadohub_session"
_DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_MAX_FORWARDED_CHAIN_LENGTH = 16
_MAX_FORWARDED_HEADER_LENGTH = 1024
_LAN_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "10.0.0.0/8",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)
_LAN_DNS_SUFFIXES = (".home", ".home.arpa", ".lan", ".local")
logger = logging.getLogger(__name__)
_SECURITY_LOG_INTERVAL_SECONDS = 60
_security_log_lock = threading.Lock()
_security_last_log: dict[str, float] = {}


def _csv(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def _normalize_host(host: str) -> str:
    normalized = host.strip().lower().rstrip(".")
    try:
        address = ipaddress.ip_address(normalized)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return str(address)
    except ValueError:
        return normalized


def _origin(value: str, *, label: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError(f"{label} must be an absolute HTTP(S) origin.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError(f"{label} must not contain credentials, query, or fragment.")
    if parsed.path not in {"", "/"}:
        raise RuntimeError(f"{label} must not contain a path.")
    host = _normalize_host(parsed.hostname)
    if not _valid_host(host):
        raise RuntimeError(f"{label} contains an invalid host name.")
    default_port = 443 if parsed.scheme == "https" else 80
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError(f"{label} contains an invalid port.") from exc
    port_suffix = f":{port}" if port and port != default_port else ""
    rendered_host = f"[{host}]" if ":" in host else host
    return f"{parsed.scheme}://{rendered_host}{port_suffix}", host


def _valid_host(host: str) -> bool:
    if "%" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if len(host) > 253 or not host.isascii():
        return False
    labels = host.rstrip(".").split(".")
    return bool(labels) and all(_DNS_LABEL_PATTERN.fullmatch(label) for label in labels)


def _networks(values: Iterable[str]) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for value in values:
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError as exc:
            raise RuntimeError(f"Invalid trusted proxy network: {value}") from exc
    return tuple(networks)


@dataclass(frozen=True)
class PublicSecurityConfig:
    public_base_url: str
    allowed_hosts: tuple[str, ...]
    allowed_origins: frozenset[str]
    trusted_proxies: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    dynamic_base_url: bool = False
    require_https: bool = False
    enforce_origin: bool = False
    # Reader entry only: public Host must match settings allowlist.
    enforce_reading_public_allowlist: bool = False

    def is_trusted_proxy(self, host: str) -> bool:
        try:
            address = ipaddress.ip_address(str(host or "").strip())
        except ValueError:
            return False
        return any(address in network for network in self.trusted_proxies)

    def request_is_https(self, request: Request) -> bool:
        if request.url.scheme == "https":
            return True
        client_host = request.client.host if request.client else ""
        if not self.is_trusted_proxy(client_host):
            return False
        forwarded_values = request.headers.getlist("x-forwarded-proto")
        if len(forwarded_values) != 1 or "," in forwarded_values[0]:
            return False
        return forwarded_values[0].strip().lower() == "https"

    def client_ip(self, request: Request) -> str:
        immediate = request.client.host if request.client and request.client.host else "unknown"
        if not self.is_trusted_proxy(immediate):
            return immediate
        forwarded_values = request.headers.getlist("x-forwarded-for")
        if len(forwarded_values) != 1:
            return immediate
        if len(forwarded_values[0]) > _MAX_FORWARDED_HEADER_LENGTH:
            return immediate
        values = forwarded_values[0].split(",")
        if not values or len(values) > _MAX_FORWARDED_CHAIN_LENGTH:
            return immediate
        chain: list[str] = []
        for value in values:
            candidate = value.strip()
            if not candidate:
                return immediate
            try:
                chain.append(str(ipaddress.ip_address(candidate)))
            except ValueError:
                return immediate
        for candidate in reversed(chain):
            if not self.is_trusted_proxy(candidate):
                return candidate
        return immediate


def load_public_security_config() -> PublicSecurityConfig:
    configured_base = os.getenv("LEGADOHUB_PUBLIC_BASE_URL", "").strip().rstrip("/")
    dynamic_base_url = not configured_base
    base_url, base_host = _origin(
        configured_base or f"http://{config.HOST}:{config.PORT}",
        label="LEGADOHUB_PUBLIC_BASE_URL",
    )
    require_https = base_url.startswith("https://")

    hosts = _csv("LEGADOHUB_ALLOWED_HOSTS")
    if not hosts:
        hosts = [] if dynamic_base_url else [base_host, "localhost", "testserver"]
    normalized_hosts: list[str] = []
    for host in hosts:
        normalized = _normalize_host(host)
        if not normalized or "*" in normalized or not _valid_host(normalized):
            raise RuntimeError("LEGADOHUB_ALLOWED_HOSTS must contain exact host names without wildcards.")
        normalized_hosts.append(normalized)
    if not dynamic_base_url and base_host not in normalized_hosts:
        raise RuntimeError("LEGADOHUB_ALLOWED_HOSTS must include the public base URL host.")

    origin_values = _csv("LEGADOHUB_ALLOWED_ORIGINS")
    if not origin_values and not dynamic_base_url:
        origin_values = [base_url]
    origins = frozenset(_origin(value.rstrip("/"), label="LEGADOHUB_ALLOWED_ORIGINS")[0] for value in origin_values)
    if not dynamic_base_url and base_url not in origins:
        raise RuntimeError("LEGADOHUB_ALLOWED_ORIGINS must include LEGADOHUB_PUBLIC_BASE_URL.")

    proxy_values = _csv("LEGADOHUB_TRUSTED_PROXIES") or ["127.0.0.1/32", "::1/128"]
    trusted_proxies = _networks(proxy_values)
    return PublicSecurityConfig(
        public_base_url=base_url,
        allowed_hosts=tuple(dict.fromkeys(normalized_hosts)),
        allowed_origins=origins,
        trusted_proxies=trusted_proxies,
        dynamic_base_url=dynamic_base_url,
        require_https=require_https,
        enforce_origin=require_https,
        enforce_reading_public_allowlist=True,
    )


def load_admin_security_config() -> PublicSecurityConfig:
    """Load the isolated management listener's host, origin, and proxy policy."""
    configured_base = os.getenv("LEGADOHUB_ADMIN_BASE_URL", "").strip().rstrip("/")
    dynamic_base_url = not configured_base
    base_url, base_host = _origin(
        configured_base or f"http://127.0.0.1:{config.ADMIN_PORT}",
        label="LEGADOHUB_ADMIN_BASE_URL",
    )
    require_https = base_url.startswith("https://")

    hosts = _csv("LEGADOHUB_ADMIN_ALLOWED_HOSTS")
    if not hosts and not dynamic_base_url:
        hosts = [base_host, "127.0.0.1", "localhost", "testserver"]
    normalized_hosts: list[str] = []
    for host in hosts:
        normalized = _normalize_host(host)
        if not normalized or "*" in normalized or not _valid_host(normalized):
            raise RuntimeError(
                "LEGADOHUB_ADMIN_ALLOWED_HOSTS must contain exact host names without wildcards."
            )
        normalized_hosts.append(normalized)
    if not dynamic_base_url and base_host not in normalized_hosts:
        raise RuntimeError(
            "LEGADOHUB_ADMIN_ALLOWED_HOSTS must include the admin base URL host."
        )

    origin_values = _csv("LEGADOHUB_ADMIN_ALLOWED_ORIGINS")
    if not origin_values and not dynamic_base_url:
        origin_values = [base_url]
    origins = frozenset(
        _origin(value.rstrip("/"), label="LEGADOHUB_ADMIN_ALLOWED_ORIGINS")[0]
        for value in origin_values
    )
    if not dynamic_base_url and base_url not in origins:
        raise RuntimeError(
            "LEGADOHUB_ADMIN_ALLOWED_ORIGINS must include LEGADOHUB_ADMIN_BASE_URL."
        )

    proxy_values = _csv("LEGADOHUB_ADMIN_TRUSTED_PROXIES") or ["127.0.0.1/32", "::1/128"]
    return PublicSecurityConfig(
        public_base_url=base_url,
        allowed_hosts=tuple(dict.fromkeys(normalized_hosts)),
        allowed_origins=origins,
        trusted_proxies=_networks(proxy_values),
        dynamic_base_url=dynamic_base_url,
        require_https=require_https,
        enforce_origin=True,
        enforce_reading_public_allowlist=False,
    )


def _is_default_allowed_host(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return _valid_host(host) and (
            host in {"localhost", "testserver"} or host.endswith(_LAN_DNS_SUFFIXES)
        )
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is None:
            return not address.is_unspecified and not address.is_multicast
        address = address.ipv4_mapped
    return any(
        address.version == network.version and address in network
        for network in _LAN_NETWORKS
    )


def _dynamic_host_client_allowed(request: Request) -> bool | None:
    immediate = request.client.host if request.client and request.client.host else ""
    normalized = _normalize_host(immediate)
    try:
        ipaddress.ip_address(normalized)
    except ValueError:
        # ASGI tests and internal transports may identify clients by name.
        return None
    return _is_default_allowed_host(normalized)


def _request_origin(request: Request, security: PublicSecurityConfig) -> str:
    scheme = "https" if security.request_is_https(request) else request.url.scheme.lower()
    if scheme not in {"http", "https"}:
        raise RuntimeError("Request scheme is not HTTP(S).")
    origin, host = _origin(
        f"{scheme}://{request.headers.get('host', '').strip()}",
        label="Host",
    )
    client_allowed = _dynamic_host_client_allowed(request)
    if client_allowed is False or (
        client_allowed is None and not _is_default_allowed_host(host)
    ):
        raise RuntimeError(
            "Dynamic Host requires a local/private IPv4 or valid IPv6 client."
        )
    # Reader entry: public hostnames (CF/domain) only when allowlisted in settings.
    # LAN/localhost Hosts keep working without registration. Admin entry skips this.
    if security.enforce_reading_public_allowlist and not _is_default_allowed_host(host):
        allowlist = reading_public_base_allowlist()
        if not allowlist or origin not in allowlist:
            raise RuntimeError("Public Host is not allowlisted")
    return origin


def reading_public_base_allowlist() -> frozenset[str]:
    """Operator-registered public reading origins (settings UI). Empty = no public Host."""
    try:
        from app.core.app_config import AppConfig

        configured = str(AppConfig.get().reading_access.public_base_url or "").strip()
    except Exception:
        return frozenset()
    if not configured:
        return frozenset()
    try:
        return frozenset({normalize_public_base_url(configured)})
    except RuntimeError:
        # Stale/invalid stored values do not open the public gate.
        return frozenset()


def get_public_base_url(request: Request | None = None) -> str:
    """Resolve the reading base for this request (or offline default).

    Priority for live requests:
    1. Fixed env ``LEGADOHUB_PUBLIC_BASE_URL`` when set (non-dynamic mode)
    2. Request Host + trusted ``X-Forwarded-Proto`` (dynamic mode), subject to
       public-host allowlist from settings

    Settings ``readingAccess.publicBaseUrl`` is a whitelist for public Hosts,
    not a force-rewrite of every generated source.
    """
    security = (
        getattr(request.app.state, "public_security", None)
        if request is not None
        else None
    ) or load_public_security_config()
    if request is not None:
        if security.dynamic_base_url:
            return _request_origin(request, security)
        return security.public_base_url
    if not security.dynamic_base_url:
        return security.public_base_url
    # Offline/script path: never invent a public origin from the allowlist alone.
    return security.public_base_url


def normalize_public_base_url(value: str) -> str:
    return _origin(str(value or "").strip().rstrip("/"), label="public base URL")[0]


def request_uses_https(request: Request) -> bool:
    security = getattr(request.app.state, "public_security", None) or load_public_security_config()
    return bool(security.require_https or security.request_is_https(request))


def request_client_ip(request: Request) -> str:
    security = getattr(request.app.state, "public_security", None) or load_public_security_config()
    return security.client_ip(request)


def _apply_response_headers(response, security: PublicSecurityConfig, *, api_response: bool) -> None:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
    if api_response:
        response.headers["Cache-Control"] = "no-store"
    if security.require_https:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")


def _security_rejection(
    *,
    security: PublicSecurityConfig,
    request_id: str,
    event: str,
    status_code: int,
    detail: str,
    api_response: bool,
) -> JSONResponse:
    now = time.monotonic()
    should_log = False
    with _security_log_lock:
        last_logged = _security_last_log.get(event, 0.0)
        if now - last_logged >= _SECURITY_LOG_INTERVAL_SECONDS:
            _security_last_log[event] = now
            should_log = True
    if should_log:
        logger.warning("Security request rejected: event=%s request_id=%s", event, request_id)
    response = JSONResponse(status_code=status_code, content={"detail": detail})
    response.headers["X-Request-ID"] = request_id
    _apply_response_headers(response, security, api_response=api_response)
    return response


def install_public_security(app: FastAPI, security: PublicSecurityConfig) -> None:
    app.state.public_security = security
    if security.allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(security.allowed_hosts))

    @app.middleware("http")
    async def public_security_boundary(request: Request, call_next):
        request_id = secrets.token_hex(16)
        request.state.request_id = request_id
        api_response = request.url.path.startswith("/api/")
        request_origin = ""
        if security.dynamic_base_url:
            try:
                request_origin = _request_origin(request, security)
            except RuntimeError:
                return _security_rejection(
                    security=security,
                    request_id=request_id,
                    event="host_rejected",
                    status_code=400,
                    detail="Host is not allowed",
                    api_response=api_response,
                )
        if security.require_https and request.url.path != "/health" and not security.request_is_https(request):
            return _security_rejection(
                security=security,
                request_id=request_id,
                event="https_required",
                status_code=400,
                detail="HTTPS is required",
                api_response=api_response,
            )

        if security.enforce_origin and request.method.upper() in UNSAFE_METHODS:
            origin = request.headers.get("origin", "").strip().rstrip("/")
            if origin:
                try:
                    normalized_origin = _origin(origin, label="Origin")[0]
                except RuntimeError:
                    normalized_origin = ""
                if normalized_origin not in security.allowed_origins and normalized_origin != request_origin:
                    return _security_rejection(
                        security=security,
                        request_id=request_id,
                        event="origin_rejected",
                        status_code=403,
                        detail="Origin is not allowed",
                        api_response=api_response,
                    )
            elif SESSION_COOKIE_NAME in request.cookies and not request.headers.get("authorization"):
                return _security_rejection(
                    security=security,
                    request_id=request_id,
                    event="origin_missing",
                    status_code=403,
                    detail="Origin header is required",
                    api_response=api_response,
                )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        _apply_response_headers(response, security, api_response=api_response)
        return response


def prepare_runtime_permissions() -> None:
    if os.name == "nt":
        return
    os.umask(0o077)
    directories = [config.CONFIG_DIR, config.COOKIE_DIR, config.DATA_DIR, config.GENERATED_DIR, config.RUNTIME_DIR]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
    protected_files: list[Path] = [config.APP_CONFIG_PATH, config.DB_PATH]
    if config.COOKIE_DIR.exists():
        protected_files.extend(path for path in config.COOKIE_DIR.glob("*.json") if path.is_file())
    for path in protected_files:
        if path.exists():
            path.chmod(0o600)
