"""Single-process per-user rate and concurrency limits for Reading clients."""

from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class ReadingActionLimit:
    requests_per_window: int
    max_concurrency: int | None = None


# The client prefetches current/next/prev chapters and their comments in
# parallel, so a fixed concurrency of 4/2 trips 429 under normal reading.
# Scale the read-path concurrency slot with the host CPU (e.g. 4 cores -> 16
# parallel blocks) to keep multi-book + multi-chapter prefetch from being
# rejected as "当前阅读请求较多".
def _cpu_concurrency_slots(multiplier: int = 4, *, floor: int = 8, cap: int = 64) -> int:
    cores = max(1, os.cpu_count() or 1)
    return max(floor, min(cap, cores * multiplier))


_READ_CONCURRENCY = _cpu_concurrency_slots()

DEFAULT_READING_LIMITS = {
    "search": ReadingActionLimit(20),
    "metadata": ReadingActionLimit(120),
    "chapter": ReadingActionLimit(120, max_concurrency=_READ_CONCURRENCY),
    "reviews": ReadingActionLimit(30, max_concurrency=min(_READ_CONCURRENCY, 16)),
}


class ReadingLimitError(RuntimeError):
    def __init__(self, code: str, message: str, *, retry_after_seconds: int):
        super().__init__(message)
        self.code = code
        self.retry_after_seconds = max(1, int(retry_after_seconds))


class ReadingAccessLimiter:
    def __init__(self, *, window_seconds: int = 60, limits=None, clock=time.monotonic):
        self.window_seconds = max(1, int(window_seconds))
        self.limits = dict(limits or DEFAULT_READING_LIMITS)
        self.clock = clock
        self._events: dict[tuple[str, str], deque[float]] = {}
        self._active: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    @contextmanager
    def guard(self, user_id: str, action: str) -> Iterator[None]:
        limit = self.limits.get(action)
        if not limit:
            raise ValueError(f"unsupported Reading action: {action}")
        key = (str(user_id), action)
        now = self.clock()
        concurrency_acquired = False
        with self._lock:
            events = self._events.setdefault(key, deque())
            cutoff = now - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit.requests_per_window:
                retry_after = math.ceil(self.window_seconds - (now - events[0]))
                raise ReadingLimitError(
                    "reading_rate_limited",
                    "阅读请求过于频繁，请稍后重试",
                    retry_after_seconds=retry_after,
                )
            if limit.max_concurrency is not None:
                active = self._active.get(key, 0)
                if active >= limit.max_concurrency:
                    raise ReadingLimitError(
                        "reading_concurrency_limited",
                        "当前阅读请求较多，请稍后重试",
                        retry_after_seconds=1,
                    )
                self._active[key] = active + 1
                concurrency_acquired = True
            events.append(now)
        try:
            yield
        finally:
            if concurrency_acquired:
                with self._lock:
                    remaining = self._active.get(key, 1) - 1
                    if remaining > 0:
                        self._active[key] = remaining
                    else:
                        self._active.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._active.clear()


reading_access_limiter = ReadingAccessLimiter()
