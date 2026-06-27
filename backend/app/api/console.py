"""Console API endpoints for plugin governance, testing, search jobs, explore, books, and configuration."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.config import APP_PHASE
from app.core.app_config import AppConfig
from app.core.aggregate_config import load_aggregate_config, save_aggregate_config, update_progress
from app.core.source_generator import write_aggregate_source
from app.services.catalog import Catalog
from app.services.book_catalog import BookCatalog
from app.services.cookie_store import CookieStore
from app.services.search_jobs import SearchJobService
from app.services.live_acceptance import LiveAcceptanceService
from app.services.live_check_repository import LiveCheckRepository
from app.services.update_scheduler import UpdateScheduler
from app.services.cache import Cache
from app.services.source_ping import SourcePingService
from app.services.login_browser_service import login_browser_service
from app.services.official_auth.manager import official_auth_manager
from app.services.aggregate_reviews import empty_aggregate_reviews
from app.services.aggregate_processor import AggregateProcessor
from app.services.aggregate_settings import AggregateSettingsRepository
from app.services.library_books import library_books_service
from app.source_plugins.loader import PluginLoader
from app.source_plugins.scheduler import PluginScheduler, get_plugin_scheduler
from app.services.user_auth import auth_service

console_router = APIRouter(prefix="/api/console")


def console_route(method: str, path: str, **kwargs):
    """Register a console API route."""
    return getattr(console_router, method)(path, **kwargs)


def _legacy_archived(feature: str) -> dict:
    return {
        "archived": True,
        "feature": feature,
        "message": "旧 Reading/Legado 规则引擎能力已归档，后续按 Python source plugin 体系重建。",
    }


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _aggregate_book_settings(payload: str) -> dict:
    try:
        return json.loads(payload or "{}")
    except Exception:
        return {}


def _shared_book_storage_read_mode() -> str:
    workflow = AggregateSettingsRepository().content_workflow()
    mode = str(workflow.get("sharedBookStorageReadMode", "legacy") or "legacy").strip().lower()
    return "legacy" if mode == "legacy" else "shared"


def _is_admin_role(user) -> bool:
    return str(getattr(user, "role", "") or "").strip().lower() == "admin"


def _sanitize_source_map_summary(items: list[dict] | None) -> list[dict]:
    sanitized = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        sanitized.append(
            {
                "bookId": item.get("bookId", "") or "",
                "sourceId": item.get("sourceId", "") or "",
                "sourceName": item.get("sourceName", "") or "",
                "score": int(item.get("score", 0) or 0),
                "chapterCount": int(item.get("chapterCount", 0) or 0),
                "lastChapter": item.get("lastChapter", "") or "",
                "bookStatus": item.get("bookStatus", "") or "",
                "name": item.get("name", "") or "",
                "author": item.get("author", "") or "",
            }
        )
    return sanitized


def _sanitize_trace_summary(summary: dict | None) -> dict:
    payload = summary if isinstance(summary, dict) else {}
    return {
        "chapterStatus": payload.get("chapterStatus", "") or "",
        "selectedSource": payload.get("selectedSource", "") or "",
        "selectedContentSource": payload.get("selectedContentSource", "") or "",
        "fallbackSourceId": payload.get("fallbackSourceId", "") or "",
        "alignmentPassed": payload.get("alignmentPassed"),
        "alignmentReason": payload.get("alignmentReason", "") or "",
        "titleSimilarity": payload.get("titleSimilarity"),
        "previewSimilarity": payload.get("previewSimilarity"),
        "aiModel": payload.get("aiModel", "") or "",
        "aiTokens": int(payload.get("aiTokens", 0) or 0),
        "processedAt": payload.get("processedAt", "") or "",
        "traceHash": payload.get("traceHash", "") or "",
    }


def _load_legacy_library_book_summary(book_id: str) -> dict:
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        row = _fetch_aggregate_book_row(conn, book_id)
    if not row:
        return {"bookId": book_id, "found": False}
    payload = _serialize_aggregate_book_row(row)
    payload["found"] = True
    return payload


def _load_shared_library_book_summary(book_id: str, *, admin_view: bool = False) -> dict:
    book = library_books_service.get_book(book_id)
    if not book:
        return {"bookId": book_id, "found": False}
    shared_metadata = library_books_service.load_shared_metadata(book_id)
    source_map = shared_metadata.get("sourceMap") if isinstance(shared_metadata.get("sourceMap"), dict) else {}
    health = source_map.get("health") if isinstance(source_map.get("health"), dict) else {}
    source_summary = _sanitize_source_map_summary(
        library_books_service.build_source_map_summary(shared_metadata)
    )
    payload = {
        "bookId": book_id,
        "found": True,
        "book": book,
        "bookState": library_books_service.build_book_state_summary(shared_metadata),
        "sourceMap": {
            "summary": source_summary,
            "health": {
                "status": str(health.get("status", "") or ""),
                "lastVerifiedAt": str(health.get("lastVerifiedAt", "") or ""),
                "missingCriticalSource": bool(health.get("missingCriticalSource")),
            },
        },
        "sourceMapSummary": source_summary,
        "sourceMapRefresh": library_books_service.source_map_refresh_state(book_id),
    }
    if admin_view:
        payload["payload"] = library_books_service.load_payload(book_id)
    return payload


def _list_legacy_library_book_chapters(
    book_id: str,
    *,
    page: int = 1,
    pageSize: int = 50,
    status: str = "all",
    keyword: str = "",
) -> dict:
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    page = _bounded_page(page, 1, 1000000)
    page_size = _bounded_page(pageSize, 50, 200)
    where = ["aggregate_book_id = ?"]
    params: list = [book_id]
    if status and status != "all":
        where.append("status = ?")
        params.append(status)
    if keyword:
        where.append("title LIKE ?")
        params.append(f"%{keyword}%")
    where_sql = "WHERE " + " AND ".join(where)
    offset = (page - 1) * page_size
    with sqlite3.connect(DB_PATH) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM aggregate_chapter_tasks {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT chapter_id, chapter_index, title, status, content_length, ai_model,
                   ai_total_tokens, deviation_score, ai_self_score, fallback_source_id, retry_count,
                   last_processed_at, error
            FROM aggregate_chapter_tasks
            {where_sql}
            ORDER BY COALESCE(chapter_index, 999999), created_at
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
    items = [
        {
            "chapterId": row[0],
            "chapterIndex": row[1] or 0,
            "title": row[2] or "",
            "status": row[3] or "pending",
            "contentLength": int(row[4] or 0),
            "aiModel": row[5] or "",
            "aiTotalTokens": int(row[6] or 0),
            "deviationScore": float(row[7] or 0.0),
            "aiSelfScore": float(row[8] or 0.0),
            "fallbackSourceId": row[9] or "",
            "retryCount": int(row[10] or 0),
            "lastProcessedAt": row[11] or "",
            "error": row[12] or "",
        }
        for row in rows
    ]
    return {"items": items, "page": page, "pageSize": page_size, "total": total}


def _list_shared_library_book_chapters(
    book_id: str,
    *,
    page: int = 1,
    pageSize: int = 50,
    status: str = "all",
    keyword: str = "",
) -> dict:
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    page = _bounded_page(page, 1, 1000000)
    page_size = _bounded_page(pageSize, 50, 200)
    where = ["aggregate_book_id = ?"]
    params: list = [book_id]
    if status and status != "all":
        where.append("status = ?")
        params.append(status)
    if keyword:
        where.append("title LIKE ?")
        params.append(f"%{keyword}%")
    where_sql = "WHERE " + " AND ".join(where)
    offset = (page - 1) * page_size
    with sqlite3.connect(DB_PATH) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM aggregate_chapter_tasks {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT chapter_id, source_chapter_id, chapter_index, title, status, placeholder,
                   content_length, processed_content, last_processed_at, source_word_count,
                   preview_only, primary_source_chapter_url
            FROM aggregate_chapter_tasks
            {where_sql}
            ORDER BY COALESCE(chapter_index, 999999), created_at
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
    items = [
        {
            "chapterId": row[0],
            "sourceChapterId": row[1] or "",
            "chapterIndex": int(row[2] or 0),
            "title": row[3] or "",
            "status": row[4] or "pending",
            "placeholder": bool(row[5]),
            "contentLength": int(row[6] or 0),
            "hasContent": bool(row[7]),
            "processedAt": row[8] or "",
            "sourceWordCount": int(row[9] or 0),
            "previewOnly": bool(row[10]),
            "primarySourceChapterUrl": row[11] or "",
        }
        for row in rows
    ]
    return {"items": items, "page": page, "pageSize": page_size, "total": total}


def _list_library_book_logs(book_id: str, *, limit: int = 50, offset: int = 0, admin_view: bool = False) -> dict:
    read_mode = _shared_book_storage_read_mode()
    if read_mode == "shared":
        return _list_shared_library_book_logs(book_id, limit=limit, offset=offset, admin_view=admin_view)
    return _list_legacy_library_book_logs(book_id, limit=limit, offset=offset, admin_view=admin_view)


def _list_legacy_library_book_logs(book_id: str, *, limit: int = 50, offset: int = 0, admin_view: bool = False) -> dict:
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM aggregate_operation_logs WHERE aggregate_book_id = ?",
            (book_id,),
        ).fetchone()[0]
        rows = conn.execute(
            """
            SELECT id, operation_type, actor_role, actor_user_id, created_at, before_json, after_json
            FROM aggregate_operation_logs
            WHERE aggregate_book_id = ?
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (book_id, max(1, int(limit or 50)), max(0, int(offset or 0))),
        ).fetchall()
    items = []
    for row in rows:
        item = {
            "id": int(row[0]),
            "operationType": row[1] or "",
            "actorRole": row[2] or "",
            "createdAt": row[4] or "",
        }
        if admin_view:
            item["actorUserId"] = row[3] or ""
            item["beforeJson"] = row[5] or ""
            item["afterJson"] = row[6] or ""
        items.append(item)
    return {"bookId": book_id, "items": items, "limit": max(1, int(limit or 50)), "offset": max(0, int(offset or 0)), "total": total}


def _list_shared_library_book_logs(book_id: str, *, limit: int = 50, offset: int = 0, admin_view: bool = False) -> dict:
    from app.services.library_books import library_books_service
    from app.services.shared_book_runtime import SharedBookProcessLogger

    book = library_books_service.get_book(book_id)
    if not book:
        return {"bookId": book_id, "items": [], "limit": limit, "offset": offset, "total": 0}

    logger = SharedBookProcessLogger(library_books_service.shared_book_storage)
    result = logger.read(
        book_name=str(book.get("name", "") or ""),
        author=str(book.get("author", "") or ""),
        limit=limit,
        offset=offset,
    )
    return {
        "bookId": book_id,
        "items": result["items"],
        "limit": result["limit"],
        "offset": result["offset"],
        "total": result["total"],
    }


def _load_library_book_chapter_progress(book_id: str, chapter_id: str) -> dict:
    read_mode = _shared_book_storage_read_mode()
    if read_mode == "shared":
        return _load_shared_library_book_chapter_progress(book_id, chapter_id)
    return _load_legacy_library_book_chapter_progress(book_id, chapter_id)


