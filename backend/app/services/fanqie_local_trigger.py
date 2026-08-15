"""Hub-side trigger of the fanqie_local downloader job.

When a user subscribes a fanqie_local candidate (or an admin adds one from a
search job), the hub must make sure the local Tomato-Novel-Downloader actually
has a download job running for that book so the incremental files
(downloaded_chapters.jsonl, segment_comments/<fnqie_id>.json, images/)
start producing. Otherwise the reader would wait for a job that nobody started
until the first missing chapter() call fires it lazily.

This module mirrors the plugin's own idempotent _ensure_job_started logic
(which lives in an un-importable plugin module) using ordinary HTTP, so the hub
does not reach into plugin internals. It is intentionally best-effort:
throttled / error dispositions never raise.
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)

# Keep strong refs to fire-and-forget trigger tasks so they are not GC'd.
_TASKS: set[asyncio.Task] = set()

_FANQIE_SOURCE_ID = "fanqie_local"


def _base_url() -> str:
    return (os.environ.get("FANQIE_LOCAL_BASE", "http://127.0.0.1:18423")).rstrip("/")


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    password = os.environ.get("FANQIE_LOCAL_PASSWD", "")
    if password:
        headers["x-tomato-password"] = password
    return headers


def fanqie_book_id_from_url(book_url):
    """Return the raw fanqie_local book id from its hub bookUrl.

    fanqie_local bookUrls look like <TOMATO_BASE>/__fanqie__/<book_id>,
    so the last path segment is the downloader's book id.
    """
    if not book_url:
        return None
    value = str(book_url).rstrip("/")
    if not value:
        return None
    return value.split("/")[-1] or None


def find_fanqie_book_id(group):
    """Extract the raw fanqie_local book id from a candidate group."""
    items = group.get("items") if isinstance(group.get("items"), list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("sourceId") != _FANQIE_SOURCE_ID:
            continue
        book_url = item.get("rawBookUrl") or item.get("bookUrl")
        book_id = fanqie_book_id_from_url(book_url)
        if book_id:
            return book_id
    return None


async def ensure_fanqie_download_job(
    book_id,
    *,
    base_url=None,
    password=None,
):
    """Idempotently make sure the downloader has a job for this book.

    Mirrors the plugin's _ensure_job_started contract:
      disposition in {existing_running, existing_done, existing_failed,
                      created, throttled, error}
    Never raises; throttled / error mean "download in progress state is
    unknown - the subscription continues and the existing reader path retries".
    """
    base = {"started": False, "job_id": None, "disposition": "error"}
    root = (base_url or _base_url()).rstrip("/")
    headers = dict(_headers())
    if password:
        headers["x-tomato-password"] = password

    # 1) Look for an existing job for this book (idempotent reuse).
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            data = (await client.get(f"{root}/api/jobs", params={"all": "true"}, headers=headers)).json()
    except Exception:
        return base
    for job in data.get("items") or []:
        if not isinstance(job, dict):
            continue
        if str(job.get("book_id") or "") != str(book_id):
            continue
        state = str(job.get("state") or "")
        jid = job.get("id")
        if state in ("queued", "running"):
            return {"started": True, "job_id": jid, "disposition": "existing_running"}
        if state == "done":
            return {"started": True, "job_id": jid, "disposition": "existing_done"}
        # failed / canceled: do not auto-recreate (mirrors plugin behavior).
        return {"started": False, "job_id": jid, "disposition": "existing_failed"}

    # 2) Create a new job; single-active-task 429 (or network error) -> throttled.
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{root}/api/jobs",
                json={"book_id": str(book_id)},
                headers={**headers, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            payload = resp.json()
    except Exception:
        return base | {"disposition": "throttled"}

    jid = payload.get("id") if isinstance(payload, dict) else None
    if jid:
        return {"started": True, "job_id": jid, "disposition": "created"}

    # 3) Race: create returned empty (beaten by another creator) -> re-check.
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            data = (await client.get(f"{root}/api/jobs", params={"all": "true"}, headers=headers)).json()
    except Exception:
        return base | {"disposition": "throttled"}
    for job in data.get("items") or []:
        if not isinstance(job, dict):
            continue
        if str(job.get("book_id") or "") != str(book_id):
            continue
        state = str(job.get("state") or "")
        if state in ("queued", "running"):
            return {"started": True, "job_id": job.get("id"), "disposition": "existing_running"}
        if state == "done":
            return {"started": True, "job_id": job.get("id"), "disposition": "existing_done"}
    return base | {"disposition": "throttled"}


async def trigger_for_group(group):
    """Try to start a download job for a fanqie_local candidate group.

    Returns the disposition dict, or {"skipped": True} when the group has no
    fanqie_local source.
    """
    book_id = find_fanqie_book_id(group)
    if not book_id:
        return {"skipped": True, "disposition": "skipped"}
    return await ensure_fanqie_download_job(book_id)


async def trigger_for_book(book):
    """Try to start a download job for a created shared book (fanqie_local)."""
    if str(book.get("primarySourceId") or "") != _FANQIE_SOURCE_ID:
        return {"skipped": True, "disposition": "skipped"}
    book_id = fanqie_book_id_from_url(book.get("primaryBookUrl"))
    if not book_id:
        return {"skipped": True, "disposition": "skipped"}
    return await ensure_fanqie_download_job(book_id)


def spawn_trigger_for_book(book):
    """Fire-and-forget the fanqie_local download trigger for a created book.

    Never blocks the subscription response and never raises. Uses a tracked
    task set so the task is not garbage collected mid-flight.
    """
    if str(book.get("primarySourceId") or "") != _FANQIE_SOURCE_ID:
        return {"disposition": "skipped", "started": False}

    async def _run():
        try:
            await trigger_for_book(book)
        except Exception:
            logger.warning("fanqie_local download trigger failed", exc_info=True)

    try:
        task = asyncio.create_task(_run())
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
        return {"disposition": "spawned", "started": True}
    except RuntimeError:
        # No running event loop (sync call site) -> skip, reader path retries.
        return {"disposition": "no_loop", "started": False}
