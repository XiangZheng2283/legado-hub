"""File-backed per-book lease locks for single-instance local deployments."""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from app.services.shared_book_storage import SharedBookStorage

try:
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows fallback
    msvcrt = None
    import fcntl


PROCESS_START_TS = int(time.time() * 1000)


class SharedBookLockError(RuntimeError):
    """Raised when a caller attempts to keep writing after a hard stop."""


@dataclass(slots=True)
class SharedBookLease:
    """Caller-facing lease state for one shared-book lock."""

    service: "SharedBookLockService"
    book_name: str
    author: str
    worker_id: str
    lock_path: Path
    ttl_seconds: float
    renewal_interval_seconds: float
    acquired_at: float
    expires_at: float
    stop_requested: bool = False

    @property
    def can_write(self) -> bool:
        return not self.stop_requested

    def assert_writable(self) -> None:
        if self.stop_requested:
            raise SharedBookLockError(
                f"shared-book lease for '{self.book_name}' is no longer writable; stop work and exit"
            )

    def renew(self) -> bool:
        return self.service.renew(self)

    def release(self) -> None:
        self.service.release(self)


class SharedBookLockService:
    """Coordinate one active writer per shared book via a local filesystem lease file."""

    def __init__(
        self,
        storage: SharedBookStorage | None = None,
        *,
        ttl_seconds: float = 30.0,
        time_provider: Callable[[], float] | None = None,
        hostname: str | None = None,
        pid: int | None = None,
        process_start_ts: int | None = None,
        random_factory: Callable[[], str] | None = None,
    ):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self.storage = storage or SharedBookStorage()
        self.ttl_seconds = float(ttl_seconds)
        self.time_provider = time_provider or time.time
        self.hostname = hostname or socket.gethostname()
        self.pid = int(pid if pid is not None else os.getpid())
        self.process_start_ts = int(process_start_ts if process_start_ts is not None else PROCESS_START_TS)
        self.random_factory = random_factory or (lambda: uuid.uuid4().hex[:8])

    def acquire(self, *, book_name: str, author: str) -> SharedBookLease | None:
        runtime_dir = self.storage.runtime_dir(book_name=book_name, author=author)
        lock_path = runtime_dir / "shared_book.lock.json"
        worker_id = self.build_worker_id()

        with self._guard_lock(runtime_dir):
            now = self.time_provider()
            current = self._read_lock_payload(lock_path)
            if current is not None and not self._is_expired(current, now=now):
                return None

            payload = self._build_lock_payload(worker_id=worker_id, now=now)
            self._atomic_write_json(lock_path, payload)
            return self._lease_from_payload(
                book_name=book_name,
                author=author,
                lock_path=lock_path,
                payload=payload,
            )

    def renew(self, lease: SharedBookLease) -> bool:
        if lease.stop_requested:
            return False

        now = self.time_provider()
        with self._guard_lock(lease.lock_path.parent):
            payload = self._read_lock_payload(lease.lock_path)
            if payload is None:
                lease.stop_requested = True
                return False
            if payload.get("workerId") != lease.worker_id:
                lease.stop_requested = True
                return False
            if self._is_expired(payload, now=now):
                lease.stop_requested = True
                return False

            renewed_payload = dict(payload)
            renewed_payload["renewedAt"] = now
            renewed_payload["expiresAt"] = now + lease.ttl_seconds
            self._atomic_write_json(lease.lock_path, renewed_payload)
            lease.acquired_at = float(renewed_payload.get("acquiredAt", now) or now)
            lease.expires_at = float(renewed_payload["expiresAt"])
            return True

    def release(self, lease: SharedBookLease) -> None:
        with self._guard_lock(lease.lock_path.parent):
            payload = self._read_lock_payload(lease.lock_path)
            if payload is None:
                return
            if payload.get("workerId") != lease.worker_id:
                return
            try:
                lease.lock_path.unlink()
            except FileNotFoundError:
                return

    def build_worker_id(self) -> str:
        random_suffix = self.random_factory()
        return f"{self.hostname}-{self.pid}-{self.process_start_ts}-{random_suffix}"

    def _lease_from_payload(
        self,
        *,
        book_name: str,
        author: str,
        lock_path: Path,
        payload: dict[str, object],
    ) -> SharedBookLease:
        ttl_seconds = float(payload.get("ttlSeconds", self.ttl_seconds) or self.ttl_seconds)
        return SharedBookLease(
            service=self,
            book_name=book_name,
            author=author,
            worker_id=str(payload["workerId"]),
            lock_path=lock_path,
            ttl_seconds=ttl_seconds,
            renewal_interval_seconds=ttl_seconds / 3.0,
            acquired_at=float(payload["acquiredAt"]),
            expires_at=float(payload["expiresAt"]),
        )

    def _build_lock_payload(self, *, worker_id: str, now: float) -> dict[str, object]:
        return {
            "workerId": worker_id,
            "hostname": self.hostname,
            "pid": self.pid,
            "processStartTs": self.process_start_ts,
            "randomSuffix": worker_id.rsplit("-", 1)[-1],
            "acquiredAt": now,
            "renewedAt": now,
            "ttlSeconds": self.ttl_seconds,
            "expiresAt": now + self.ttl_seconds,
        }

    def _is_expired(self, payload: dict[str, object], *, now: float) -> bool:
        expires_at = float(payload.get("expiresAt", 0) or 0)
        return expires_at <= now

    def _read_lock_payload(self, path: Path) -> dict[str, object] | None:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(f"invalid lock payload at {path}")
        return data

    def _atomic_write_json(self, path: Path, payload: dict[str, object]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)

    @contextmanager
    def _guard_lock(self, runtime_dir: Path) -> Iterator[None]:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        guard_path = runtime_dir / ".shared_book.lock.guard"
        with guard_path.open("a+b") as handle:
            # Guard lock protects the local critical section; the JSON lease file is the ownership record
            # that other processes read to determine who currently owns this book.
            self._acquire_file_lock(handle)
            try:
                yield
            finally:
                self._release_file_lock(handle)

    def _acquire_file_lock(self, handle) -> None:
        if msvcrt is not None:
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            return
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

    def _release_file_lock(self, handle) -> None:
        if msvcrt is not None:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