def _load_legacy_library_book_chapter_progress(book_id: str, chapter_id: str) -> dict:
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT act.chapter_id, act.chapter_index, act.title, act.status, act.preview_only,
                   act.content_length, act.source_word_count, act.last_processed_at, act.updated_at,
                   act.fallback_source_id, abt.primary_source_id, act.source_alignment_json,
                   act.ai_model, act.ai_total_tokens, act.trace_hash
            FROM aggregate_chapter_tasks act
            LEFT JOIN aggregate_book_tasks abt ON act.aggregate_book_id = abt.aggregate_book_id
            WHERE act.aggregate_book_id = ? AND act.chapter_id = ?
            """,
            (book_id, chapter_id),
        ).fetchone()
    if not row:
        return {"bookId": book_id, "chapterId": chapter_id, "found": False}
    try:
        alignment = json.loads(row[11] or "{}")
    except Exception:
        alignment = {}
    trace_summary = _sanitize_trace_summary(
        {
            "chapterStatus": row[3] or "pending",
            "selectedSource": alignment.get("selectedSource", "") or row[10] or "",
            "selectedContentSource": alignment.get("selectedContentSource", "") or "",
            "fallbackSourceId": row[9] or "",
            "alignmentPassed": alignment.get("alignmentPassed"),
            "alignmentReason": alignment.get("alignmentReason", "") or "",
            "titleSimilarity": alignment.get("titleSimilarity"),
            "previewSimilarity": alignment.get("previewSimilarity"),
            "aiModel": row[12] or "",
            "aiTokens": int(row[13] or 0),
            "processedAt": row[7] or row[8] or "",
            "traceHash": row[14] or "",
        }
    )
    return {
        "bookId": book_id,
        "chapterId": row[0],
        "chapterIndex": int(row[1] or 0),
        "title": row[2] or "",
        "status": row[3] or "pending",
        "previewOnly": bool(row[4]),
        "contentLength": int(row[5] or 0),
        "sourceWordCount": int(row[6] or 0),
        "found": True,
        "traceSummary": trace_summary,
    }


def _load_shared_library_book_chapter_progress(book_id: str, chapter_id: str) -> dict:
    from app.services.library_books import library_books_service
    from app.services.shared_book_runtime import SharedBookProcessLogger, build_chapter_progress_payload

    book = library_books_service.get_book(book_id)
    if not book:
        return {"bookId": book_id, "chapterId": chapter_id, "found": False}

    book_name = str(book.get("name", "") or "").strip()
    author = str(book.get("author", "") or "").strip()
    storage = library_books_service.shared_book_storage

    chapter_index_path = storage.chapter_index_path(book_name=book_name, author=author)
    chapter_index = storage._read_json(chapter_index_path) or {"chapters": []}
    target_entry: dict[str, Any] | None = None
    for entry in chapter_index.get("chapters", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("index") == int(chapter_id) or str(entry.get("index", "")) == chapter_id:
            target_entry = entry
            break

    if target_entry is None:
        return {"bookId": book_id, "chapterId": chapter_id, "found": False}

    chapter_index_value = int(target_entry.get("index", 0) or 0)
    chapter_title = str(target_entry.get("title", "") or "").strip()
    file_name = str(target_entry.get("file", "") or "").strip()
    chapter_path = storage.shared_book_dir(book_name=book_name, author=author) / file_name if file_name else None

    trace: dict[str, Any] | None = None
    if chapter_path and chapter_path.exists():
        try:
            trace = storage.parse_trace_block(chapter_path.read_text(encoding="utf-8"))
        except Exception:
            trace = None

    logger = SharedBookProcessLogger(storage)
    logs = logger.read(
        book_name=book_name,
        author=author,
        chapter_index=chapter_index_value,
        limit=20,
    )["items"]

    return build_chapter_progress_payload(
        book_id=book_id,
        chapter_index=chapter_index_value,
        chapter_title=chapter_title,
        chapter_trace=trace,
        logs=logs,
    )


async def _manual_source_map_refresh(book_id: str, payload: dict | None = None) -> dict:
    book = library_books_service.get_book(book_id)
    if not book:
        return {"ok": False, "bookId": book_id, "error": "书籍不存在"}
    scheduler = SharedBookScheduler()
    result = await scheduler.run_source_map_refresh_now(
        book_id,
        payload=library_books_service.load_payload(book_id),
        force=True if payload is None else bool(payload.get("force", True)),
    )
    return {"ok": bool(result.get("success")), "bookId": book_id, "result": result}


def _manual_library_book_repair(book_id: str, payload: dict | None = None) -> dict:
    del payload
    book = library_books_service.get_book(book_id)
    if not book:
        return {"ok": False, "bookId": book_id, "error": "书籍不存在"}
    book_name = str(book.get("name", "") or "").strip()
    author = str(book.get("author", "") or "").strip()
    storage = library_books_service.shared_book_storage
    metadata_path = storage.metadata_path(book_name=book_name, author=author)
    chapter_index_path = storage.chapter_index_path(book_name=book_name, author=author)
    if not metadata_path.exists() or not chapter_index_path.exists():
        return {"ok": False, "bookId": book_id, "error": "shared_metadata_missing"}
    metadata_payload = _read_json(metadata_path, {})
    chapter_index_payload = _read_json(chapter_index_path, {})
    chapter_traces = {}
    for item in chapter_index_payload.get("chapters", []) if isinstance(chapter_index_payload, dict) else []:
        if not isinstance(item, dict):
            continue
        file_name = str(item.get("file", "") or "").strip()
        if not file_name:
            continue
        chapter_path = metadata_path.parent / file_name
        if not chapter_path.exists():
            continue
        try:
            trace = storage.parse_trace_block(chapter_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        chapter_index = int(trace.get("chapterIndex", 0) or 0)
        if chapter_index > 0:
            chapter_traces[chapter_index] = trace
    repaired = storage.rebuild_metadata_summary(
        metadata_payload,
        chapter_index_payload=chapter_index_payload if isinstance(chapter_index_payload, dict) else {},
        chapter_traces=chapter_traces,
    )
    storage.atomic_write_json(metadata_path, repaired)
    return {
        "ok": True,
        "bookId": book_id,
        "bookState": repaired.get("bookState", {}),
        "sourceMapSummary": _sanitize_source_map_summary(repaired.get("sourceMapSummary", [])),
    }


async def _manual_library_book_update_check(book_id: str) -> dict:
    return await UpdateScheduler().run_check(book_id)


# ---- Plugins ----

_plugin_loader = PluginLoader()
_plugin_scheduler = get_plugin_scheduler()


def _smoke_dir(plugin_dir: Path) -> Path:
    preferred = plugin_dir / "smoke"
    legacy = plugin_dir / "tests"
    if preferred.exists():
        return preferred
    return legacy


def _plugin_access_type(plugin) -> str:
    browser_mode = (plugin.metadata.browser or {}).get("mode", "none")
    return "Browser" if browser_mode == "required" else "HTTP"


def _plugin_source_type(plugin) -> str:
    return _plugin_access_type(plugin)


def _plugin_last_modified(plugin) -> str:
    return getattr(plugin.source, "last_modified", "") if plugin.source else ""


def _plugin_health(plugin_id: str) -> dict:
    from app.services.plugin_runtime_state import get_runtime_state

    state = get_runtime_state().get_state(plugin_id)
    last_ping = state.get("lastPing") or {}
    last_smoke = state.get("lastSmoke") or {}
    last_error = state.get("lastError") or {}
    return {
        "pingStatus": last_ping.get("status", "unknown"),
        "pingLatencyMs": last_ping.get("latencyMs", 0),
        "pingTimestamp": last_ping.get("timestamp"),
        "lastTestResult": "pass" if last_smoke.get("pass") else "fail" if last_smoke else None,
        "lastSmokeTimestamp": last_smoke.get("timestamp"),
        "lastError": last_error.get("message", ""),
        "lastErrorTimestamp": last_error.get("timestamp"),
    }


@console_route("get", "/plugins")
def list_plugins():
    plugins = _plugin_scheduler._plugins
    return {
        "items": [
            {
                "pluginId": p.metadata.id,
                "name": p.metadata.name,
                "version": p.metadata.version,
                "enabled": p.metadata.enabled,
                "official": p.metadata.is_official_source(),
                "capabilities": p.capabilities,
                "domains": p.metadata.domains,
                "tags": p.metadata.tags,
                "auth": p.metadata.auth,
                "content": p.metadata.content,
                "accessType": _plugin_access_type(p),
                "sourceType": _plugin_source_type(p),
                "proxyRequired": bool((p.metadata.proxy or {}).get("required")),
                "proxyMode": (p.metadata.proxy or {}).get("mode", "auto"),
                "browser": p.metadata.browser,
                "lastModified": _plugin_last_modified(p),
                "health": _plugin_health(p.metadata.id),
            }
            for p in plugins.values()
        ],
        "total": len(plugins),
    }


@console_route("get", "/official-sources")
async def list_official_sources():
    plugins = _plugin_scheduler._plugins
    cookie_store = CookieStore()
    items = []
    for plugin in plugins.values():
        auth_mode = (plugin.metadata.auth or {}).get("mode", "none")
        if not plugin.metadata.is_official_source() and auth_mode == "none":
            continue
        payload = cookie_store.load(plugin.metadata.id)
        has_cookies = bool(payload) and (
            bool(payload.get("cookies")) if isinstance(payload, dict) else True
        )
        auth_status = {
            "authenticated": False,
            "authStatus": "anonymous" if not has_cookies else "unknown",
            "accountName": "",
            "message": "",
            "requiredActions": ["check_auth_status"] if has_cookies else [],
            "hasCookies": has_cookies,
            "cookieDomains": sorted((payload.get("cookies") or {}).keys()) if isinstance(payload, dict) and isinstance(payload.get("cookies"), dict) else [],
        }
        if "auth" in plugin.capabilities:
            ctx = _plugin_scheduler._make_ctx(plugin.metadata.id)
            try:
                result = await plugin.source.auth_status(ctx)
                auth_status = {
                    **auth_status,
                    **result,
                    "hasCookies": has_cookies,
                    "cookieDomains": auth_status["cookieDomains"],
                }
            except Exception as exc:
                auth_status = {
                    **auth_status,
                    "message": str(exc),
                }
            finally:
                await ctx._fetcher.close()

        items.append({
            "pluginId": plugin.metadata.id,
            "name": plugin.metadata.name,
            "version": plugin.metadata.version,
            "enabled": plugin.metadata.enabled,
            "domains": plugin.metadata.domains,
            "baseUrls": plugin.metadata.base_urls,
            "tags": plugin.metadata.tags,
            "auth": plugin.metadata.auth,
            "content": plugin.metadata.content,
            "lastModified": _plugin_last_modified(plugin),
            "browser": plugin.metadata.browser,
            "official": plugin.metadata.is_official_source(),
            "hasCookies": has_cookies,
            "authStatus": auth_status,
        })
    items.sort(key=lambda item: (not item["official"], item["name"], item["pluginId"]))
    return {"items": items, "total": len(items)}


@console_route("get", "/plugins/{plugin_id}")
def get_plugin(plugin_id: str):
    plugin = _plugin_scheduler._plugins.get(plugin_id)
    if not plugin:
        return {"error": "插件不存在"}
    return {
        "pluginId": plugin.metadata.id,
        "name": plugin.metadata.name,
        "version": plugin.metadata.version,
        "enabled": plugin.metadata.enabled,
        "official": plugin.metadata.is_official_source(),
        "capabilities": plugin.capabilities,
        "domains": plugin.metadata.domains,
        "baseUrls": plugin.metadata.base_urls,
        "tags": plugin.metadata.tags,
        "auth": plugin.metadata.auth,
        "content": plugin.metadata.content,
        "accessType": _plugin_access_type(plugin),
        "sourceType": _plugin_source_type(plugin),
        "proxyRequired": bool((plugin.metadata.proxy or {}).get("required")),
        "proxyMode": (plugin.metadata.proxy or {}).get("mode", "auto"),
        "browser": plugin.metadata.browser,
        "rateLimit": plugin.metadata.rate_limit,
        "proxy": plugin.metadata.proxy,
        "sourceSeed": plugin.metadata.source_seed,
        "lastModified": _plugin_last_modified(plugin),
        "health": _plugin_health(plugin_id),
    }


@console_route("get", "/plugins/{plugin_id}/attempts")
def get_plugin_attempts(plugin_id: str, limit: int = 20):
    plugin = _plugin_scheduler._plugins.get(plugin_id)
    if not plugin:
        return {"error": "插件不存在"}
    from app.services.plugin_runtime_state import get_runtime_state

    attempts = get_runtime_state().get_attempts(plugin_id, limit=limit)
    return {"pluginId": plugin_id, "attempts": attempts}


@console_route("post", "/plugins/reload")
def reload_plugins():
    _plugin_scheduler.reload()
    return {"reloaded": True, "count": len(_plugin_scheduler._plugins)}


@console_route("post", "/plugins/{plugin_id}/enable")
def enable_plugin(plugin_id: str, payload: dict):
    plugin = _plugin_scheduler._plugins.get(plugin_id)
    if not plugin:
        return {"error": "插件不存在"}
    enabled = payload.get("enabled", True)
    plugin.metadata.enabled = enabled
    AppConfig.get().set_plugin_enabled(plugin_id, enabled)
    return {"pluginId": plugin_id, "enabled": enabled}


@console_route("post", "/plugins/batch-enable")
def batch_enable_plugins(payload: dict):
    plugin_ids = payload.get("pluginIds", [])
    enabled = payload.get("enabled", True)
    cfg = AppConfig.get()
    results = []
    for plugin_id in plugin_ids:
        plugin = _plugin_scheduler._plugins.get(plugin_id)
        if plugin:
            plugin.metadata.enabled = enabled
            cfg.set_plugin_enabled(plugin_id, enabled)
            results.append({"pluginId": plugin_id, "enabled": enabled})
        else:
            results.append({"pluginId": plugin_id, "error": "插件不存在"})
    return {"results": results}


@console_route("post", "/plugins/batch-delete")
def batch_delete_plugins(payload: dict):
    plugin_ids = payload.get("pluginIds", [])
    cfg = AppConfig.get()
    results = []
    for plugin_id in plugin_ids:
        plugin = _plugin_scheduler._plugins.get(plugin_id)
        if plugin:
            plugin.metadata.enabled = False
        cfg.set_plugin_enabled(plugin_id, False)
        # Remove from filesystem
        source_dir = Path("plugins/sources") / plugin_id
        if source_dir.exists():
            import shutil
            shutil.rmtree(source_dir)
        # Remove from in-memory scheduler
        if plugin_id in _plugin_scheduler._plugins:
            del _plugin_scheduler._plugins[plugin_id]
        results.append({"pluginId": plugin_id, "deleted": True})
    return {"results": results}


@console_route("post", "/plugins/ping")
async def ping_all_plugins(payload: dict | None = None):
    payload = payload or {}
    plugin_ids = payload.get("pluginIds")
    if plugin_ids:
        plugin_ids = [pid for pid in plugin_ids if pid in _plugin_scheduler._plugins]
    service = SourcePingService(scheduler=_plugin_scheduler)
    results = await service.ping_all(plugin_ids)
    return {"results": results}


@console_route("post", "/plugins/{plugin_id}/ping")
async def ping_one_plugin(plugin_id: str):
    if plugin_id not in _plugin_scheduler._plugins:
        return {"error": "插件不存在"}
    service = SourcePingService(scheduler=_plugin_scheduler)
    result = await service.ping_one(plugin_id)
    return result


@console_route("post", "/plugins/{plugin_id}/smoke")
async def smoke_plugin(plugin_id: str, payload: dict | None = None):
    keyword = (payload or {}).get("keyword", "凡人修仙传")
    result = await _plugin_scheduler.smoke(plugin_id, keyword=keyword)
    from app.services.plugin_runtime_state import get_runtime_state

    runtime_state = get_runtime_state()
    runtime_state.record_smoke(
        plugin_id,
        passed=bool(result.get("pass")),
        message=result.get("message", ""),
        error=result.get("error"),
    )
    return result


@console_route("get", "/plugins/{plugin_id}/auth")
async def get_plugin_auth(plugin_id: str):
    plugin = _plugin_scheduler._plugins.get(plugin_id)
    if not plugin:
        return {"error": "插件不存在"}
    cookie_store = CookieStore()
    payload = cookie_store.load(plugin_id)
    has_cookies = bool(payload) and (
        bool(payload.get("cookies")) if isinstance(payload, dict) else True
    )
    cookie_domains: list[str] = []
    if isinstance(payload, dict):
        cookies = payload.get("cookies")
        if isinstance(cookies, dict):
            cookie_domains = sorted(cookies.keys())

    auth_meta = plugin.metadata.auth or {}
    if auth_meta.get("mode", "none") == "none":
        browser_meta = plugin.metadata.browser or {}
        if browser_meta.get("mode") == "required":
            return {
                "sourceId": plugin_id,
                "mode": "browser_bypass",
                "authenticated": False,
                "accountName": "",
                "expiresAt": "",
                "message": (
                    "已保存 Cookie，可用于后端模拟访问。"
                    if has_cookies
                    else "该插件无需账号登录；如遇 Cloudflare/浏览器挑战，后续按绕过策略处理，不再提供手动验证链路。"
                ),
                "requiredActions": ["retry_live_check"] if has_cookies else ["bypass_required"],
                "hasCookies": has_cookies,
                "cookieDomains": cookie_domains,
                "verificationStatus": "cookies_saved" if has_cookies else "bypass_required",
            }
        return {
            "sourceId": plugin_id,
            "mode": "none",
            "authenticated": False,
            "accountName": "",
            "expiresAt": "",
            "message": "该插件无需登录",
            "requiredActions": [],
            "hasCookies": has_cookies,
            "cookieDomains": cookie_domains,
        }
    if "auth" not in plugin.capabilities:
        return {
            "sourceId": plugin_id,
            "mode": auth_meta.get("mode", "optional"),
            "authenticated": False,
            "accountName": "",
            "expiresAt": "",
            "message": "该插件尚未实现登录检测方法",
            "requiredActions": ["manual_login"] if auth_meta.get("loginUrl") else [],
            "hasCookies": has_cookies,
            "cookieDomains": cookie_domains,
        }
    ctx = _plugin_scheduler._make_ctx(plugin_id)
    try:
        result = await plugin.source.auth_status(ctx)
        result.setdefault("mode", auth_meta.get("mode", "optional"))
        if not result.get("authenticated") and has_cookies:
            result.setdefault("requiredActions", ["check_auth_status"])
            if not result.get("message"):
                result["message"] = "Cookie 已保存，但远程登录态校验未通过"
    except Exception as exc:
        result = {
            "sourceId": plugin_id,
            "mode": auth_meta.get("mode", "optional"),
            "authenticated": False,
            "accountName": "",
            "expiresAt": "",
            "message": str(exc),
            "requiredActions": ["check_auth_status"] if has_cookies else [],
            "hasCookies": has_cookies,
            "cookieDomains": cookie_domains,
        }
    finally:
        await ctx._fetcher.close()
    return result


@console_route("post", "/plugins/{plugin_id}/login")
async def prepare_plugin_login(plugin_id: str):
    plugin = _plugin_scheduler._plugins.get(plugin_id)
    if not plugin:
        return {"error": "插件不存在"}
    if hasattr(plugin.source, "prepare_login") and callable(getattr(plugin.source, "prepare_login")):
        ctx = _plugin_scheduler._make_ctx(plugin_id)
        try:
            return await plugin.source.prepare_login(ctx)
        finally:
            await ctx._fetcher.close()
    auth = plugin.metadata.auth
    login_url = auth.get("loginUrl", plugin.metadata.base_urls[0] if plugin.metadata.base_urls else "")
    cookie_domains = auth.get("cookieDomains", plugin.metadata.domains)
    return {
        "sourceId": plugin_id,
        "mode": "manual_browser",
        "loginUrl": login_url,
        "instructions": "在打开的浏览器中完成登录，然后回到后台点击检测登录状态。",
        "cookieDomains": cookie_domains,
    }


@console_route("post", "/plugins/{plugin_id}/auth/check")
async def check_plugin_auth(plugin_id: str):
    return await get_plugin_auth(plugin_id)


@console_route("post", "/plugins/{plugin_id}/cookies/clear")
def clear_plugin_cookies(plugin_id: str):
    plugin = _plugin_scheduler._plugins.get(plugin_id)
    if not plugin:
        return {"error": "插件不存在"}
    ctx = _plugin_scheduler._make_ctx(plugin_id)
    ctx.cookies.clear()
    CookieStore().clear(plugin_id)
    return {"cleared": True, "pluginId": plugin_id}


@console_route("post", "/plugins/{plugin_id}/login-browser")
async def start_login_browser(plugin_id: str):
    """Launch a headed browser window for the user to complete manual login.

    The browser opens the plugin's configured login URL. The user interacts
    with the page (SMS code, captcha, etc.) manually. The backend polls for
    login-success indicators and extracts cookies automatically.
    """
    plugin = _plugin_scheduler._plugins.get(plugin_id)
    if not plugin:
        return {"error": "插件不存在"}

    # Resolve login URL and cookie domains (same logic as prepare_login)
    auth = plugin.metadata.auth or {}
    login_url = auth.get("loginUrl", "")
    if not login_url and plugin.metadata.base_urls:
        login_url = plugin.metadata.base_urls[0]
    cookie_domains = auth.get("cookieDomains", plugin.metadata.domains or ["qidian.com"])

    session = await login_browser_service.start(
        plugin_id=plugin_id,
        login_url=login_url or "https://passport.qidian.com/",
        cookie_domains=cookie_domains,
    )
    return {
        "pluginId": plugin_id,
        "status": session.status,
        "message": session.message,
    }


@console_route("get", "/plugins/{plugin_id}/login-browser/status")
async def get_login_browser_status(plugin_id: str):
    """Poll the status of an active login-browser session."""
    session = await login_browser_service.get(plugin_id)
    if not session:
        return {"pluginId": plugin_id, "status": "none", "message": "没有活跃的登录会话"}

    result = {
        "pluginId": plugin_id,
        "status": session.status,
        "message": session.message,
        "hasCookies": session.status == "success" and bool(session.cookies),
        "cookieDomains": list(session.cookies.keys()) if session.cookies else [],
    }

    # If completed, persist cookies and clean up
    if session.status in ("success", "failed", "timeout", "cancelled"):
        if session.status == "success" and session.cookies:
            await official_auth_manager.save_cookies_and_probe(plugin_id, session.cookies)
        await login_browser_service.cleanup(plugin_id)

    return result


@console_route("delete", "/plugins/{plugin_id}/login-browser")
async def cancel_login_browser(plugin_id: str):
    """Cancel an active login-browser session."""
    ok = await login_browser_service.cancel(plugin_id)
    await login_browser_service.cleanup(plugin_id)
    return {"pluginId": plugin_id, "cancelled": ok}


# ---- Official Source Login (通用登录协议层) ----

@console_route("get", "/official-sources/{plugin_id}/login-capabilities")
def get_login_capabilities(plugin_id: str):
    """Get available login methods for an official source."""
    return official_auth_manager.capabilities(plugin_id)


@console_route("post", "/official-sources/{plugin_id}/login/phone/request-code")
async def official_login_phone_request(plugin_id: str, payload: dict):
    """Step 1 of phone login: request SMS verification code.

    Payload: {"phone": "13800138000", "sessionId": "", "challengeToken": "", "challengeRandstr": ""}
    Full payload is forwarded to private auth_api, including challenge params.
    """
    if not payload.get("phone"):
        return {"ok": False, "error": "缺少手机号"}
    return official_auth_manager.request_phone_code(plugin_id, payload)


@console_route("post", "/official-sources/{plugin_id}/login/phone/verify")
async def official_login_phone_verify(plugin_id: str, payload: dict):
    """Step 2 of phone login: verify SMS code and complete login.

    Payload: {"sessionId": "xxx", "phone": "13800138000", "code": "123456", "challengeToken": ""}
    """
    return await official_auth_manager.verify_phone_code(plugin_id, payload)


@console_route("post", "/official-sources/{plugin_id}/login/cookie/verify")
async def official_login_cookie_verify(plugin_id: str, payload: dict):
    """Verify pasted cookies for an official source.

    Payload: {"cookieText": "ywguid=...; ywkey=..."}
    """
    cookie_text = payload.get("cookieText", "")
    if not cookie_text:
        return {"ok": False, "error": "缺少 Cookie 文本"}
    return await official_auth_manager.verify_cookie(plugin_id, cookie_text)


@console_route("post", "/official-sources/{plugin_id}/login/logout")
async def official_login_logout(plugin_id: str):
    """Clear auth state for an official source."""
    return official_auth_manager.logout(plugin_id)


@console_route("get", "/official-sources/{plugin_id}/login/debug-trace")
def official_login_debug_trace(plugin_id: str):
    """Return recent login step traces for an official source.

    Traces include the payload sent to the private auth_api and the raw result
    returned by it, which is useful when comparing Web vs App identity params.
    """
    from app.services.official_auth.sessions import login_trace_store
    from app.services.official_auth.manager import official_auth_manager

    return {
        "pluginId": plugin_id,
        "traces": login_trace_store.get(plugin_id),
        "session": _get_active_login_session(plugin_id),
    }


def _get_active_login_session(plugin_id: str) -> dict | None:
    """Best-effort snapshot of the most recent active login session."""
    from app.services.official_auth.sessions import session_store

    # Find the most recent non-expired session for this plugin.
    candidate = None
    for session in list(session_store._sessions.values()):
        if session.plugin_id == plugin_id and not session.expired():
            if candidate is None or session.created_at > candidate.created_at:
                candidate = session
    return candidate.to_dict() if candidate else None


# ---- Sources ----

@console_route("get", "/sources")
def list_sources(
    enabled_only: bool = False,
    limit: int = 100,
    offset: int = 0,
):
    all_plugins = list(_plugin_scheduler._plugins.values())
    if enabled_only:
        all_plugins = [p for p in all_plugins if p.metadata.enabled]
    total = len(all_plugins)
    page_plugins = all_plugins[offset : offset + limit]
    items = []
    for plugin in page_plugins:
        items.append({
            "pluginId": plugin.metadata.id,
            "name": plugin.metadata.name,
            "version": plugin.metadata.version,
            "enabled": plugin.metadata.enabled,
            "official": plugin.metadata.is_official_source(),
            "capabilities": plugin.capabilities,
            "domains": plugin.metadata.domains,
            "baseUrls": plugin.metadata.base_urls,
            "tags": plugin.metadata.tags,
            "auth": plugin.metadata.auth,
            "content": plugin.metadata.content,
            "proxyMode": (plugin.metadata.proxy or {}).get("mode", "auto"),
            "proxyRequired": bool((plugin.metadata.proxy or {}).get("required")),
            "browser": plugin.metadata.browser,
            "lastModified": _plugin_last_modified(plugin),
        })
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@console_route("get", "/sources/{source_id}")
def get_source(source_id: str):
    plugin = _plugin_scheduler._plugins.get(source_id)
    if not plugin:
        return {"error": "书源不存在"}
    return {
        "source": {
            "pluginId": plugin.metadata.id,
            "name": plugin.metadata.name,
            "version": plugin.metadata.version,
            "enabled": plugin.metadata.enabled,
            "official": plugin.metadata.is_official_source(),
            "capabilities": plugin.capabilities,
            "domains": plugin.metadata.domains,
            "baseUrls": plugin.metadata.base_urls,
            "tags": plugin.metadata.tags,
            "auth": plugin.metadata.auth,
            "content": plugin.metadata.content,
            "proxyMode": (plugin.metadata.proxy or {}).get("mode", "auto"),
            "proxyRequired": bool((plugin.metadata.proxy or {}).get("required")),
            "browser": plugin.metadata.browser,
            "lastModified": _plugin_last_modified(plugin),
        }
    }


@console_route("post", "/sources/{source_id}/test")
async def test_source(source_id: str, payload: dict):
    catalog = Catalog()
    keyword = payload.get("keyword", "凡人修仙传")
    page = payload.get("page", 1)
    stage = payload.get("stage", "search")
    proxy_mode = payload.get("proxyMode")
    result = await catalog.test_source(
        source_id=source_id,
        keyword=keyword,
        page=page,
        stage=stage,
        proxy_mode_override=proxy_mode,
    )
    return result


@console_route("get", "/search/stream")
async def stream_search(keyword: str = "", page: int = 1, limit: int | None = None):
    catalog = Catalog()

    async def event_generator():
        async for event in catalog.stream_search(keyword=keyword, page=page, max_sources_override=limit):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@console_route("post", "/sources/{source_id}/enable")
def enable_source(source_id: str, payload: dict):
    plugin = _plugin_scheduler._plugins.get(source_id)
    enabled = payload.get("enabled", True)
    if plugin:
        plugin.metadata.enabled = enabled
    AppConfig.get().set_plugin_enabled(source_id, enabled)
    return {"sourceId": source_id, "enabled": enabled}


# ---- Search Jobs ----

_search_service = SearchJobService()
_live_check_repository = LiveCheckRepository()
_live_acceptance_service = LiveAcceptanceService(
    scheduler=_plugin_scheduler,
    repository=_live_check_repository,
)


def _schedule_console_search(job_id: str) -> None:
    """Schedule a search job to run in the background event loop."""
    _search_service.schedule_job(job_id)


@console_route("post", "/search-jobs")
async def create_search_job(request: Request, payload: dict):
    """Create a source search job.  Always starts a live search."""
    auth_service.require_admin(request)
    keyword = payload.get("keyword", "")
    page = payload.get("page", 1)
    limit = payload.get("limit")
    source_ids = payload.get("sourceIds")

    job = _search_service.create_job(
        keyword=keyword, page=page, limit=limit,
        source_ids=source_ids, search_mode="source",
    )

    return {
        "jobId": job.job_id,
        "status": "running",
        "keyword": job.keyword,
        "page": job.page,
        "searchMode": "source",
        "sourceCount": len(job.sources),
        "completedCount": 0,
        "successCount": 0,
        "errorCount": 0,
        "timeoutCount": 0,
        "elapsedMs": 0,
        "result": {"items": [], "candidateGroups": []},
        "candidateGroups": [],
        "events": [],
        "liveSearchPending": True,
    }


@console_route("post", "/search/aggregate")
async def create_aggregate_search(request: Request, payload: dict):
    auth_service.require_admin(request)
    return {
        "deprecated": True,
        "message": "即时聚合搜索入口已废弃，请改用 /api/subscribe/search 做订阅发现，或使用普通搜索查看本地书库注入效果。",
    }


@console_route("get", "/search-jobs")
def list_search_jobs(request: Request, limit: int = 20):
    auth_service.require_admin(request)
    return {"items": _search_service.list_jobs(limit=limit)}


@console_route("get", "/search-jobs/{job_id}")
def get_search_job(request: Request, job_id: str):
    """Get search job status and results using the session model."""
    auth_service.require_admin(request)
    # Try session snapshot first (in-memory, includes merged items).
    snapshot = _search_service.session_snapshot(
        job_id, base_api=None, include_official_sources=True
    )
    if snapshot:
        # Apply score filter to items.
        items = snapshot.get("items", [])
        if items:
            filtered_items, score_filter, filtered_count = _search_service._apply_score_filter(items)
            if filtered_count > 0:
                snapshot["items"] = filtered_items
                from app.services.live_acceptance import group_candidates
                snapshot["candidateGroups"] = group_candidates(
                    filtered_items, snapshot.get("keyword", "")
                )
            debug = dict(snapshot.get("debug") or {})
            debug["scoreFilter"] = score_filter
            debug["filteredCount"] = filtered_count
            snapshot["debug"] = debug
        return snapshot

    # Fallback: try DB for historical job.
    job = _search_service.get_job(job_id)
    if not job:
        return {"error": "任务不存在"}
    result = job.result or {}
    items = result.get("items", [])
    candidate_groups = job.candidate_groups or []
    if items:
        filtered_items, score_filter, filtered_count = _search_service._apply_score_filter(items)
        if filtered_count > 0:
            items = filtered_items
            from app.services.live_acceptance import group_candidates
            candidate_groups = group_candidates(items, job.keyword)
        debug = dict(result.get("debug", {}))
        debug["scoreFilter"] = score_filter
        debug["filteredCount"] = filtered_count
        result = {**result, "items": items, "debug": debug}
    # When loaded from DB, job.sources is empty. Use source_count from the
    # result debug or fall back to len(job.sources).
    db_source_count = (
        result.get("debug", {}).get("sourceCount")
        or len(job.sources)
        or 0
    )
    return {
        "jobId": job.job_id,
        "status": job.status,
        "keyword": job.keyword,
        "page": job.page,
        "sourceCount": db_source_count,
        "completedCount": job.completed_count,
        "successCount": job.success_count,
        "errorCount": job.error_count,
        "timeoutCount": job.timeout_count,
        "elapsedMs": job.elapsed_ms,
        "result": result,
        "candidateGroups": candidate_groups,
        "liveSearchPending": job.status in {"running", "pending"},
    }


@console_route("get", "/search-jobs/{job_id}/events")
def get_search_job_events(request: Request, job_id: str, after: int = 0):
    auth_service.require_admin(request)
    events = _search_service.get_events(job_id, after_index=after)
    return {"jobId": job_id, "events": events, "nextAfter": after + len(events)}


@console_route("get", "/search-jobs/{job_id}/candidates")
def get_search_job_candidates(request: Request, job_id: str):
    auth_service.require_admin(request)
    job = _search_service.get_job(job_id)
    if not job:
        return {"error": "任务不存在", "items": []}
    candidates = _search_service.get_candidates(job_id)
    # Apply score filter to candidate groups
    score_filter = _search_service._get_score_filter()
    filtered_candidates = []
    for group in candidates:
        items = [item for item in group.get("items", []) if item.get("score", 0) >= score_filter]
        if items:
            filtered_group = dict(group)
            filtered_group["items"] = items
            filtered_candidates.append(filtered_group)
    return {"jobId": job_id, "items": filtered_candidates, "scoreFilter": score_filter}


@console_route("post", "/search-jobs/{job_id}/candidates/{candidate_id}/verify")
async def verify_search_job_candidate(request: Request, job_id: str, candidate_id: str, payload: dict | None = None):
    auth_service.require_admin(request)
    candidate = _search_service.find_candidate(job_id, candidate_id)
    if not candidate:
        return {"error": "候选不存在", "jobId": job_id, "candidateId": candidate_id}
    job = _search_service.get_job(job_id)
    payload = payload or {}
    chapter_index = payload.get("chapterIndex", 0)
    include_reviews = payload.get("includeReviews", True)
    result = await _live_acceptance_service.verify_candidate(
        candidate,
        keyword=job.keyword if job else "",
        chapter_index=chapter_index,
        include_reviews=bool(include_reviews),
    )
    return {"jobId": job_id, "candidateId": candidate_id, "result": result}


@console_route("post", "/search-jobs/{job_id}/candidates/{candidate_id}/reviews")
async def fetch_search_job_candidate_reviews(request: Request, job_id: str, candidate_id: str, payload: dict | None = None):
    """Fetch chapter reviews independently of chapter content.

    Useful for VIP chapters where the main text is only a preview but reviews
    are still available. This endpoint intentionally allows a longer timeout
    so it can retrieve all review pages asynchronously from the frontend.
    """
    auth_service.require_admin(request)
    candidate = _search_service.find_candidate(job_id, candidate_id)
    if not candidate:
        return {"error": "候选不存在", "jobId": job_id, "candidateId": candidate_id}
    payload = payload or {}
    chapter_index = payload.get("chapterIndex", 0)
    # Allow the caller to cap the backend timeout; default to a generous limit
    # so review pagination can complete without blocking chapter content.
    timeout = payload.get("timeout")
    if timeout is not None:
        try:
            timeout = float(timeout)
        except (TypeError, ValueError):
            timeout = None
    result = await _live_acceptance_service.fetch_reviews(
        candidate,
        chapter_index=chapter_index,
        timeout=timeout,
    )
    return {"jobId": job_id, "candidateId": candidate_id, "result": result}


@console_route("post", "/search-jobs/{job_id}/cancel")
def cancel_search_job(request: Request, job_id: str):
    auth_service.require_admin(request)
    ok = _search_service.cancel_job(job_id)
    return {"jobId": job_id, "cancelled": ok}


@console_route("post", "/search-jobs/{job_id}/subscribe")
async def subscribe_from_search_job(request: Request, job_id: str, payload: dict):
    """Admin shortcut: add a candidate group to the shared library."""
    admin = auth_service.require_admin(request)
    candidate_id = str(payload.get("candidateId", "")).strip()
    added_by_user_id = str(payload.get("addedByUserId", "")).strip() or admin.user_id
    start_chapter_index = max(1, int(payload.get("startChapterIndex", 1) or 1))
    auto_archive = bool(payload.get("autoArchiveOnComplete", True))
    if not candidate_id:
        return {"error": "缺少 candidateId"}
    group = _search_service.find_candidate_group(job_id, candidate_id)
    if not group:
        return {"error": "候选书籍不存在", "jobId": job_id, "candidateId": candidate_id}
    created = await library_books_service.create_or_get_shared_book(
        group,
        added_by_user_id=added_by_user_id,
        start_chapter_index=start_chapter_index,
        auto_archive_on_complete=auto_archive,
    )
    if created.get("created"):
        processor = AggregateProcessor()
        processor.enqueue_book(created["book"]["aggregateBookId"], created["payload"])
        asyncio.create_task(processor.bootstrap_book_until_visible(created["book"]["aggregateBookId"]))
    return {
        "ok": True,
        "created": bool(created.get("created")),
        "book": created.get("book"),
    }


# ---- Live Acceptance ----


@console_route("post", "/plugins/{plugin_id}/live-check")
async def run_plugin_live_check(plugin_id: str, payload: dict | None = None):
    payload = payload or {}
    result = await _live_acceptance_service.run_plugin_live_check(
        plugin_id=plugin_id,
        keyword=payload.get("keyword", "凡人修仙传"),
        candidate_index=int(payload.get("candidateIndex", 0) or 0),
        chapter_index=int(payload.get("chapterIndex", 0) or 0),
        persist=True,
    )
    return result


@console_route("get", "/plugins/{plugin_id}/live-checks")
def list_plugin_live_checks(plugin_id: str, limit: int = 20, offset: int = 0):
    return {
        "pluginId": plugin_id,
        "items": _live_check_repository.list_by_plugin(plugin_id, limit=limit, offset=offset),
        "limit": limit,
        "offset": offset,
    }


@console_route("get", "/plugins/{plugin_id}/live-checks/latest")
def latest_plugin_live_check(plugin_id: str):
    return {"pluginId": plugin_id, "item": _live_check_repository.latest_by_plugin(plugin_id)}


@console_route("get", "/live-checks")
def list_live_checks(limit: int = 50, offset: int = 0):
    return {
        "items": _live_check_repository.list_all(limit=limit, offset=offset),
        "stats": _live_check_repository.stats(),
        "limit": limit,
        "offset": offset,
    }


# ---- Explore ----

@console_route("get", "/explore/sources")
async def list_explore_sources():
    groups = await _plugin_scheduler.explore_groups()
    source_map: dict[str, dict] = {}
    for group in groups.get("groups", []):
        source_id = group.get("sourceId", "")
        if not source_id:
            continue
        source = source_map.setdefault(
            source_id,
            {
                "sourceId": source_id,
                "name": group.get("sourceName", ""),
                "groupCount": 0,
                "groups": [],
            },
        )
        source["groupCount"] += 1
        source["groups"].append(group)
    return {
        "items": list(source_map.values()),
        "total": len(source_map),
        "debug": groups.get("debug", {}),
    }


@console_route("get", "/explore/sources/{source_id}/groups")
async def get_explore_groups(source_id: str):
    return await _plugin_scheduler.explore_groups(source_id)


@console_route("post", "/explore/sources/{source_id}/items")
async def explore_items(source_id: str, payload: dict):
    group_id = payload.get("groupId") or payload.get("kind")
    page = int(payload.get("page", 1) or 1)
    return await Catalog().explore(source_id=source_id, group_id=group_id, page=page)


# ---- Books ----

@console_route("get", "/books")
def list_books(limit: int = 100, offset: int = 0):
    import sqlite3
    from app.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT book_id, name, author, last_chapter, last_seen_at FROM book_records ORDER BY last_seen_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return {
        "items": [
            {"bookId": r[0], "name": r[1], "author": r[2], "lastChapter": r[3], "lastSeenAt": r[4]}
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
    }


@console_route("get", "/books/{book_id}")
async def get_book(book_id: str):
    catalog = BookCatalog()
    detail = await catalog.book_detail(book_id)
    sources = catalog.get_book_sources(book_id)
    return {"bookId": book_id, "detail": detail, "sources": sources}


@console_route("get", "/books/{book_id}/toc")
async def get_book_toc(book_id: str):
    catalog = BookCatalog()
    return await catalog.toc(book_id)


@console_route("get", "/chapter/{chapter_id}")
async def get_chapter(chapter_id: str):
    catalog = BookCatalog()
    return await catalog.chapter(chapter_id)


@console_route("get", "/chapter/{chapter_id}/fallback")
async def get_chapter_fallback(chapter_id: str, source_ids: str = ""):
    catalog = BookCatalog()
    fallback_ids = [s.strip() for s in source_ids.split(",") if s.strip()]
    return await catalog.chapter_with_fallback(chapter_id, fallback_ids or None)


@console_route("get", "/books/{book_id}/chapters/{chapter_id}/navigation")
def get_chapter_navigation(book_id: str, chapter_id: str):
    catalog = BookCatalog()
    return catalog.get_chapter_navigation(book_id, chapter_id)


# ---- Update Tasks ----

_scheduler = UpdateScheduler()


@console_route("get", "/update-tasks")
def list_update_tasks(limit: int = 100, offset: int = 0):
    return {"items": _scheduler.list_tasks(limit=limit, offset=offset)}


@console_route("post", "/update-tasks/{book_id}/enable")
def enable_update_task(book_id: str):
    return _scheduler.enable_tracking(book_id)


@console_route("post", "/update-tasks/{book_id}/disable")
def disable_update_task(book_id: str):
    return _scheduler.disable_tracking(book_id)


@console_route("post", "/update-tasks/{book_id}/run")
async def run_update_task(book_id: str):
    return await _scheduler.run_check(book_id)


# ---- Cache ----

@console_route("get", "/cache")
def get_cache():
    import sqlite3
    from app.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        search_count = conn.execute("SELECT COUNT(*) FROM book_search_cache").fetchone()[0]
        book_count = conn.execute("SELECT COUNT(*) FROM book_cache").fetchone()[0]
        toc_count = conn.execute("SELECT COUNT(*) FROM toc_cache").fetchone()[0]
        chapter_count = conn.execute("SELECT COUNT(*) FROM chapter_cache").fetchone()[0]
    return {
        "searchCache": search_count,
        "bookCache": book_count,
        "tocCache": toc_count,
        "chapterCache": chapter_count,
    }


def _json_payload(value: str | None) -> dict:
    if not value:
        return {}
    try:
        payload = json.loads(value)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


@console_route("get", "/cache/items")
def list_cache_items(limit: int = 50):
    import sqlite3
    from app.config import DB_PATH

    limit = max(1, min(int(limit or 50), 200))
    with sqlite3.connect(DB_PATH) as conn:
        search_rows = conn.execute(
            """
            SELECT match_mode, normalized_name, source_id, source_name,
                   raw_book_url, score, first_seen_at, last_seen_at, expires_at
            FROM book_search_cache
            ORDER BY last_seen_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        book_rows = conn.execute(
            """
            SELECT book_id, source_id, book_url, response_json, created_at
            FROM book_cache
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        toc_rows = conn.execute(
            """
            SELECT book_id, response_json, created_at
            FROM toc_cache
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        chapter_rows = conn.execute(
            """
            SELECT chapter_id, source_id, chapter_url, response_json, created_at
            FROM chapter_cache
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    searches = []
    for (match_mode, norm_name, source_id, source_name,
         raw_book_url, score, first_seen, last_seen, expires_at) in search_rows:
        searches.append({
            "matchMode": match_mode,
            "normalizedName": norm_name,
            "sourceId": source_id,
            "sourceName": source_name,
            "rawBookUrl": raw_book_url,
            "score": score,
            "firstSeenAt": first_seen,
            "lastSeenAt": last_seen,
            "expiresAt": expires_at,
        })

    books = []
    for book_id, source_id, book_url, response_json, created_at in book_rows:
        payload = _json_payload(response_json)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        books.append({
            "bookId": book_id,
            "sourceId": source_id,
            "bookUrl": book_url,
            "name": data.get("name", ""),
            "author": data.get("author", ""),
            "lastChapter": data.get("lastChapter", ""),
            "createdAt": created_at,
        })

    tocs = []
    for book_id, response_json, created_at in toc_rows:
        payload = _json_payload(response_json)
        chapters = payload.get("chapters") if isinstance(payload.get("chapters"), list) else []
        first = chapters[0] if chapters else {}
        last = chapters[-1] if chapters else {}
        tocs.append({
            "bookId": book_id,
            "chapterCount": len(chapters),
            "firstTitle": first.get("title", "") if isinstance(first, dict) else "",
            "lastTitle": last.get("title", "") if isinstance(last, dict) else "",
            "createdAt": created_at,
        })

    chapters = []
    for chapter_id, source_id, chapter_url, response_json, created_at in chapter_rows:
        payload = _json_payload(response_json)
        content = payload.get("content", "")
        chapters.append({
            "chapterId": chapter_id,
            "sourceId": source_id,
            "chapterUrl": chapter_url,
            "title": payload.get("title", ""),
            "contentLength": len(content) if isinstance(content, str) else 0,
            "createdAt": created_at,
        })

    return {
        "searches": searches,
        "books": books,
        "tocs": tocs,
        "chapters": chapters,
        "limit": limit,
    }


@console_route("delete", "/cache")
def clear_cache():
    import sqlite3
    from app.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM book_search_cache")
        conn.execute("DELETE FROM book_cache")
        conn.execute("DELETE FROM toc_cache")
        conn.execute("DELETE FROM chapter_cache")
        conn.commit()
    return {"cleared": True}


@console_route("post", "/cache/clear")
def clear_cache_post(payload: dict):
    cache_type = payload.get("type", "all")
    import sqlite3
    from app.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        if cache_type in ("all", "search"):
            conn.execute("DELETE FROM book_search_cache")
        if cache_type in ("all", "book"):
            conn.execute("DELETE FROM book_cache")
        if cache_type in ("all", "toc"):
            conn.execute("DELETE FROM toc_cache")
        if cache_type in ("all", "chapter"):
            conn.execute("DELETE FROM chapter_cache")
        conn.commit()
    return {"cleared": True, "type": cache_type}


def _source_pool_from_config(cfg: AppConfig) -> dict:
    return {
        "proxy": {
            "enabled": cfg.proxy.enabled,
            "url": cfg.proxy.url,
            "allowAutoRetry": cfg.proxy.allow_auto_retry,
        },
        "max_concurrency": cfg.search.global_source_concurrency,
        "source_batch_size": 20,
        "source_timeout_seconds": cfg.search.source_timeout_seconds,
        "overall_search_timeout_seconds": cfg.search.overall_timeout_seconds,
        "browser_source_timeout_seconds": cfg.search.browser_source_timeout_seconds,
        "browser_search_timeout_seconds": cfg.search.browser_search_timeout_seconds,
        "default_user_agent": cfg.search.default_user_agent,
        "officialSourceInNormalSearch": cfg.search.official_source_in_normal_search,
    }


def _apply_source_pool_to_config(cfg: AppConfig, sp: dict) -> None:
    proxy = sp.get("proxy") or {}
    cfg.set("proxy.enabled", bool(proxy.get("enabled", cfg.proxy.enabled)))
    cfg.set("proxy.url", str(proxy.get("url", cfg.proxy.url)))
    cfg.set(
        "proxy.allowAutoRetry",
        bool(proxy.get("allowAutoRetry", cfg.proxy.allow_auto_retry)),
    )
    cfg.set("search.globalSourceConcurrency", int(sp.get("max_concurrency", cfg.search.global_source_concurrency)))
    cfg.set("search.sourceTimeoutSeconds", float(sp.get("source_timeout_seconds", cfg.search.source_timeout_seconds)))
    cfg.set("search.overallTimeoutSeconds", float(sp.get("overall_search_timeout_seconds", cfg.search.overall_timeout_seconds)))
    cfg.set("search.browserSourceTimeoutSeconds", float(sp.get("browser_source_timeout_seconds", cfg.search.browser_source_timeout_seconds)))
    cfg.set("search.browserSearchTimeoutSeconds", float(sp.get("browser_search_timeout_seconds", cfg.search.browser_search_timeout_seconds)))
    cfg.set("search.defaultUserAgent", str(sp.get("default_user_agent", cfg.search.default_user_agent)))
    cfg.set("search.officialSourceInNormalSearch", bool(sp.get("officialSourceInNormalSearch", cfg.search.official_source_in_normal_search)))


# ---- Settings ----

@console_route("get", "/settings")
def get_settings():
    cfg = AppConfig.get()
    settings = {
        "sourcePool": _source_pool_from_config(cfg),
        "searchScoreFilter": cfg.search.score_filter,
        "searchConfig": {
            "overallTimeoutSeconds": cfg.search.overall_timeout_seconds,
            "firstResultTimeoutSeconds": cfg.search.first_result_timeout_seconds,
            "sourceTimeoutSeconds": cfg.search.source_timeout_seconds,
            "cacheTtlSeconds": cfg.search.cache_ttl_seconds,
        },
        "contentWorkflow": cfg.aggregate.content_workflow,
        "legacy": {
            "ruleEngines": _legacy_archived("rule_engines"),
            "sourceSubscriptions": _legacy_archived("source_subscriptions"),
        },
    }
    return settings


@console_route("post", "/settings")
def update_settings(payload: dict):
    cfg = AppConfig.get()
    if "sourcePool" in payload and isinstance(payload["sourcePool"], dict):
        _apply_source_pool_to_config(cfg, payload["sourcePool"])
    if "searchScoreFilter" in payload:
        try:
            score = int(payload["searchScoreFilter"])
            if score >= 0:
                cfg.set("search.scoreFilter", score)
        except (TypeError, ValueError):
            pass
    if "contentWorkflow" in payload and isinstance(payload["contentWorkflow"], dict):
        cfg.set("aggregate.contentWorkflow", payload["contentWorkflow"])
    cfg.save()
    _plugin_scheduler.refresh_config()
    _search_service.scheduler.refresh_config()
    return {"saved": True}


# ---- Aggregate Source ----

@console_route("get", "/aggregate-source")
def get_aggregate_source():
    config = load_aggregate_config()
    path = write_aggregate_source()
    config["generated_path"] = path
    return config


@console_route("post", "/aggregate-source/regenerate")
def regenerate_aggregate_source():
    path = write_aggregate_source()
    config = load_aggregate_config()
    config["last_generated_at"] = _now()
    save_aggregate_config(config)
    return {"path": path, "config": config}


# ---- Aggregate Settings ----

@console_route("get", "/aggregate-settings")
def get_aggregate_settings():
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    return AggregateSettingsRepository(DB_PATH).get_settings()


@console_route("post", "/aggregate-settings")
def update_aggregate_settings(payload: dict):
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    settings = AggregateSettingsRepository(DB_PATH).save_settings(payload)
    return {"saved": True, **settings}


@console_route("post", "/aggregate-settings/test-provider")
async def test_aggregate_provider(payload: dict):
    from app.ai.client import OpenAICompatibleClient

    config = payload.get("aiProviderConfig") if isinstance(payload.get("aiProviderConfig"), dict) else payload
    if not config or not config.get("baseUrl") or not config.get("apiKey"):
        return {"ok": False, "status": "not_configured", "message": "baseUrl and apiKey are required"}

    client = OpenAICompatibleClient(config)
    return await client.test_connectivity()


@console_route("post", "/aggregate-settings/fetch-models")
async def fetch_aggregate_models(payload: dict):
    from app.ai.client import OpenAICompatibleClient

    config = payload.get("aiProviderConfig") if isinstance(payload.get("aiProviderConfig"), dict) else payload
    if not config or not config.get("baseUrl") or not config.get("apiKey"):
        return {"ok": False, "status": "not_configured", "models": [], "message": "baseUrl and apiKey are required"}

    client = OpenAICompatibleClient(config)
    try:
        models = await client.list_models()
        return {"ok": True, "models": models, "count": len(models)}
    except Exception as exc:
        return {"ok": False, "models": [], "status": "error", "message": str(exc)}


# ---- Aggregate Books ----

def _bounded_page(value: int | str | None, default: int, maximum: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return min(max(parsed, 1), maximum)


def _serialize_aggregate_book_row(row: tuple) -> dict:
    total_chapters = int(row[6] or 0)
    processed_chapters = int(row[7] or 0)
    visible_processed_chapters = int(row[8] or 0)
    settings = _aggregate_book_settings(row[21] or "")
    return {
        "id": row[0],
        "bookId": row[0],
        "aggregateBookId": row[0],
        "name": row[1] or "",
        "author": row[2] or "",
        "status": row[3] or "active",
        "bookStatus": row[4] or "unknown",
        "primarySourceId": row[5] or "",
        "totalChapters": total_chapters,
        "processedChapters": processed_chapters,
        "visibleProcessedChapters": visible_processed_chapters,
        "failedChapters": int(row[9] or 0),
        "progress": processed_chapters / total_chapters if total_chapters else 0,
        "totalTokens": int(row[10] or 0),
        "lastProcessedAt": row[11] or "",
        "nextCheckTime": row[12] or "",
        "lastError": row[13] or "",
        "addedByUserId": row[14] or "",
        "addedByUsername": library_books_service.username_for_user_id(row[14] or ""),
        "coverUrl": row[15] or "",
        "intro": row[16] or "",
        "wordCount": row[17] or "",
        "searchVisibilityStatus": row[18] or "hidden",
        "startChapterIndex": int(row[19] or 1),
        "autoArchiveOnComplete": bool(row[20]),
        "settings": settings,
        "currentPolicyVersion": int(row[22] or 1),
    }


def _fetch_aggregate_book_row(conn: sqlite3.Connection, book_id: str):
    return conn.execute(
        """
        SELECT aggregate_book_id, name, author, status, book_status, primary_source_id,
               total_chapters, processed_chapters, visible_processed_chapters, failed_chapters, total_tokens,
               last_processed_at, next_check_time, last_error, added_by_user_id, cover_url, intro,
               word_count, search_visibility_status, start_chapter_index, auto_archive_on_complete,
               settings_json, current_policy_version
        FROM aggregate_book_tasks
        WHERE aggregate_book_id = ?
        """,
        (book_id,),
    ).fetchone()


def _delete_aggregate_book_impl(book_id: str, *, actor_user_id: str = "", actor_role: str = "admin") -> dict:
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    base_dir = Path(DB_PATH).parent / "novels" / "legadohub_ai_aggregate" / book_id
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO aggregate_operation_logs
            (aggregate_book_id, actor_user_id, actor_role, operation_type, before_json, after_json, created_at)
            VALUES (?, ?, ?, 'delete', '', '', ?)
            """,
            (book_id, actor_user_id, actor_role, _now()),
        )
        conn.execute("DELETE FROM aggregate_source_snapshots WHERE aggregate_book_id = ?", (book_id,))
        conn.execute("DELETE FROM aggregate_book_sources WHERE aggregate_book_id = ?", (book_id,))
        conn.execute("DELETE FROM aggregate_chapter_tasks WHERE aggregate_book_id = ?", (book_id,))
        cursor = conn.execute("DELETE FROM aggregate_book_tasks WHERE aggregate_book_id = ?", (book_id,))
        conn.commit()
    if base_dir.exists():
        shutil.rmtree(base_dir, ignore_errors=True)
    return {"bookId": book_id, "deleted": cursor.rowcount > 0}


@console_route("get", "/aggregate-books")
def list_aggregate_books(request: Request, page: int = 1, pageSize: int = 20, status: str = "all", keyword: str = "", sort: str = "updated_desc"):
    auth_service.require_admin(request)
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    page = _bounded_page(page, 1, 1000000)
    page_size = _bounded_page(pageSize, 20, 100)
    where = []
    params: list = []
    if status and status != "all":
        where.append("status = ?")
        params.append(status)
    if keyword:
        where.append("(name LIKE ? OR author LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sort_sql = {
        "created_desc": "created_at DESC",
        "progress_desc": "processed_chapters DESC",
        "tokens_desc": "total_tokens DESC",
    }.get(sort, "updated_at DESC")
    offset = (page - 1) * page_size
    with sqlite3.connect(DB_PATH) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM aggregate_book_tasks {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT aggregate_book_id, name, author, status, book_status, primary_source_id,
                   total_chapters, processed_chapters, visible_processed_chapters, failed_chapters, total_tokens,
                   last_processed_at, next_check_time, last_error, added_by_user_id, cover_url, intro,
                   word_count, search_visibility_status, start_chapter_index, auto_archive_on_complete,
                   settings_json, current_policy_version
            FROM aggregate_book_tasks
            {where_sql}
            ORDER BY {sort_sql}
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
    items = [_serialize_aggregate_book_row(row) for row in rows]
    return {"items": items, "page": page, "pageSize": page_size, "total": total}


@console_route("get", "/aggregate-books/{book_id}")
def get_aggregate_book(request: Request, book_id: str):
    auth_service.require_admin(request)
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        row = _fetch_aggregate_book_row(conn, book_id)
    if not row:
        return {"bookId": book_id, "found": False}
    data = _serialize_aggregate_book_row(row)
    data["found"] = True
    return data


@console_route("post", "/aggregate-books/{book_id}/run")
async def run_aggregate_book(request: Request, book_id: str):
    auth_service.require_admin(request)
    from app.services.aggregate_processor import AggregateProcessor

    return await AggregateProcessor().run_book_task(book_id)


@console_route("post", "/aggregate-books/{book_id}/pause")
def pause_aggregate_book(request: Request, book_id: str):
    auth_service.require_admin(request)
    return _update_aggregate_book_status(book_id, "paused")


@console_route("post", "/aggregate-books/{book_id}/resume")
def resume_aggregate_book(request: Request, book_id: str):
    auth_service.require_admin(request)
    return _update_aggregate_book_status(book_id, "active")


def _update_aggregate_book_status(book_id: str, status: str, *, actor_user_id: str = "", actor_role: str = "admin"):
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO aggregate_operation_logs
            (aggregate_book_id, actor_user_id, actor_role, operation_type, before_json, after_json, created_at)
            VALUES (?, ?, ?, ?, '', ?, ?)
            """,
            (
                book_id,
                actor_user_id,
                actor_role,
                f"set_status:{status}",
                json.dumps({"status": status}, ensure_ascii=False),
                _now(),
            ),
        )
        cursor = conn.execute(
            """
            UPDATE aggregate_book_tasks
            SET status = ?,
                archived_at = CASE
                        WHEN ? = 'archived' THEN COALESCE(archived_at, datetime('now'))
                    WHEN ? = 'active' THEN NULL
                    WHEN ? != 'archived' THEN archived_at
                    ELSE archived_at
                END,
                updated_at = datetime('now')
            WHERE aggregate_book_id = ?
            """,
            (status, status, status, status, book_id),
        )
        conn.commit()
    return {"bookId": book_id, "status": status, "updated": cursor.rowcount > 0}


@console_route("delete", "/aggregate-books/{book_id}")
def delete_aggregate_book(request: Request, book_id: str):
    auth_service.require_admin(request)
    return _delete_aggregate_book_impl(book_id)


@console_route("get", "/aggregate-books/{book_id}/chapters")
def list_aggregate_chapters(request: Request, book_id: str, page: int = 1, pageSize: int = 50, status: str = "all", keyword: str = ""):
    auth_service.require_admin(request)
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    page = _bounded_page(page, 1, 1000000)
    page_size = _bounded_page(pageSize, 50, 200)
    where = ["aggregate_book_id = ?"]
    params: list = [book_id]
    if status and status != "all":
        where.append("status = ?")
        params.append(status)
    if keyword:
        where.append("title LIKE ?")
        params.append(f"%{keyword}%")
    where_sql = "WHERE " + " AND ".join(where)
    offset = (page - 1) * page_size
    with sqlite3.connect(DB_PATH) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM aggregate_chapter_tasks {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT chapter_id, chapter_index, title, status, content_length, ai_model,
                   ai_total_tokens, deviation_score, ai_self_score, fallback_source_id, retry_count,
                   last_processed_at, error
            FROM aggregate_chapter_tasks
            {where_sql}
            ORDER BY COALESCE(chapter_index, 999999), created_at
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ).fetchall()
    items = [
        {
            "chapterId": row[0],
            "chapterIndex": row[1] or 0,
            "title": row[2] or "",
            "status": row[3] or "pending",
            "contentLength": int(row[4] or 0),
            "aiModel": row[5] or "",
            "aiTotalTokens": int(row[6] or 0),
            "deviationScore": float(row[7] or 0.0),
            "aiSelfScore": float(row[8] or 0.0),
            "fallbackSourceId": row[9] or "",
            "retryCount": int(row[10] or 0),
            "lastProcessedAt": row[11] or "",
            "error": row[12] or "",
        }
        for row in rows
    ]
    return {"items": items, "page": page, "pageSize": page_size, "total": total}


@console_route("get", "/aggregate-books/{book_id}/chapters/{chapter_id}")
def get_aggregate_chapter(request: Request, book_id: str, chapter_id: str):
    auth_service.require_admin(request)
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT act.chapter_id, act.chapter_index, act.title, act.status, act.processed_content, abt.primary_source_id,
                   act.fallback_source_id, act.source_alignment_json, act.ai_model, act.ai_prompt_tokens,
                   act.ai_completion_tokens, act.ai_total_tokens, act.ai_latency_ms, act.deviation_score,
                   act.ai_self_score, act.error
            FROM aggregate_chapter_tasks act
            LEFT JOIN aggregate_book_tasks abt ON act.aggregate_book_id = abt.aggregate_book_id
            WHERE act.aggregate_book_id = ? AND act.chapter_id = ?
            """,
            (book_id, chapter_id),
        ).fetchone()
    if not row:
        return {"chapterId": chapter_id, "bookId": book_id, "found": False}
    try:
        alignment = json.loads(row[7] or "{}")
    except Exception:
        alignment = {}
    content = row[4] or ""
    ai_enabled = bool(row[8])
    ai_model = row[8] or ""
    ai_prompt = int(row[9] or 0)
    ai_completion = int(row[10] or 0)
    ai_total = int(row[11] or 0)
    ai_latency = int(row[12] or 0)
    deviation = float(row[13] or 0.0)
    ai_self_score = float(row[14] or 0.0)
    fallback_source_id = row[6] or ""
    error = row[15] or ""
    return {
        "chapterId": row[0],
        "chapterIndex": row[1] or 0,
        "title": row[2] or "",
        "status": row[3] or "pending",
        "content": content,
        "contentLength": len(content),
        "contentPreview": content[:500],
        "source": {
            "primarySourceId": row[5] or "",
            "fallbackSourceId": fallback_source_id,
            "alignment": alignment,
        },
        "sourceAlignment": alignment,
        "fallbackInfo": {
            "fallbackSourceId": fallback_source_id,
            "error": error,
        },
        "ai": {
            "enabled": ai_enabled,
            "model": ai_model,
            "promptTokens": ai_prompt,
            "completionTokens": ai_completion,
            "totalTokens": ai_total,
            "latencyMs": ai_latency,
            "deviationScore": deviation,
            "aiSelfScore": ai_self_score,
        },
        "aiInfo": {
            "enabled": ai_enabled,
            "model": ai_model,
            "promptTokens": ai_prompt,
            "completionTokens": ai_completion,
            "totalTokens": ai_total,
            "latencyMs": ai_latency,
            "deviationScore": deviation,
            "aiSelfScore": ai_self_score,
        },
        "aiModel": ai_model,
        "tokens": ai_total,
        "deviationScore": deviation,
        "aiSelfScore": ai_self_score,
        "fallbackSourceId": fallback_source_id,
        "errorMessage": error,
        "error": error,
    }


@console_route("post", "/aggregate-books/{book_id}/chapters/{chapter_id}/retry")
def retry_aggregate_chapter(request: Request, book_id: str, chapter_id: str):
    auth_service.require_admin(request)
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            UPDATE aggregate_chapter_tasks
            SET status = 'pending', error = '', next_retry_time = NULL, updated_at = datetime('now')
            WHERE aggregate_book_id = ? AND chapter_id = ?
            """,
            (book_id, chapter_id),
        )
        conn.commit()
    return {"bookId": book_id, "chapterId": chapter_id, "queued": cursor.rowcount > 0}


@console_route("get", "/aggregate-books/{book_id}/chapters/{chapter_id}/reviews")
async def get_aggregate_chapter_reviews(request: Request, book_id: str, chapter_id: str):
    auth_service.require_admin(request)
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database
    from app.services.aggregate_reviews import (
        empty_aggregate_reviews, summarize_reviews, hot_review_bubble_label,
    )

    initialize_database(DB_PATH)
    mapped_chapter_id = ""
    mapped_source_id = ""
    reason = "not_mapped"
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT act.source_chapter_id, abt.primary_source_id
            FROM aggregate_chapter_tasks act
            LEFT JOIN aggregate_book_tasks abt ON act.aggregate_book_id = abt.aggregate_book_id
            WHERE act.aggregate_book_id = ? AND act.chapter_id = ?
            """,
            (book_id, chapter_id),
        ).fetchone()
    if row:
        mapped_chapter_id = row[0] or ""
        mapped_source_id = row[1] or ""
        reason = "primary_source" if mapped_chapter_id else "not_mapped"

    if not mapped_chapter_id or not mapped_source_id:
        return empty_aggregate_reviews(
            chapter_id=chapter_id,
            mapped_chapter_id=mapped_chapter_id,
            mapped_source_id=mapped_source_id,
            mapping_reason=reason,
        )

    # Try to fetch real reviews from the source plugin.
    try:
        from app.source_plugins.id_codec import decode_chapter_id
        _, chapter_url = decode_chapter_id(mapped_chapter_id)
        if not chapter_url:
            raise ValueError("could not decode chapter URL")

        has_capability = False
        plugin = _plugin_scheduler._plugins.get(mapped_source_id)
        if plugin:
            caps = plugin.capabilities if isinstance(plugin.capabilities, (list, set)) else []
            has_capability = "chapter_reviews" in caps

        if not has_capability:
            return empty_aggregate_reviews(
                chapter_id=chapter_id,
                mapped_chapter_id=mapped_chapter_id,
                mapped_source_id=mapped_source_id,
                mapping_reason="source_no_review_capability",
            )

        raw_reviews = await _plugin_scheduler.chapter_reviews(mapped_source_id, chapter_url)

        # Normalize into aggregate contract.
        paragraphs = raw_reviews.get("paragraphs") or {}
        chapter_end = raw_reviews.get("chapterEnd") or []
        chapter_end_hot = raw_reviews.get("chapterEndHot") or []
        author_reviews = raw_reviews.get("authorReviews") or []

        # Add hot_review_bubble_label to hot reviews.
        for i, review in enumerate(chapter_end_hot):
            if isinstance(review, dict) and "bubbleLabel" not in review:
                review["bubbleLabel"] = hot_review_bubble_label(i + 1)

        payload = {
            "chapterId": chapter_id,
            "mappedChapterId": mapped_chapter_id,
            "mappedSourceId": mapped_source_id,
            "mappingReason": reason,
            "chapterEndHot": chapter_end_hot,
            "chapterEnd": chapter_end,
            "authorReviews": author_reviews,
            "hotParagraphReviews": raw_reviews.get("hotParagraphReviews") or [],
            "paragraphs": paragraphs,
            "summary": {},
            "debug": raw_reviews.get("debug") or {"aggregate": True, "reviewSource": reason},
        }
        payload["summary"] = summarize_reviews(payload)
        return payload

    except Exception as exc:
        result = empty_aggregate_reviews(
            chapter_id=chapter_id,
            mapped_chapter_id=mapped_chapter_id,
            mapped_source_id=mapped_source_id,
            mapping_reason=f"fetch_error: {exc}",
        )
        result["debug"]["error"] = str(exc)
        return result


