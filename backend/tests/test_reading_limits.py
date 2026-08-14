from __future__ import annotations

import pytest

from app.services.reading_limits import ReadingAccessLimiter, ReadingActionLimit, ReadingLimitError


def test_rejected_concurrent_chapter_does_not_consume_rate_window() -> None:
    limiter = ReadingAccessLimiter(
        window_seconds=60,
        limits={"chapter": ReadingActionLimit(3, max_concurrency=1)},
        clock=lambda: 100.0,
    )

    with limiter.guard("user", "chapter"):
        with pytest.raises(ReadingLimitError) as rejected:
            with limiter.guard("user", "chapter"):
                pass
        assert rejected.value.code == "reading_concurrency_limited"

    with limiter.guard("user", "chapter"):
        pass

    with limiter.guard("user", "chapter"):
        pass
