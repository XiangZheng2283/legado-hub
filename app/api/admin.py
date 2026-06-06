"""Admin API endpoints for source governance, testing, search jobs, explore, books, and configuration."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
import json
from pathlib import Path

from app.core.aggregate_config import load_aggregate_config, save_aggregate_config, update_progress
from app.core.source_generator import write_aggregate_source
from app.legado_engine.capabilities import default_engine_report
from app.services.catalog import Catalog
from app.services.book_catalog import BookCatalog
from app.services.explore_catalog import ExploreCatalog
from app.services.rule_engine_audit import RuleEngineAuditService
from app.services.source_repository import SourceRepository
from app.services.source_subscriptions import SourceSubscriptionService
from app.services.search_jobs import SearchJobService
from app.services.update_scheduler import UpdateScheduler
from app.services.cache import Cache
from app.services.verification_harness import VerificationHarness

router = APIRouter(prefix="/api/admin")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCE_POOL_CONFIG_PATH = PROJECT_ROOT / "config" / "source_pool.json"
ENGINE_CONFIG_PATH = PROJECT_ROOT / "config" / "rule_engines.json"
SUBSCRIPTION_CONFIG_PATH = PROJECT_ROOT / "config" / "source_subscriptions.json"


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---- Sources ----

@router.get("/sources")
def list_sources(
    enabled_only: bool = False,
    health_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    repo = SourceRepository()
    items = repo.get_sources(enabled_only=enabled_only, health_status=health_status, limit=limit, offset=offset)
    stats = repo.get_stats()
    return {"items": items, "stats": stats, "limit": limit, "offset": offset}


@router.get("/sources/{source_id}")
def get_source(source_id: str):
    repo = SourceRepository()
    src = repo.get_source(source_id)
    if not src:
        return {"error": "书源不存在"}
    attempts = repo.get_attempts(source_id, limit=20)
    return {"source": src, "attempts": attempts}


@router.post("/sources/{source_id}/test")
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


@router.get("/search/stream")
async def stream_search(keyword: str = "", page: int = 1, limit: int | None = None):
    catalog = Catalog()

    async def event_generator():
        async for event in catalog.stream_search(keyword=keyword, page=page, max_sources_override=limit):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/sources/{source_id}/enable")
def enable_source(source_id: str, payload: dict):
    repo = SourceRepository()
    enabled = payload.get("enabled", True)
    repo.set_enabled(source_id, enabled)
    return {"sourceId": source_id, "enabled": enabled}


@router.post("/sources/{source_id}/proxy-mode")
def set_proxy_mode(source_id: str, payload: dict):
    repo = SourceRepository()
    proxy_mode = payload.get("proxyMode", "auto")
    repo.set_proxy_mode(source_id, proxy_mode)
    return {"sourceId": source_id, "proxyMode": proxy_mode}


# ---- Search Jobs ----

_search_service = SearchJobService()


@router.post("/search-jobs")
async def create_search_job(payload: dict):
    keyword = payload.get("keyword", "")
    page = payload.get("page", 1)
    limit = payload.get("limit")
    job = _search_service.create_job(keyword=keyword, page=page, limit=limit)
    # Start job in background
    asyncio = __import__("asyncio")
    asyncio.create_task(_search_service.run_job(job.job_id))
    return {"jobId": job.job_id, "status": job.status, "keyword": keyword}


@router.get("/search-jobs/{job_id}")
def get_search_job(job_id: str):
    job = _search_service.get_job(job_id)
    if not job:
        return {"error": "任务不存在"}
    return {
        "jobId": job.job_id,
        "status": job.status,
        "keyword": job.keyword,
        "page": job.page,
        "sourceCount": len(job.sources),
        "completedCount": job.completed_count,
        "successCount": job.success_count,
        "errorCount": job.error_count,
        "timeoutCount": job.timeout_count,
        "elapsedMs": job.elapsed_ms,
        "result": job.result,
    }


@router.get("/search-jobs/{job_id}/events")
def get_search_job_events(job_id: str, after: int = 0):
    events = _search_service.get_events(job_id, after_index=after)
    return {"jobId": job_id, "events": events, "nextAfter": after + len(events)}


@router.post("/search-jobs/{job_id}/cancel")
def cancel_search_job(job_id: str):
    ok = _search_service.cancel_job(job_id)
    return {"jobId": job_id, "cancelled": ok}


# ---- Explore ----

@router.get("/explore/sources")
def list_explore_sources():
    return {"items": ExploreCatalog().list_explore_sources()}


@router.get("/explore/sources/{source_id}/groups")
def get_explore_groups(source_id: str):
    groups = ExploreCatalog().get_explore_groups(source_id)
    return {"sourceId": source_id, "groups": groups}


@router.post("/explore/sources/{source_id}/items")
async def explore_items(source_id: str, payload: dict):
    explore_url = payload.get("exploreUrl", "")
    page = payload.get("page", 1)
    result = await ExploreCatalog().explore_items(source_id, explore_url, page)
    return result


# ---- Books ----

@router.get("/books")
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


@router.get("/books/{book_id}")
async def get_book(book_id: str):
    catalog = BookCatalog()
    detail = await catalog.book_detail(book_id)
    sources = catalog.get_book_sources(book_id)
    return {"bookId": book_id, "detail": detail, "sources": sources}


@router.get("/books/{book_id}/toc")
async def get_book_toc(book_id: str):
    catalog = BookCatalog()
    return await catalog.toc(book_id)


@router.get("/chapter/{chapter_id}")
async def get_chapter(chapter_id: str):
    catalog = BookCatalog()
    return await catalog.chapter(chapter_id)


@router.get("/chapter/{chapter_id}/fallback")
async def get_chapter_fallback(chapter_id: str, source_ids: str = ""):
    catalog = BookCatalog()
    fallback_ids = [s.strip() for s in source_ids.split(",") if s.strip()]
    return await catalog.chapter_with_fallback(chapter_id, fallback_ids or None)


@router.get("/books/{book_id}/chapters/{chapter_id}/navigation")
def get_chapter_navigation(book_id: str, chapter_id: str):
    catalog = BookCatalog()
    return catalog.get_chapter_navigation(book_id, chapter_id)


# ---- Update Tasks ----

_scheduler = UpdateScheduler()


@router.get("/update-tasks")
def list_update_tasks(limit: int = 100, offset: int = 0):
    return {"items": _scheduler.list_tasks(limit=limit, offset=offset)}


@router.post("/update-tasks/{book_id}/enable")
def enable_update_task(book_id: str):
    return _scheduler.enable_tracking(book_id)


@router.post("/update-tasks/{book_id}/disable")
def disable_update_task(book_id: str):
    return _scheduler.disable_tracking(book_id)


@router.post("/update-tasks/{book_id}/run")
async def run_update_task(book_id: str):
    return await _scheduler.run_check(book_id)


# ---- Cache ----

@router.get("/cache")
def get_cache():
    import sqlite3
    from app.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        search_count = conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
        book_count = conn.execute("SELECT COUNT(*) FROM book_cache").fetchone()[0]
        toc_count = conn.execute("SELECT COUNT(*) FROM toc_cache").fetchone()[0]
        chapter_count = conn.execute("SELECT COUNT(*) FROM chapter_cache").fetchone()[0]
    return {
        "searchCache": search_count,
        "bookCache": book_count,
        "tocCache": toc_count,
        "chapterCache": chapter_count,
    }


@router.post("/cache/clear")
def clear_cache(payload: dict):
    cache_type = payload.get("type", "all")
    import sqlite3
    from app.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        if cache_type in ("all", "search"):
            conn.execute("DELETE FROM search_cache")
        if cache_type in ("all", "book"):
            conn.execute("DELETE FROM book_cache")
        if cache_type in ("all", "toc"):
            conn.execute("DELETE FROM toc_cache")
        if cache_type in ("all", "chapter"):
            conn.execute("DELETE FROM chapter_cache")
        conn.commit()
    return {"cleared": True, "type": cache_type}


# ---- Settings ----

@router.get("/settings")
def get_settings():
    import sqlite3
    from app.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT key, value_json FROM admin_settings").fetchall()
    settings = {r[0]: r[1] for r in rows}
    settings["sourcePool"] = _read_json(SOURCE_POOL_CONFIG_PATH, {})
    settings["ruleEngines"] = _read_json(ENGINE_CONFIG_PATH, {"engines": []})
    settings["sourceSubscriptions"] = _read_json(SUBSCRIPTION_CONFIG_PATH, {"subscriptions": []})
    return settings


@router.post("/settings")
def update_settings(payload: dict):
    import sqlite3
    from app.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        for key, value in payload.items():
            conn.execute(
                "INSERT OR REPLACE INTO admin_settings (key, value_json, updated_at) VALUES (?, ?, datetime('now'))",
                (key, value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)),
            )
        conn.commit()
    if "sourcePool" in payload and isinstance(payload["sourcePool"], dict):
        current = _read_json(SOURCE_POOL_CONFIG_PATH, {})
        current.update(payload["sourcePool"])
        _write_json(SOURCE_POOL_CONFIG_PATH, current)
    if "ruleEngines" in payload and isinstance(payload["ruleEngines"], dict):
        _write_json(ENGINE_CONFIG_PATH, payload["ruleEngines"])
    if "sourceSubscriptions" in payload and isinstance(payload["sourceSubscriptions"], dict):
        _write_json(SUBSCRIPTION_CONFIG_PATH, payload["sourceSubscriptions"])
    return {"saved": True}


# ---- Aggregate Source ----

@router.get("/aggregate-source")
def get_aggregate_source():
    config = load_aggregate_config()
    path = write_aggregate_source()
    config["generated_path"] = path
    return config


@router.post("/aggregate-source/regenerate")
def regenerate_aggregate_source():
    path = write_aggregate_source()
    config = load_aggregate_config()
    config["last_generated_at"] = _now()
    save_aggregate_config(config)
    return {"path": path, "config": config}


# ---- Progress ----

@router.get("/progress")
def get_progress():
    repo = SourceRepository()
    stats = repo.get_stats()
    progress = {
        "configured_sources": stats.get("total", 0),
        "enabled_sources": stats.get("enabled", 0),
        "healthy_sources": stats.get("healthy", 0),
        "proxy_sources": stats.get("proxyNeeded", 0),
        "unsupported_sources": stats.get("unsupported", 0),
    }
    update_progress(progress)
    config = load_aggregate_config()
    return {
        "aggregate": config.get("parser_progress", {}),
        "sources": stats,
    }


# ---- Subscriptions ----

@router.get("/source-subscriptions")
def list_source_subscriptions():
    service = SourceSubscriptionService()
    return service.list_subscriptions()


@router.post("/source-subscriptions")
def add_source_subscription(payload: dict):
    service = SourceSubscriptionService()
    try:
        item = service.add_subscription(payload)
        return {"saved": True, "subscription": item}
    except ValueError as exc:
        return {"saved": False, "error": str(exc)}


@router.post("/source-subscriptions/sync-all")
async def sync_all_source_subscriptions(payload: dict | None = None):
    service = SourceSubscriptionService()
    include_disabled = bool((payload or {}).get("includeDisabled", False))
    return await service.sync_all(include_disabled=include_disabled)


@router.post("/source-subscriptions/{subscription_id}")
def update_source_subscription(subscription_id: str, payload: dict):
    service = SourceSubscriptionService()
    item = service.update_subscription(subscription_id, payload)
    if not item:
        return {"saved": False, "error": "订阅不存在"}
    return {"saved": True, "subscription": item}


@router.post("/source-subscriptions/{subscription_id}/sync")
async def sync_source_subscription(subscription_id: str):
    service = SourceSubscriptionService()
    return await service.sync_subscription(subscription_id)


# ---- Rule Audit ----

@router.get("/rule-engines")
def list_rule_engines():
    return default_engine_report()


@router.get("/rule-audit")
def audit_rules(limit: int = 200, offset: int = 0):
    service = RuleEngineAuditService()
    return service.audit_all(limit=limit, offset=offset)


@router.get("/sources/{source_id}/rule-audit")
def audit_source_rule(source_id: str):
    service = RuleEngineAuditService()
    return service.audit_source(source_id)


# ---- Verification ----

@router.get("/verification")
def get_verification():
    harness = VerificationHarness()
    return harness.load_last_report()


@router.post("/verification/run")
def run_verification(payload: dict | None = None):
    harness = VerificationHarness()
    category = (payload or {}).get("category", "all")
    if category in ("all", "api"):
        harness.run_api_simulations()
    if category in ("all", "ui"):
        harness.run_ui_simulations()
    harness.save_report()
    return harness.get_report()


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