# ---- Shared Library / Users ----

@console_route("get", "/library-books")
def list_library_books(request: Request, keyword: str = ""):
    auth_service.require_admin(request)
    items = library_books_service.list_books(keyword=keyword, include_hidden=True)
    return {"items": items, "total": len(items)}


@console_route("get", "/library-books/{book_id}/summary")
def get_library_book_summary(request: Request, book_id: str):
    user = auth_service.require_user(request)
    if _shared_book_storage_read_mode() == "legacy":
        payload = _load_legacy_library_book_summary(book_id)
        payload["mode"] = "legacy"
        return payload
    payload = _load_shared_library_book_summary(book_id, admin_view=_is_admin_role(user))
    payload["mode"] = "shared"
    return payload


@console_route("get", "/library-books/{book_id}")
def get_library_book_admin(request: Request, book_id: str):
    auth_service.require_admin(request)
    if _shared_book_storage_read_mode() == "legacy":
        payload = _load_legacy_library_book_summary(book_id)
        payload["mode"] = "legacy"
        return payload
    payload = _load_shared_library_book_summary(book_id, admin_view=True)
    payload["mode"] = "shared"
    return payload


@console_route("get", "/library-books/{book_id}/chapters")
def list_library_book_chapters_admin(
    request: Request,
    book_id: str,
    page: int = 1,
    pageSize: int = 50,
    status: str = "all",
    keyword: str = "",
):
    user = auth_service.require_user(request)
    if _shared_book_storage_read_mode() == "legacy":
        payload = _list_legacy_library_book_chapters(
            book_id,
            page=page,
            pageSize=pageSize,
            status=status,
            keyword=keyword,
        )
        payload["mode"] = "legacy"
        return payload
    payload = _list_shared_library_book_chapters(
        book_id,
        page=page,
        pageSize=pageSize,
        status=status,
        keyword=keyword,
    )
    payload["mode"] = "shared"
    payload["adminView"] = _is_admin_role(user)
    return payload


