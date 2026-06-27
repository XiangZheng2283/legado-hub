"""Shared-book scheduler skeleton for startup recovery and periodic updates."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any, Callable

from app.services.aggregate_processor import AggregateProcessor
from app.services.shared_book_job_types import SharedBookJobType
from app.services.shared_book_lock import SharedBookLockService
from app.services.shared_book_runtime import SharedBookProcessLogger
from app.services.shared_book_source_map import SharedBookSourceMapService

logger = logging.getLogger(__name__)

BookContext = dict[str, str]
BookItem = dict[str, Any]
ManualQueueEntry = tuple[str, str, dict[str, Any] | None]


class SharedBookScheduler:
    """Lightweight scheduler that decides when AggregateProcessor should run."""

    def __init__(
        self,
        processor: AggregateProcessor | None = None,
        *,
        lock_service: SharedBookLockService | None = None,
        recovery_limit: int = 20,
        periodic_limit: int = 5,
        recovery_scanner: Callable[[], list[BookItem]] | None = None,
        book_context_provider: Callable[[str], dict[str, Any] | None] | None = None,
        source_map_service: SharedBookSourceMapService | None = None,
        process_logger: SharedBookProcessLogger | None = None,
        enable_process_logging: bool = True,
    ):
        self.processor = processor or AggregateProcessor()
        self.lock_service = lock_service or SharedBookLockService()
        self.source_map_service = source_map_service or SharedBookSourceMapService()
        self.process_logger = process_logger or SharedBookProcessLogger()
        self.enable_process_logging = bool(enable_process_logging)
        self.recovery_limit = int(recovery_limit)
        self.periodic_limit = int(periodic_limit)
        self.recovery_scanner = recovery_scanner or self._default_recovery_scanner
        self.book_context_provider = book_context_provider or self._default_book_context_provider

        self._startup_recovery_lock = asyncio.Lock()
        self._startup_recovery_done = False
        self._startup_recovery_result: dict[str, Any] | None = None
        self._recovery_complete = asyncio.Event()
        self._recovery_pending_books: set[str] = set()
        self._startup_recovery_processed_books: set[str] = set()
        self._startup_periodic_skip_pending = False
        self._manual_queue: deque[ManualQueueEntry] = deque()
        self._manual_pending_entries: set[tuple[str, str]] = set()
        self._initial_source_map_pending_books: set[str] = set()
        self._book_contexts: dict[str, BookContext] = {}

    async def startup_recovery_scan(self) -> dict[str, Any]:
        """Run one startup recovery pass before the periodic loop begins."""
        if self._startup_recovery_done and self._startup_recovery_result is not None:
            return self._startup_recovery_result

        async with self._startup_recovery_lock:
            if self._startup_recovery_done and self._startup_recovery_result is not None:
                return self._startup_recovery_result

            logger.info("Shared-book startup recovery scan started")
            try:
                candidates = list(self.recovery_scanner() or [])
            except Exception as exc:
                logger.warning("Shared-book startup recovery scan failed to enumerate books", exc_info=True)
                result = {
                    "jobType": SharedBookJobType.STARTUP_RECOVERY_SCAN.value,
                    "queuedBooks": 0,
                    "processedBooks": 0,
                    "items": [],
                    "error": str(exc),
                }
                self._startup_recovery_done = True
                self._startup_recovery_result = result
                self._recovery_complete.set()
                return result

            items: list[dict[str, Any]] = []
            queued_book_ids: list[str] = []
            for item in candidates:
                book_id = self._book_id_from_item(item)
                if not book_id or book_id in self._recovery_pending_books:
                    continue
                queued_book_ids.append(book_id)
                self._recovery_pending_books.add(book_id)
                self._remember_book_context(
                    book_id,
                    payload=item.get("payload"),
                    book_name=item.get("bookName") or item.get("name"),
                    author=item.get("author"),
                )

            try:
                for item in candidates:
                    book_id = self._book_id_from_item(item)
                    if not book_id or book_id not in self._recovery_pending_books:
                        continue
                    try:
                        result = await self._process_book(
                            book_id,
                            trigger=SharedBookJobType.STARTUP_RECOVERY_SCAN.value,
                            payload=item.get("payload"),
                        )
                    except Exception as exc:
                        logger.warning("Shared-book recovery failed for %s", book_id, exc_info=True)
                        result = {
                            "bookId": book_id,
                            "trigger": SharedBookJobType.STARTUP_RECOVERY_SCAN.value,
                            "success": False,
                            "skipped": False,
                            "error": str(exc),
                        }
                    finally:
                        self._recovery_pending_books.discard(book_id)
                        self._startup_recovery_processed_books.add(book_id)
                    items.append(result)
            finally:
                self._recovery_complete.set()

            result = {
                "jobType": SharedBookJobType.STARTUP_RECOVERY_SCAN.value,
                "queuedBooks": len(queued_book_ids),
                "processedBooks": len(items),
                "items": items,
            }
            self._startup_periodic_skip_pending = True
            self._startup_recovery_done = True
            self._startup_recovery_result = result
            logger.info(
                "Shared-book startup recovery scan finished: queuedBooks=%d, processedBooks=%d",
                result["queuedBooks"],
                result["processedBooks"],
            )
            return result

    def enqueue_manual_update(
        self,
        aggregate_book_id: str,
        *,
        reason: str = "manual",
        book_name: str | None = None,
        author: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Queue one book for the next scheduler pass."""
        book_id = str(aggregate_book_id or "").strip()
        normalized_reason = str(reason or "manual").strip() or "manual"
        if not book_id:
            return {"queued": False, "reason": "missing_book_id", "bookId": ""}
        if book_id in self._recovery_pending_books:
            return {"queued": False, "reason": "already_in_recovery_queue", "bookId": book_id}
        backlog_state = self._stage3_backlog_state(book_id)
        if backlog_state["exceeded"]:
            return {
                "queued": False,
                "reason": "stage3_backlog_limit_exceeded",
                "bookId": book_id,
                "stage3Backlog": backlog_state["backlog"],
                "stage3BacklogLimit": backlog_state["limit"],
            }
        entry_key = (book_id, normalized_reason)
        if entry_key in self._manual_pending_entries:
            return {"queued": False, "reason": "already_queued", "bookId": book_id, "trigger": normalized_reason}

        self._remember_book_context(book_id, payload=payload, book_name=book_name, author=author)
        self._startup_recovery_processed_books.discard(book_id)
        self._manual_queue.append((book_id, normalized_reason, dict(payload) if isinstance(payload, dict) else None))
        self._manual_pending_entries.add(entry_key)
        return {"queued": True, "reason": normalized_reason, "bookId": book_id, "trigger": normalized_reason}

    def enqueue_initial_subscription(
        self,
        aggregate_book_id: str,
        *,
        payload: dict[str, Any] | None = None,
        book_name: str | None = None,
        author: str | None = None,
    ) -> dict[str, Any]:
        """Queue the initial source-map refresh before the first bootstrap."""
        book_id = str(aggregate_book_id or "").strip()
        if not book_id:
            return {"queued": False, "reason": "missing_book_id", "bookId": ""}

        self._initial_source_map_pending_books.add(book_id)
        self._remember_book_context(book_id, payload=payload, book_name=book_name, author=author)
        refresh_result = self.enqueue_manual_update(
            book_id,
            reason=SharedBookJobType.BOOK_SOURCE_MAP_REFRESH.value,
            book_name=book_name,
            author=author,
            payload=payload,
        )
        bootstrap_result = self.enqueue_manual_update(
            book_id,
            reason=SharedBookJobType.BOOK_BOOTSTRAP.value,
            book_name=book_name,
            author=author,
            payload=payload,
        )
        return {
            "queued": bool(refresh_result.get("queued")) or bool(bootstrap_result.get("queued")),
            "bookId": book_id,
            "items": [refresh_result, bootstrap_result],
        }

    def enqueue_recovery_book(
        self,
        aggregate_book_id: str,
        *,
        book_name: str | None = None,
        author: str | None = None,
    ) -> dict[str, Any]:
        """Compatibility entrypoint for explicit recovery queueing."""
        book_id = str(aggregate_book_id or "").strip()
        if not book_id:
            return {"queued": False, "reason": "missing_book_id", "bookId": ""}
        if book_id in self._recovery_pending_books:
            return {"queued": False, "reason": "already_in_recovery_queue", "bookId": book_id}

        self._remember_book_context(book_id, book_name=book_name, author=author)
        self._recovery_pending_books.add(book_id)
        return {"queued": True, "reason": SharedBookJobType.STARTUP_RECOVERY_SCAN.value, "bookId": book_id}

    async def run_periodic_once(
        self,
        *,
        limit: int | None = None,
        wait_for_recovery: bool = True,
        include_due_books: bool = True,
    ) -> dict[str, Any]:
        """Run one periodic scheduling pass after startup recovery."""
        if wait_for_recovery:
            await self._recovery_complete.wait()

        effective_limit = int(limit or self.periodic_limit)
        manual_items = self._drain_manual_queue()
        due_items = list(self.processor.list_due_books(limit=effective_limit) or []) if include_due_books else []

        scheduled: list[ManualQueueEntry] = []
        seen_book_ids: set[str] = set()
        skipped_recovery = 0
        skipped_startup_recovery_processed = 0
        skipped_stage3_backlog = 0
        deferred_bootstrap = 0

        for book_id, reason, payload in manual_items:
            if book_id in self._recovery_pending_books:
                skipped_recovery += 1
                continue
            backlog_state = self._stage3_backlog_state(book_id)
            if backlog_state["exceeded"]:
                self._requeue_manual_entry(book_id, reason, payload)
                skipped_stage3_backlog += 1
                continue
            if reason != SharedBookJobType.BOOK_BOOTSTRAP.value and book_id in seen_book_ids:
                continue
            if reason != SharedBookJobType.BOOK_BOOTSTRAP.value:
                seen_book_ids.add(book_id)
            scheduled.append((book_id, reason, payload))

        for item in due_items:
            book_id = self._book_id_from_item(item)
            if not book_id:
                continue
            if book_id in self._recovery_pending_books:
                skipped_recovery += 1
                continue
            if self._startup_periodic_skip_pending and book_id in self._startup_recovery_processed_books:
                skipped_startup_recovery_processed += 1
                continue
            backlog_state = self._stage3_backlog_state(book_id)
            if backlog_state["exceeded"]:
                skipped_stage3_backlog += 1
                continue
            if book_id in seen_book_ids:
                continue
            seen_book_ids.add(book_id)
            self._remember_book_context(
                book_id,
                payload=item.get("payload"),
                book_name=item.get("bookName") or item.get("name"),
                author=item.get("author"),
            )
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else None
            should_refresh, _reason = self.source_map_service.should_refresh(book_id, payload=payload)
            trigger = (
                SharedBookJobType.BOOK_SOURCE_MAP_REFRESH.value
                if should_refresh
                else SharedBookJobType.BOOK_UPDATE_CHECK.value
            )
            scheduled.append((book_id, trigger, payload))

        processed_items: list[dict[str, Any]] = []
        for book_id, trigger, payload in scheduled:
            if trigger == SharedBookJobType.BOOK_BOOTSTRAP.value and self._should_defer_bootstrap(book_id):
                self._requeue_manual_entry(book_id, trigger, payload)
                deferred_bootstrap += 1
                continue
            processed_items.append(await self._process_book(book_id, trigger=trigger, payload=payload))
            if trigger == SharedBookJobType.BOOK_SOURCE_MAP_REFRESH.value:
                self._initial_source_map_pending_books.discard(book_id)

        result = {
            "processedBooks": len(processed_items),
            "dueBooks": len(due_items),
            "manualBooks": len(manual_items),
            "skippedRecoveryBooks": skipped_recovery,
            "skippedStartupRecoveryProcessedBooks": skipped_startup_recovery_processed,
            "skippedStage3BacklogBooks": skipped_stage3_backlog,
            "deferredBootstrapBooks": deferred_bootstrap,
            "items": processed_items,
        }
        if self._startup_periodic_skip_pending:
            self._startup_periodic_skip_pending = False
            self._startup_recovery_processed_books.clear()
        return result

    async def run_forever(self, stop_event: asyncio.Event, poll_seconds: int = 60) -> None:
        """Run startup recovery once, then continue periodic checks."""
        logger.info("Shared-book scheduler started, pollSeconds=%d", poll_seconds)
        try:
            await self.startup_recovery_scan()
            while not stop_event.is_set():
                try:
                    result = await self.run_periodic_once(wait_for_recovery=False)
                    if result.get("processedBooks", 0) > 0:
                        logger.info(
                            "Shared-book scheduler pass completed: processedBooks=%d, dueBooks=%d, manualBooks=%d",
                            result.get("processedBooks", 0),
                            result.get("dueBooks", 0),
                            result.get("manualBooks", 0),
                        )
                except Exception:
                    logger.warning("Shared-book scheduler periodic pass failed", exc_info=True)

                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
                except asyncio.TimeoutError:
                    continue
        finally:
            logger.info("Shared-book scheduler stopped")

    async def _process_book(
        self,
        aggregate_book_id: str,
        *,
        trigger: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        book_context = self._resolve_book_context(aggregate_book_id, payload=payload)
        book_name = book_context["bookName"]
        author = book_context["author"]
        lease = self.lock_service.acquire(book_name=book_name, author=author)
        if lease is None:
            self._log(
                book_name=book_name,
                author=author,
                event="job_skipped",
                book_id=aggregate_book_id,
                payload={"trigger": trigger, "reason": "lock_busy"},
            )
            return {
                "bookId": aggregate_book_id,
                "trigger": trigger,
                "success": False,
                "skipped": True,
                "reason": "lock_busy",
            }

        self._log(
            book_name=book_name,
            author=author,
            event="job_start",
            book_id=aggregate_book_id,
            payload={"trigger": trigger},
        )
        try:
            if trigger == SharedBookJobType.BOOK_SOURCE_MAP_REFRESH.value:
                force_refresh = aggregate_book_id in self._initial_source_map_pending_books
                result = await self.source_map_service.refresh_for_book(
                    aggregate_book_id,
                    payload=payload,
                    force=force_refresh,
                )
                self._log(
                    book_name=book_name,
                    author=author,
                    event="job_complete",
                    book_id=aggregate_book_id,
                    payload={"trigger": trigger, "success": bool(result.get("success", True))},
                )
                return {
                    "bookId": aggregate_book_id,
                    "trigger": trigger,
                    "success": bool(result.get("success", True)),
                    "skipped": False,
                    "result": result,
                }
            if trigger == SharedBookJobType.BOOK_BOOTSTRAP.value:
                result = await self.processor.bootstrap_book_until_visible(aggregate_book_id)
                self._log(
                    book_name=book_name,
                    author=author,
                    event="job_complete",
                    book_id=aggregate_book_id,
                    payload={"trigger": trigger, "success": bool(result.get("success", True))},
                )
                return {
                    "bookId": aggregate_book_id,
                    "trigger": trigger,
                    "success": bool(result.get("success", True)),
                    "skipped": False,
                    "result": result,
                }
            result = await self.processor.run_book_task(aggregate_book_id)
            if trigger == SharedBookJobType.STARTUP_RECOVERY_SCAN.value and not result.get("skipped", False):
                self._startup_recovery_processed_books.add(aggregate_book_id)
            self._log(
                book_name=book_name,
                author=author,
                event="job_complete",
                book_id=aggregate_book_id,
                payload={"trigger": trigger, "success": bool(result.get("success", True))},
            )
            return {
                "bookId": aggregate_book_id,
                "trigger": trigger,
                "success": bool(result.get("success", True)),
                "skipped": False,
                "result": result,
            }
        except Exception as exc:
            self._log(
                book_name=book_name,
                author=author,
                event="job_error",
                book_id=aggregate_book_id,
                payload={"trigger": trigger, "error": str(exc)},
            )
            raise
        finally:
            lease.release()

    def _default_recovery_scanner(self) -> list[BookItem]:
        return list(self.processor.list_due_books(limit=self.recovery_limit) or [])

    def _default_book_context_provider(self, aggregate_book_id: str) -> dict[str, Any] | None:
        library_getter = getattr(self.processor, "_library_books", None)
        if not callable(library_getter):
            return None
        try:
            service = library_getter()
            if service is None or not hasattr(service, "get_book"):
                return None
            return service.get_book(aggregate_book_id)
        except Exception:
            logger.debug("Failed to resolve shared-book context for %s", aggregate_book_id, exc_info=True)
            return None

    async def run_source_map_refresh_now(
        self,
        aggregate_book_id: str,
        *,
        payload: dict[str, Any] | None = None,
        force: bool = True,
    ) -> dict[str, Any]:
        """Minimal admin/manual entrypoint for an immediate source-map refresh."""
        book_id = str(aggregate_book_id or "").strip()
        if not book_id:
            return {"bookId": "", "success": False, "error": "missing_book_id"}
        return await self.source_map_service.refresh_for_book(book_id, payload=payload, force=force)

    def _drain_manual_queue(self) -> list[ManualQueueEntry]:
        drained: list[ManualQueueEntry] = []
        while self._manual_queue:
            book_id, reason, payload = self._manual_queue.popleft()
            self._manual_pending_entries.discard((book_id, reason))
            drained.append((book_id, reason, payload))
        return drained

    def _requeue_manual_entry(
        self,
        aggregate_book_id: str,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        entry_key = (aggregate_book_id, reason)
        if entry_key in self._manual_pending_entries:
            return
        self._manual_queue.append((aggregate_book_id, reason, dict(payload) if isinstance(payload, dict) else None))
        self._manual_pending_entries.add(entry_key)

    def _remember_book_context(
        self,
        aggregate_book_id: str,
        *,
        payload: dict[str, Any] | None = None,
        book_name: str | None = None,
        author: str | None = None,
    ) -> None:
        current = self._book_contexts.get(aggregate_book_id, {})
        payload = payload if isinstance(payload, dict) else {}
        resolved_name = str(book_name or payload.get("name") or payload.get("bookName") or current.get("bookName", "")).strip()
        resolved_author = str(author or payload.get("author") or current.get("author", "")).strip()
        if resolved_name or resolved_author:
            self._book_contexts[aggregate_book_id] = {
                "bookName": resolved_name,
                "author": resolved_author,
            }

    def _resolve_book_context(
        self,
        aggregate_book_id: str,
        *,
        payload: dict[str, Any] | None = None,
    ) -> BookContext:
        self._remember_book_context(aggregate_book_id, payload=payload)
        current = self._book_contexts.get(aggregate_book_id)
        if current and current.get("bookName"):
            return {
                "bookName": current.get("bookName", aggregate_book_id) or aggregate_book_id,
                "author": current.get("author", "") or "",
            }

        provided = self.book_context_provider(aggregate_book_id) or {}
        provided_name = str(provided.get("name") or provided.get("bookName") or aggregate_book_id).strip() or aggregate_book_id
        provided_author = str(provided.get("author") or "").strip()
        resolved = {"bookName": provided_name, "author": provided_author}
        self._book_contexts[aggregate_book_id] = resolved
        return resolved

    def _should_defer_bootstrap(self, aggregate_book_id: str) -> bool:
        if aggregate_book_id in self._initial_source_map_pending_books:
            return True
        library_books = getattr(self.source_map_service, "library_books", None)
        if library_books is None or not hasattr(library_books, "source_map_refresh_state"):
            return False
        state = library_books.source_map_refresh_state(aggregate_book_id)
        return not bool(state.get("completed"))

    def _log(
        self,
        *,
        book_name: str,
        author: str,
        event: str,
        book_id: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if not self.enable_process_logging or not book_name or not author:
            return
        try:
            self.process_logger.append(
                book_name=book_name,
                author=author,
                event=event,
                book_id=book_id,
                payload=payload,
            )
        except Exception:
            logger.debug("Failed to write shared-book process log", exc_info=True)

    def _book_id_from_item(self, item: dict[str, Any]) -> str:
        if not isinstance(item, dict):
            return ""
        return str(item.get("aggregateBookId") or item.get("bookId") or "").strip()

    def _stage3_backlog_state(self, aggregate_book_id: str) -> dict[str, Any]:
        resolver = getattr(self.processor, "stage3_backlog_state", None)
        if not callable(resolver):
            return {
                "bookId": aggregate_book_id,
                "backlog": 0,
                "limit": 0,
                "enabled": False,
                "exceeded": False,
            }
        try:
            state = resolver(aggregate_book_id)
        except Exception:
            logger.debug("Failed to resolve Stage 3 backlog state for %s", aggregate_book_id, exc_info=True)
            return {
                "bookId": aggregate_book_id,
                "backlog": 0,
                "limit": 0,
                "enabled": False,
                "exceeded": False,
            }
        if isinstance(state, dict):
            return {
                "bookId": aggregate_book_id,
                "backlog": int(state.get("backlog", 0) or 0),
                "limit": int(state.get("limit", 0) or 0),
                "enabled": bool(state.get("enabled", False)),
                "exceeded": bool(state.get("exceeded", False)),
            }
        return {
            "bookId": aggregate_book_id,
            "backlog": 0,
            "limit": 0,
            "enabled": False,
            "exceeded": False,
        }
