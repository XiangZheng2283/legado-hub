from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.services.shared_book_lock import SharedBookLease, SharedBookLockError, SharedBookLockService
from app.services.shared_book_storage import SharedBookStorage


class FakeClock:
    def __init__(self, now: float):
        self.now = float(now)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


def _make_service(tmp_path: Path, clock: FakeClock, **kwargs: object) -> SharedBookLockService:
    storage = SharedBookStorage(tmp_path / "library")
    return SharedBookLockService(
        storage=storage,
        ttl_seconds=float(kwargs.pop("ttl_seconds", 9.0)),
        time_provider=clock,
        hostname=str(kwargs.pop("hostname", "host-a")),
        pid=int(kwargs.pop("pid", 1234)),
        process_start_ts=int(kwargs.pop("process_start_ts", 1710000000000)),
        random_factory=kwargs.pop("random_factory", lambda: "rand1234"),
        **kwargs,
    )


def _lock_payload(lease: SharedBookLease) -> dict[str, object]:
    return json.loads(lease.lock_path.read_text(encoding="utf-8"))


def test_shared_book_lock_acquire_succeeds(tmp_path: Path):
    clock = FakeClock(100.0)
    service = _make_service(tmp_path, clock)

    lease = service.acquire(aggregate_book_id="book-1")

    assert lease is not None
    assert lease.worker_id == "host-a-1234-1710000000000-rand1234"
    assert lease.renewal_interval_seconds == pytest.approx(3.0)
    assert lease.can_write is True
    payload = _lock_payload(lease)
    assert payload["aggregateBookId"] == "book-1"
    assert payload["workerId"] == lease.worker_id
    assert payload["expiresAt"] == pytest.approx(109.0)


def test_shared_book_lock_second_acquire_fails(tmp_path: Path):
    clock = FakeClock(100.0)
    service_a = _make_service(tmp_path, clock, random_factory=lambda: "first")
    service_b = _make_service(tmp_path, clock, random_factory=lambda: "second", pid=5678)

    lease_a = service_a.acquire(aggregate_book_id="book-1")
    lease_b = service_b.acquire(aggregate_book_id="book-1")

    assert lease_a is not None
    assert lease_b is None


def test_shared_book_lock_release_allows_clean_reacquire(tmp_path: Path):
    clock = FakeClock(100.0)
    first_service = _make_service(tmp_path, clock, random_factory=lambda: "first")
    second_service = _make_service(tmp_path, clock, random_factory=lambda: "second", pid=5678)

    first_lease = first_service.acquire(aggregate_book_id="book-1")
    assert first_lease is not None

    first_lease.release()

    second_lease = second_service.acquire(aggregate_book_id="book-1")

    assert second_lease is not None
    assert second_lease.worker_id.endswith("-second")
    assert _lock_payload(second_lease)["workerId"] == second_lease.worker_id


def test_shared_book_lock_renew_succeeds(tmp_path: Path):
    clock = FakeClock(100.0)
    service = _make_service(tmp_path, clock, ttl_seconds=12.0)
    lease = service.acquire(aggregate_book_id="book-1")
    assert lease is not None

    clock.advance(4.0)
    renewed = lease.renew()

    assert renewed is True
    assert lease.stop_requested is False
    assert lease.expires_at == pytest.approx(116.0)
    payload = _lock_payload(lease)
    assert payload["renewedAt"] == pytest.approx(104.0)
    assert payload["expiresAt"] == pytest.approx(116.0)


def test_shared_book_lock_stop_request_is_visible_to_owner(tmp_path: Path):
    clock = FakeClock(100.0)
    owner = _make_service(tmp_path, clock, random_factory=lambda: "owner")
    admin = _make_service(tmp_path, clock, random_factory=lambda: "admin", pid=5678)
    lease = owner.acquire(aggregate_book_id="book-1")
    assert lease is not None

    assert admin.request_stop(aggregate_book_id="book-1") is True
    assert lease.renew() is False
    assert lease.stop_requested is True
    lease.release()
    assert admin.acquire(aggregate_book_id="book-1") is not None


def test_shared_book_lock_expired_lock_can_be_taken(tmp_path: Path):
    clock = FakeClock(100.0)
    first_service = _make_service(tmp_path, clock, random_factory=lambda: "first")
    second_service = _make_service(tmp_path, clock, random_factory=lambda: "second", pid=5678)

    first_lease = first_service.acquire(aggregate_book_id="book-1")
    assert first_lease is not None

    clock.advance(10.0)
    second_lease = second_service.acquire(aggregate_book_id="book-1")

    assert second_lease is not None
    assert second_lease.worker_id.endswith("-second")
    assert _lock_payload(second_lease)["workerId"] == second_lease.worker_id


def test_shared_book_lock_renew_failure_forces_caller_visible_stop_state(tmp_path: Path):
    clock = FakeClock(100.0)
    first_service = _make_service(tmp_path, clock, random_factory=lambda: "first")
    second_service = _make_service(tmp_path, clock, random_factory=lambda: "second", pid=5678)

    first_lease = first_service.acquire(aggregate_book_id="book-1")
    assert first_lease is not None

    clock.advance(10.0)
    second_lease = second_service.acquire(aggregate_book_id="book-1")
    assert second_lease is not None

    renewed = first_lease.renew()

    assert renewed is False
    assert first_lease.stop_requested is True
    assert first_lease.can_write is False
    with pytest.raises(SharedBookLockError, match="stop work and exit"):
        first_lease.assert_writable()