@console_route("get", "/library-books/{book_id}/logs")
def list_library_book_logs(request: Request, book_id: str, limit: int = 50, offset: int = 0):
    user = auth_service.require_user(request)
    return _list_library_book_logs(book_id, limit=limit, offset=offset, admin_view=_is_admin_role(user))


@console_route("get", "/library-books/{book_id}/chapters/{chapter_id}/progress")
def get_library_book_chapter_progress(request: Request, book_id: str, chapter_id: str):
    auth_service.require_user(request)
    payload = _load_library_book_chapter_progress(book_id, chapter_id)
    if payload.get("found", True) and isinstance(payload.get("traceSummary"), dict):
        payload["traceSummary"] = _sanitize_trace_summary(payload["traceSummary"])
    return payload


@console_route("post", "/library-books/{book_id}/pause")
def pause_library_book(request: Request, book_id: str):
    auth_service.require_admin(request)
    return _update_aggregate_book_status(book_id, "paused")


@console_route("post", "/library-books/{book_id}/resume")
def resume_library_book(request: Request, book_id: str):
    auth_service.require_admin(request)
    return _update_aggregate_book_status(book_id, "active")


@console_route("post", "/library-books/{book_id}/archive")
def archive_library_book(request: Request, book_id: str):
    auth_service.require_admin(request)
    return _update_aggregate_book_status(book_id, "archived")


