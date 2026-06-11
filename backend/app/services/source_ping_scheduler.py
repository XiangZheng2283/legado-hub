"""Background scheduler for periodic source ping checks."""

from __future__ import annotations

import asyncio

from app.services.source_ping import SourcePingService
from app.source_plugins.scheduler import PluginScheduler


PING_INTERVAL_SECONDS = 600  # 10 minutes


class SourcePingScheduler:
    """Runs source ping checks in the background at a fixed interval."""

    def __init__(self, ping_service: SourcePingService | None = None):
        self.ping_service = ping_service or SourcePingService()

    async def run_forever(self, stop_event: asyncio.Event, poll_seconds: int = PING_INTERVAL_SECONDS) -> None:
        while not stop_event.is_set():
            try:
                await self.ping_service.ping_all()
            except Exception:
                pass
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
            except asyncio.TimeoutError:
                continue
