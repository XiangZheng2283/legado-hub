"""CloudFlare ImgBed uploader for chapter-review media."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.core.app_config import AppConfig


_ALLOWED_CHANNELS = {"telegram", "cfr2", "s3", "discord", "huggingface", "webdav"}
_ALLOWED_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_MAX_URL_LENGTH = 4096
_MAX_RESPONSE_BYTES = 256 * 1024
_TRUSTED_IMG_BED_HOSTS: set[str] = set()


def _host_is_public(host: str) -> bool:
    normalized = str(host or "").lower().rstrip(".")
    if not normalized or normalized in {"localhost", "localhost.localdomain"}:
        return False
    if normalized.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    )


def _normalize_base_url(value: str) -> str:
    candidate = str(value or "").strip().rstrip("/")
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ""
    if not _host_is_public(parsed.hostname):
        return ""
    return candidate


@dataclass(frozen=True)
class ImgBedConfig:
    enabled_setting: bool = False
    base_url: str = ""
    auth_code: str = ""
    api_token: str = ""
    upload_channel: str = "cfr2"
    channel_name: str = ""
    upload_folder: str = "legadohub/reviews"
    return_format: str = "full"
    timeout_seconds: float = 30.0
    max_file_bytes: int = 10 * 1024 * 1024

    @property
    def enabled(self) -> bool:
        return bool(
            self.enabled_setting
            and self.base_url
            and (self.auth_code or self.api_token)
            and self.upload_channel in _ALLOWED_CHANNELS
        )

    @classmethod
    def from_config(cls) -> "ImgBedConfig":
        settings = AppConfig.get().imgbed
        channel = str(settings.upload_channel or "cfr2").strip().lower()
        return cls(
            enabled_setting=bool(settings.enabled),
            base_url=_normalize_base_url(settings.base_url),
            auth_code=settings.auth_code,
            api_token=settings.api_token,
            upload_channel=channel if channel in _ALLOWED_CHANNELS else "cfr2",
            channel_name=settings.channel_name,
            upload_folder=settings.upload_folder,
            return_format="full",
        )

    def fingerprint(self) -> str:
        value = "\x1f".join(
            (
                str(self.enabled),
                self.base_url,
                self.upload_channel,
                self.channel_name,
                self.upload_folder,
                "auth" if self.auth_code else "",
                "token" if self.api_token else "",
            )
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


_IMAGE_SIGNATURES: tuple[tuple[str, bytes], ...] = (
    ("image/jpeg", b"\xff\xd8\xff"),
    ("image/png", b"\x89PNG\r\n\x1a\n"),
    ("image/gif", b"GIF87a"),
    ("image/gif", b"GIF89a"),
)


def sniff_image_mime(data: bytes) -> str:
    for mime, signature in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return mime
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _safe_filename(filename: str, mime: str) -> str:
    suffix = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }[mime]
    stem = str(filename or "image").replace("\\", "/").rsplit("/", 1)[-1]
    stem = "".join(char for char in stem if char.isalnum() or char in "._-").strip(".")
    if not stem:
        stem = "image"
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    return f"{stem[:80]}{suffix}"


def _remember_trusted_url(value: str) -> None:
    host = (urlparse(value).hostname or "").lower().rstrip(".")
    if host and _host_is_public(host):
        _TRUSTED_IMG_BED_HOSTS.add(host)


def is_trusted_imgbed_url(value: str) -> bool:
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > _MAX_URL_LENGTH:
        return False
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    if not _host_is_public(host):
        return False
    config = ImgBedConfig.from_config()
    configured_host = (urlparse(config.base_url).hostname or "").lower().rstrip(".")
    return host in _TRUSTED_IMG_BED_HOSTS or (configured_host and host == configured_host)


def _response_url_candidates(payload: Any) -> list[str]:
    rows: list[Any] = []
    if isinstance(payload, list):
        rows.extend(payload)
    elif isinstance(payload, dict):
        rows.append(payload)
        data = payload.get("data")
        if isinstance(data, (dict, list)):
            rows.extend(data if isinstance(data, list) else [data])
    candidates: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in ("publicUrl", "src"):
            value = row.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
    return candidates


class ImgBedUploader:
    def __init__(self, config: ImgBedConfig | None = None):
        self.config = config or ImgBedConfig.from_config()
        self._cache: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[str]] = {}

    async def upload(
        self,
        data: bytes,
        *,
        mime_type: str,
        filename: str,
    ) -> str:
        mime = str(mime_type or "").lower().strip()
        if not self.config.enabled or mime not in _ALLOWED_MIMES:
            return ""
        if len(data) <= 0 or len(data) > self.config.max_file_bytes:
            return ""
        if sniff_image_mime(data) != mime:
            return ""
        asset_key = hashlib.sha256(data).hexdigest() + ":" + mime
        cached = self._cache.get(asset_key)
        if cached and cached[0] > time.monotonic():
            self._cache.move_to_end(asset_key)
            return cached[1]
        loop = asyncio.get_running_loop()
        existing = self._inflight.get(asset_key)
        if existing is not None and existing.get_loop() is loop:
            return await existing
        future: asyncio.Future[str] = loop.create_future()
        self._inflight[asset_key] = future
        try:
            result = await self._upload_once(data, mime, filename)
            if result:
                self._cache[asset_key] = (time.monotonic() + 86400, result)
                self._cache.move_to_end(asset_key)
                while len(self._cache) > 4096:
                    self._cache.popitem(last=False)
            future.set_result(result)
            return result
        except Exception:
            future.set_result("")
            return ""
        finally:
            self._inflight.pop(asset_key, None)

    async def _upload_once(self, data: bytes, mime: str, filename: str) -> str:
        query = {
            "uploadChannel": self.config.upload_channel,
            "returnFormat": self.config.return_format,
            "uploadFolder": self.config.upload_folder,
            "uploadNameType": "origin",
        }
        if self.config.channel_name:
            query["channelName"] = self.config.channel_name
        if self.config.auth_code:
            query["authCode"] = self.config.auth_code
        headers = {"Accept": "application/json"}
        if self.config.api_token:
            headers["Authorization"] = f"Bearer {self.config.api_token}"
        files = {"file": (_safe_filename(filename, mime), data, mime)}
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                f"{self.config.base_url}/upload",
                params=query,
                headers=headers,
                files=files,
            )
            response.raise_for_status()
            if len(response.content) > _MAX_RESPONSE_BYTES:
                return ""
            payload = response.json()
        for candidate in _response_url_candidates(payload):
            if candidate.startswith("//"):
                candidate = "https:" + candidate
            elif candidate.startswith("/"):
                candidate = urljoin(self.config.base_url + "/", candidate.lstrip("/"))
            try:
                parsed = urlparse(candidate)
            except ValueError:
                continue
            if (
                parsed.scheme in {"http", "https"}
                and parsed.netloc
                and not parsed.username
                and not parsed.password
                and _host_is_public(parsed.hostname or "")
                and len(candidate) <= _MAX_URL_LENGTH
            ):
                _remember_trusted_url(candidate)
                return candidate
        return ""


_UPLOADER: ImgBedUploader | None = None
_UPLOADER_FINGERPRINT = ""


def get_imgbed_uploader() -> ImgBedUploader:
    global _UPLOADER, _UPLOADER_FINGERPRINT
    config = ImgBedConfig.from_config()
    fingerprint = config.fingerprint()
    if _UPLOADER is None or _UPLOADER_FINGERPRINT != fingerprint:
        _UPLOADER = ImgBedUploader(config)
        _UPLOADER_FINGERPRINT = fingerprint
    return _UPLOADER