@console_route("delete", "/library-books/{book_id}")
def delete_library_book(request: Request, book_id: str):
    auth_service.require_admin(request)
    return delete_aggregate_book(request, book_id)


@console_route("post", "/library-books/{book_id}/settings")
def update_library_book_settings(request: Request, book_id: str, payload: dict):
    admin = auth_service.require_admin(request)
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    now = _now()
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT settings_json, current_policy_version, interval_minutes, auto_archive_on_complete
            FROM aggregate_book_tasks
            WHERE aggregate_book_id = ?
            """,
            (book_id,),
        ).fetchone()
        if not row:
            return {"error": "书籍不存在", "bookId": book_id}

        settings = _aggregate_book_settings(row[0] or "")
        current_policy_version = int(row[1] or 1)
        interval_minutes = int(row[2] or settings.get("updateIntervalMinutes", 60) or 60)
        auto_archive = bool(row[3])
        policy_changed = False

        if "autoTrackUpdates" in payload:
            settings["autoTrackUpdates"] = bool(payload["autoTrackUpdates"])
            policy_changed = True
        if "updateIntervalMinutes" in payload:
            settings["updateIntervalMinutes"] = max(10, int(payload["updateIntervalMinutes"] or 60))
            interval_minutes = settings["updateIntervalMinutes"]
        if "aiAggregateEnabled" in payload:
            settings["aiAggregateEnabled"] = bool(payload["aiAggregateEnabled"])
            policy_changed = True
        if "aiPurifyEnabled" in payload:
            settings["aiPurifyEnabled"] = bool(payload["aiPurifyEnabled"])
            policy_changed = True
        if "primarySourceMode" in payload:
            settings["primarySourceMode"] = str(payload["primarySourceMode"] or "official")
            policy_changed = True
        if "sourcePriorityMode" in payload:
            settings["sourcePriorityMode"] = str(payload["sourcePriorityMode"] or "auto")
            policy_changed = True
        if "sourcePriority" in payload and isinstance(payload["sourcePriority"], list):
            settings["sourcePriority"] = [str(x) for x in payload["sourcePriority"]]
            policy_changed = True
        if "autoArchiveOnComplete" in payload:
            auto_archive = bool(payload["autoArchiveOnComplete"])

        next_policy_version = current_policy_version + 1 if policy_changed else current_policy_version
        conn.execute(
            """
            UPDATE aggregate_book_tasks
            SET settings_json = ?, interval_minutes = ?, auto_archive_on_complete = ?,
                current_policy_version = ?, updated_at = ?
            WHERE aggregate_book_id = ?
            """,
            (
                json.dumps(settings, ensure_ascii=False),
                interval_minutes,
                1 if auto_archive else 0,
                next_policy_version,
                now,
                book_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO aggregate_operation_logs
            (aggregate_book_id, actor_user_id, actor_role, operation_type, before_json, after_json, created_at)
            VALUES (?, ?, 'admin', 'update_settings', '', ?, ?)
            """,
            (book_id, admin.user_id, json.dumps(payload, ensure_ascii=False), now),
        )
        conn.commit()

    return {
        "bookId": book_id,
        "updated": True,
        "policyChanged": policy_changed,
        "currentPolicyVersion": next_policy_version,
    }


@console_route("post", "/library-books/{book_id}/rebuild")
async def rebuild_library_book(request: Request, book_id: str, payload: dict | None = None):
    admin = auth_service.require_admin(request)
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    payload = payload or {}
    now = _now()
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT aggregate_payload_json, settings_json, current_policy_version, start_chapter_index
            FROM aggregate_book_tasks
            WHERE aggregate_book_id = ?
            """,
            (book_id,),
        ).fetchone()
        if not row:
            return {"error": "书籍不存在", "bookId": book_id}

        aggregate_payload_json, settings_json, current_policy_version, current_start_index = row
        settings = _aggregate_book_settings(settings_json or "")
        new_start_index = max(1, int(payload.get("startChapterIndex", current_start_index or 1) or 1))
        new_auto_archive = bool(payload.get("autoArchiveOnComplete", settings.get("autoArchiveOnComplete", True)))
        settings["startChapterIndex"] = new_start_index
        settings["autoArchiveOnComplete"] = new_auto_archive
        if "aiAggregateEnabled" in payload:
            settings["aiAggregateEnabled"] = bool(payload["aiAggregateEnabled"])
        if "aiPurifyEnabled" in payload:
            settings["aiPurifyEnabled"] = bool(payload["aiPurifyEnabled"])
        if "primarySourceMode" in payload:
            settings["primarySourceMode"] = str(payload["primarySourceMode"] or "official")
        if "sourcePriorityMode" in payload:
            settings["sourcePriorityMode"] = str(payload["sourcePriorityMode"] or "auto")
        if "sourcePriority" in payload and isinstance(payload["sourcePriority"], list):
            settings["sourcePriority"] = [str(x) for x in payload["sourcePriority"]]

        conn.execute("DELETE FROM aggregate_chapter_tasks WHERE aggregate_book_id = ?", (book_id,))
        conn.execute(
            """
            UPDATE aggregate_book_tasks
            SET start_chapter_index = ?, initial_snapshot_last_index = 0, backfill_started = 0,
                total_chapters = 0, processed_chapters = 0, visible_processed_chapters = 0, failed_chapters = 0,
                search_visibility_status = 'hidden', status = 'active', archived_at = NULL,
                settings_json = ?, current_policy_version = ?, auto_archive_on_complete = ?,
                last_processed_at = NULL, updated_at = ?
            WHERE aggregate_book_id = ?
            """,
            (
                new_start_index,
                json.dumps(settings, ensure_ascii=False),
                int(current_policy_version or 1) + 1,
                1 if new_auto_archive else 0,
                now,
                book_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO aggregate_operation_logs
            (aggregate_book_id, actor_user_id, actor_role, operation_type, before_json, after_json, created_at)
            VALUES (?, ?, 'admin', 'rebuild', '', ?, ?)
            """,
            (book_id, admin.user_id, json.dumps(payload, ensure_ascii=False), now),
        )
        conn.commit()

    library_root = Path(DB_PATH).parent / "novels" / "legadohub_ai_aggregate" / book_id
    if library_root.exists():
        shutil.rmtree(library_root, ignore_errors=True)

    aggregate_payload = json.loads(aggregate_payload_json or "{}")
    processor = AggregateProcessor()
    processor.enqueue_book(book_id, aggregate_payload)
    bootstrap = await processor.bootstrap_book_until_visible(book_id)
    return {"bookId": book_id, "rebuilt": True, "bootstrap": bootstrap}


@console_route("post", "/library-books/{book_id}/source-map/refresh")
async def refresh_library_book_source_map_console(request: Request, book_id: str, payload: dict | None = None):
    auth_service.require_admin(request)
    result = _manual_source_map_refresh(book_id, payload=payload)
    if asyncio.iscoroutine(result):
        result = await result
    return result


@console_route("post", "/library-books/{book_id}/repair")
async def repair_library_book_console(request: Request, book_id: str, payload: dict | None = None):
    auth_service.require_admin(request)
    result = _manual_library_book_repair(book_id, payload=payload)
    if asyncio.iscoroutine(result):
        result = await result
    return result


@console_route("post", "/library-books/{book_id}/update-check")
async def run_library_book_update_check_console(request: Request, book_id: str):
    auth_service.require_admin(request)
    result = _manual_library_book_update_check(book_id)
    if asyncio.iscoroutine(result):
        result = await result
    return result


@console_route("get", "/library-books/{book_id}/processing-logs")
def list_library_book_processing_logs(
    request: Request,
    book_id: str,
    limit: int = 50,
    offset: int = 0,
):
    """Return recent chapter processing events for a shared book.

    This is the backend feed consumed by the console "subscription processing
    log" panel. It surfaces per-chapter status, selected source, AI usage and
    alignment metadata without leaking raw chapter text.
    """
    auth_service.require_admin(request)
    import sqlite3
    from app.config import DB_PATH
    from app.storage.db import initialize_database

    initialize_database(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        book = cur.execute(
            """
            SELECT status, search_visibility_status
            FROM aggregate_book_tasks
            WHERE aggregate_book_id = ?
            """,
            (book_id,),
        ).fetchone()
        if book is None:
            return {"error": "书籍不存在", "bookId": book_id}

        stats = cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'processed' THEN 1 ELSE 0 END) AS processed,
                SUM(CASE WHEN status IN ('processed', 'fallback') THEN 1 ELSE 0 END) AS completed,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status = 'fallback' THEN 1 ELSE 0 END) AS fallback,
                SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS failed
            FROM aggregate_chapter_tasks
            WHERE aggregate_book_id = ?
            """,
            (book_id,),
        ).fetchone()

        rows = cur.execute(
            """
            SELECT
                chapter_id,
                chapter_index,
                title,
                status,
                preview_only,
                content_length,
                source_word_count,
                primary_source_chapter_url,
                fallback_source_id,
                ai_model,
                (ai_prompt_tokens + ai_completion_tokens) AS ai_tokens,
                last_processed_at,
                updated_at,
                error,
                source_alignment_json
            FROM aggregate_chapter_tasks
            WHERE aggregate_book_id = ?
            ORDER BY
                last_processed_at DESC,
                updated_at DESC
            LIMIT ? OFFSET ?
            """,
            (book_id, limit, offset),
        ).fetchall()

        items = []
        for row in rows:
            alignment = {}
            try:
                alignment = json.loads(row["source_alignment_json"] or "{}")
            except Exception:
                pass

            source = row["fallback_source_id"] or "primary"
            if alignment.get("selectedSource"):
                source = alignment["selectedSource"]

            items.append(
                {
                    "chapterId": row["chapter_id"],
                    "chapterIndex": row["chapter_index"],
                    "title": row["title"],
                    "status": row["status"],
                    "previewOnly": bool(row["preview_only"]),
                    "wordCount": row["source_word_count"] or row["content_length"] or 0,
                    "source": source,
                    "aiModel": row["ai_model"] or "",
                    "aiTokens": row["ai_tokens"] or 0,
                    "processedAt": row["last_processed_at"] or row["updated_at"],
                    "error": row["error"] or "",
                    "alignment": {
                        "passed": alignment.get("alignmentPassed"),
                        "reason": alignment.get("alignmentReason"),
                        "titleSimilarity": alignment.get("titleSimilarity"),
                        "previewSimilarity": alignment.get("previewSimilarity"),
                    },
                }
            )

        return {
            "bookId": book_id,
            "bookStatus": book["status"],
            "searchVisibilityStatus": book["search_visibility_status"],
            "stats": {
                "total": stats["total"] or 0,
                "processed": stats["processed"] or 0,
                "completed": stats["completed"] or 0,
                "pending": stats["pending"] or 0,
                "fallback": stats["fallback"] or 0,
                "failed": stats["failed"] or 0,
            },
            "items": items,
            "limit": limit,
            "offset": offset,
        }


@console_route("get", "/users")
def list_users(request: Request):
    auth_service.require_admin(request)
    items = auth_service.list_users()
    return {"items": items, "total": len(items)}


@console_route("post", "/users")
def create_user(request: Request, payload: dict):
    auth_service.require_admin(request)
    return auth_service.create_user(
        username=str(payload.get("username", "")).strip(),
        password=str(payload.get("password", "")),
        role=str(payload.get("role", "user")),
    )


@console_route("post", "/users/{user_id}/reset-password")
def reset_user_password(request: Request, user_id: str, payload: dict):
    auth_service.require_admin(request)
    return auth_service.reset_password(user_id, str(payload.get("password", "")))


@console_route("post", "/users/{user_id}/disable")
def disable_user(request: Request, user_id: str, payload: dict | None = None):
    auth_service.require_admin(request)
    disabled = True if payload is None else bool(payload.get("disabled", True))
    return auth_service.set_disabled(user_id, disabled)


# ---- Progress ----

@console_route("get", "/progress")
def get_progress():
    from app.services.plugin_runtime_state import get_runtime_state

    runtime_state = get_runtime_state()
    plugin_count = len(_plugin_scheduler._plugins)
    enabled_plugin_count = sum(1 for p in _plugin_scheduler._plugins.values() if p.metadata.enabled)
    proxy_needed_count = sum(
        1 for p in _plugin_scheduler._plugins.values()
        if bool((p.metadata.proxy or {}).get("required"))
    )
    healthy_count = 0
    for p in _plugin_scheduler._plugins.values():
        state = runtime_state.get_state(p.metadata.id)
        last_ping = state.get("lastPing") or {}
        last_smoke = state.get("lastSmoke") or {}
        if last_ping.get("status") == "reachable" or last_smoke.get("pass") is True:
            healthy_count += 1
    plugin_stats = {
        "total": plugin_count,
        "enabled": enabled_plugin_count,
        "healthy": healthy_count,
        "disabled": plugin_count - enabled_plugin_count,
        "proxyNeeded": proxy_needed_count,
    }
    progress = {
        "pluginStats": plugin_stats,
        "configured_sources": plugin_count,
        "enabled_sources": enabled_plugin_count,
        "healthy_sources": healthy_count,
        "proxy_sources": proxy_needed_count,
        "unsupported_sources": 0,
        "plugin_count": plugin_count,
        "enabled_plugin_count": enabled_plugin_count,
    }
    update_progress(progress)
    config = load_aggregate_config()
    return {
        "aggregate": config.get("parser_progress", {}),
        "pluginStats": plugin_stats,
        "sources": plugin_stats,
        "plugins": {
            "total": plugin_count,
            "enabled": enabled_plugin_count,
            "healthy": healthy_count,
        },
    }


# ---- Subscriptions ----

@console_route("get", "/source-subscriptions")
def list_source_subscriptions():
    return {"subscriptions": [], **_legacy_archived("source_subscriptions")}


@console_route("post", "/source-subscriptions")
def add_source_subscription(payload: dict):
    return {"saved": False, **_legacy_archived("source_subscriptions")}


@console_route("post", "/source-subscriptions/sync-all")
async def sync_all_source_subscriptions(payload: dict | None = None):
    return {"synced": False, **_legacy_archived("source_subscriptions")}


@console_route("post", "/source-subscriptions/{subscription_id}")
def update_source_subscription(subscription_id: str, payload: dict):
    return {"saved": False, "subscriptionId": subscription_id, **_legacy_archived("source_subscriptions")}


@console_route("post", "/source-subscriptions/{subscription_id}/sync")
async def sync_source_subscription(subscription_id: str):
    return {"synced": False, "subscriptionId": subscription_id, **_legacy_archived("source_subscriptions")}


# ---- Rule Audit (legacy) ----

@console_route("get", "/rule-engines")
def list_rule_engines():
    # Return plugin capabilities instead of legacy engine report
    plugins = _plugin_scheduler._plugins
    return {
        "engines": [
            {
                "id": p.metadata.id,
                "name": p.metadata.name,
                "capabilities": p.capabilities,
                "contractVersion": p.metadata.contract_version,
            }
            for p in plugins.values()
        ]
    }


@console_route("get", "/rule-audit")
def audit_rules(limit: int = 200, offset: int = 0):
    return {"items": [], "limit": limit, "offset": offset, **_legacy_archived("rule_audit")}


@console_route("get", "/sources/{source_id}/rule-audit")
def audit_source_rule(source_id: str):
    return {"sourceId": source_id, **_legacy_archived("rule_audit")}


# ---- Verification ----

@console_route("get", "/verification")
def get_verification():
    from app.services.plugin_runtime_state import get_runtime_state

    runtime_state = get_runtime_state()
    items = []
    passed = 0
    failed = 0
    for plugin in _plugin_scheduler._plugins.values():
        state = runtime_state.get_state(plugin.metadata.id)
        last_smoke = state.get("lastSmoke") or {}
        last_error = state.get("lastError") or {}
        smoke_pass = last_smoke.get("pass")
        if smoke_pass is True:
            passed += 1
        elif smoke_pass is False:
            failed += 1
        items.append({
            "pluginId": plugin.metadata.id,
            "name": plugin.metadata.name,
            "hasFixtureSmoke": (_smoke_dir(_plugin_scheduler.loader.plugins_dir / plugin.metadata.id) / "smoke.yaml").exists(),
            "lastSmokePass": smoke_pass,
            "lastSmokeTimestamp": last_smoke.get("timestamp"),
            "lastError": last_error.get("message", ""),
            "lastErrorTimestamp": last_error.get("timestamp"),
            "authMode": (plugin.metadata.auth or {}).get("mode", "none"),
            "capabilities": plugin.capabilities,
            "lastModified": _plugin_last_modified(plugin),
        })
    return {
        "summary": {"passed": passed, "failed": failed, "total": len(items)},
        "items": items,
        "readingLoop": {
            "source": "/api/legado/source",
            "search": "/api/legado/search?keyword=凡人修仙传&page=1",
            "detail": "/api/legado/book/{book_id}",
            "toc": "/api/legado/book/{book_id}/toc",
            "chapter": "/api/legado/chapter/{chapter_id}",
        },
        "archived": False,
    }


@console_route("post", "/verification/run")
async def run_verification(payload: dict | None = None):
    from app.services.plugin_runtime_state import get_runtime_state

    runtime_state = get_runtime_state()
    items = []
    for plugin_id in sorted(_plugin_scheduler._plugins):
        result = await _plugin_scheduler.smoke(plugin_id)
        runtime_state.record_smoke(
            plugin_id,
            passed=bool(result.get("pass")),
            message=result.get("message", ""),
            error=result.get("error"),
        )
        items.append({
            "pluginId": plugin_id,
            "pass": result.get("pass", False),
            "mode": result.get("mode", ""),
            "errors": result.get("errors", []),
        })
    passed = sum(1 for item in items if item["pass"])
    failed = len(items) - passed
    return {"summary": {"passed": passed, "failed": failed, "total": len(items)}, "items": items, "archived": False}


# ---- Status (for console dashboard) ----

@console_route("get", "/status")
def get_status():
    # Count from actually loaded plugins so numbers always match the plugin list
    plugins = _plugin_scheduler._plugins
    total = len(plugins)
    enabled = sum(1 for p in plugins.values() if p.metadata.enabled)
    disabled = total - enabled
    from app.services.plugin_runtime_state import get_runtime_state

    runtime_state = get_runtime_state()
    healthy = 0
    unhealthy = 0
    for p in plugins.values():
        state = runtime_state.get_state(p.metadata.id)
        last_ping = state.get("lastPing") or {}
        last_smoke = state.get("lastSmoke") or {}
        if last_ping.get("status") == "reachable" or last_smoke.get("pass") is True:
            healthy += 1
        elif last_ping.get("status") in ("unreachable",) or last_smoke.get("pass") is False:
            unhealthy += 1
    plugin_stats = {
        "total": total,
        "enabled": enabled,
        "disabled": disabled,
        "healthy": healthy,
        "unhealthy": unhealthy,
    }
    return {
        "pluginStats": plugin_stats,
        "sourceStats": plugin_stats,  # compatibility alias
        "plugins": {  # compatibility alias
            "total": total,
            "enabled": enabled,
            "healthy": healthy,
            "unhealthy": unhealthy,
        },
        "version": "0.1.0",
        "phase": APP_PHASE,
    }


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
