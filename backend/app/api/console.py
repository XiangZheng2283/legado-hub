"""Console API endpoints for plugin governance, testing, search jobs, explore, books, and configuration."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.config import APP_PHASE, SOURCE_POOL_CONFIG_PATH
from app.core.aggregate_config import load_aggregate_config, save_aggregate_config, update_progress
from app.core.source_generator import write_aggregate_source
from app.services.catalog import Catalog
from app.services.book_catalog import BookCatalog
from app.services.plugin_health_repository import PluginHealthRepository
from app.services.plugin_auth_repository import PluginAuthRepository
from app.services.search_jobs import SearchJobService
from app.services.live_acceptance import LiveAcceptanceService
from app.services.live_check_repository import LiveCheckRepository
from app.services.browser_challenge import BrowserChallengeService
from app.services.browser_helper import BrowserHelperService
from app.services.update_scheduler import UpdateScheduler
from app.services.cache import Cache
from app.source_plugins.loader import PluginLoader
from app.source_plugins.scheduler import PluginScheduler

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


# ---- Plugins ----

_plugin_loader = PluginLoader()
_plugin_scheduler = PluginScheduler()
_browser_challenge_service = BrowserChallengeService()
_browser_helper_service = BrowserHelperService()


def _plugin_access_type(plugin) -> str:
    browser_mode = (plugin.metadata.browser or {}).get("mode", "none")
    return "Browser" if browser_mode == "required" else "HTTP"


def _plugin_source_type(plugin) -> str:
    return _plugin_access_type(plugin)


@console_route("get", "/plugins")
def list_plugins():
    plugins = _plugin_scheduler._plugins
    repo = PluginHealthRepository()
    return {
        "items": [
            {
                "pluginId": p.metadata.id,
                "name": p.metadata.name,
                "version": p.metadata.version,
                "enabled": p.metadata.enabled,
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
                "health": repo.get_plugin(p.metadata.id),
            }
            for p in plugins.values()
        ],
        "total": len(plugins),
    }


@console_route("get", "/plugins/{plugin_id}")
def get_plugin(plugin_id: str):
    plugin = _plugin_scheduler._plugins.get(plugin_id)
    if not plugin:
        return {"error": "插件不存在"}
    repo = PluginHealthRepository()
    return {
        "pluginId": plugin.metadata.id,
        "name": plugin.metadata.name,
        "version": plugin.metadata.version,
        "enabled": plugin.metadata.enabled,
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
        "health": repo.get_plugin(plugin.metadata.id),
    }


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
    return {"pluginId": plugin_id, "enabled": enabled}


@console_route("post", "/plugins/{plugin_id}/smoke")
async def smoke_plugin(plugin_id: str, payload: dict | None = None):
    keyword = (payload or {}).get("keyword", "凡人修仙传")
    result = await _plugin_scheduler.smoke(plugin_id, keyword=keyword)
    return result


@console_route("get", "/plugins/{plugin_id}/auth")
async def get_plugin_auth(plugin_id: str):
    plugin = _plugin_scheduler._plugins.get(plugin_id)
    if not plugin:
        return {"error": "插件不存在"}
    auth_repo = PluginAuthRepository()
    auth_meta = plugin.metadata.auth or {}
    if auth_meta.get("mode", "none") == "none":
        stored = auth_repo.get_status(plugin_id)
        browser_meta = plugin.metadata.browser or {}
        if browser_meta.get("mode") == "required":
            has_cookies = stored.get("hasCookies", False)
            challenge = None
            if not has_cookies:
                challenge = _browser_challenge_service.create_for_plugin(
                    plugin,
                    stage="auth",
                    url=browser_meta.get("verificationUrl", ""),
                    reason="BROWSER_REQUIRED",
                    message="该插件无需账号登录，但需要先在真实浏览器中完成访问验证。",
                )
            return {
                "sourceId": plugin_id,
                "mode": "browser_verification",
                "authenticated": False,
                "accountName": "",
                "expiresAt": "",
                "message": (
                    "已保存 Cookie，请运行实时验收确认该书源是否恢复可读。"
                    if has_cookies
                    else "该插件无需账号登录，但需要浏览器验证 Cookie。"
                ),
                "requiredActions": ["retry_live_check"] if has_cookies else ["browser_verification"],
                "hasCookies": has_cookies,
                "cookieDomains": stored.get("cookieDomains", []),
                "verificationStatus": "cookies_saved" if has_cookies else "required",
                "browserChallenges": [challenge] if challenge else [],
            }
        return {
            "sourceId": plugin_id,
            "mode": "none",
            "authenticated": False,
            "accountName": "",
            "expiresAt": "",
            "message": "该插件无需登录",
            "requiredActions": [],
            "hasCookies": stored.get("hasCookies", False),
            "cookieDomains": stored.get("cookieDomains", []),
        }
    if "auth" not in plugin.capabilities:
        stored = auth_repo.get_status(plugin_id)
        stored.update({
            "mode": auth_meta.get("mode", "optional"),
            "message": "该插件尚未实现登录检测方法",
            "requiredActions": ["manual_login"] if auth_meta.get("loginUrl") else [],
        })
        return stored
    ctx = _plugin_scheduler._make_ctx(plugin_id)
    try:
        result = await plugin.source.auth_status(ctx)
        result.setdefault("mode", auth_meta.get("mode", "optional"))
        auth_repo.update_status(plugin_id, result)
    except Exception as exc:
        result = {
            "sourceId": plugin_id,
            "mode": auth_meta.get("mode", "optional"),
            "authenticated": False,
            "accountName": "",
            "expiresAt": "",
            "message": str(exc),
            "requiredActions": [],
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
    PluginAuthRepository().clear_cookies(plugin_id)
    return {"cleared": True, "pluginId": plugin_id}


# ---- Browser Challenges ----

@console_route("get", "/browser-challenges")
def list_browser_challenges(source_id: str | None = None):
    return {"items": _browser_challenge_service.list(source_id=source_id)}


@console_route("post", "/plugins/{plugin_id}/browser-challenge")
def create_plugin_browser_challenge(plugin_id: str, payload: dict | None = None):
    plugin = _plugin_scheduler._plugins.get(plugin_id)
    if not plugin:
        return {"error": "插件不存在"}
    payload = payload or {}
    return _browser_challenge_service.create_for_plugin(
        plugin,
        stage=payload.get("stage", "manual"),
        url=payload.get("url", ""),
        reason=payload.get("reason", "BROWSER_REQUIRED"),
        message=payload.get("message", ""),
    )


@console_route("get", "/browser-challenges/{session_id}")
def get_browser_challenge(session_id: str):
    session = _browser_challenge_service.get(session_id)
    if not session:
        return {"error": "验证会话不存在", "sessionId": session_id}
    return session


@console_route("post", "/browser-challenges/{session_id}/cookies")
def submit_browser_challenge_cookies(session_id: str, payload: dict):
    return _browser_challenge_service.submit_cookies(session_id, payload.get("cookies", payload))


@console_route("post", "/browser-challenges/{session_id}/browser/open")
def open_browser_challenge_browser(session_id: str):
    session = _browser_challenge_service.get(session_id)
    if not session:
        return {"started": False, "error": "验证会话不存在", "sessionId": session_id}
    result = _browser_helper_service.start(session)
    if result.get("started"):
        _browser_challenge_service.record_browser_helper(session_id, result)
    return result


@console_route("get", "/browser-challenges/{session_id}/browser/status")
def get_browser_challenge_browser_status(session_id: str):
    return _browser_helper_service.status(session_id)


@console_route("post", "/browser-challenges/{session_id}/browser/import-cookies")
def import_browser_challenge_browser_cookies(session_id: str):
    cookies = _browser_helper_service.cookies(session_id)
    if not cookies:
        return {"saved": False, "error": "未找到浏览器助手 Cookie，请先完成验证或稍后重试", "sessionId": session_id}
    return _browser_challenge_service.submit_cookies(session_id, cookies)


@console_route("post", "/browser-challenges/{session_id}/retry-live-check")
async def retry_browser_challenge_live_check(session_id: str, payload: dict | None = None):
    session = _browser_challenge_service.get(session_id)
    if not session:
        return {"error": "验证会话不存在", "sessionId": session_id}
    payload = payload or {}
    result = await _live_acceptance_service.run_plugin_live_check(
        plugin_id=session["sourceId"],
        keyword=payload.get("keyword", "凡人修仙传"),
        candidate_index=int(payload.get("candidateIndex", 0) or 0),
        chapter_index=int(payload.get("chapterIndex", 0) or 0),
        persist=True,
    )
    return _browser_challenge_service.record_retry_result(session_id, result)


# ---- Plugin Health ----

@console_route("get", "/sources")
def list_sources(
    enabled_only: bool = False,
    health_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    repo = PluginHealthRepository()
    items = repo.get_plugins(enabled_only=enabled_only, health_status=health_status, limit=limit, offset=offset)
    stats = repo.get_stats()
    return {"items": items, "stats": stats, "limit": limit, "offset": offset, "legacyAlias": True}


@console_route("get", "/sources/{source_id}")
def get_source(source_id: str):
    repo = PluginHealthRepository()
    src = repo.get_plugin(source_id)
    if not src:
        return {"error": "书源不存在"}
    attempts = repo.get_attempts(source_id, limit=20)
    return {"source": src, "attempts": attempts}


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
    repo = PluginHealthRepository()
    enabled = payload.get("enabled", True)
    repo.set_enabled(source_id, enabled)
    return {"sourceId": source_id, "enabled": enabled}


@console_route("post", "/sources/{source_id}/proxy-mode")
def set_proxy_mode(source_id: str, payload: dict):
    repo = PluginHealthRepository()
    proxy_mode = payload.get("proxyMode", "auto")
    repo.set_proxy_mode(source_id, proxy_mode)
    return {"sourceId": source_id, "proxyMode": proxy_mode}


# ---- Search Jobs ----

_search_service = SearchJobService()
_live_check_repository = LiveCheckRepository()
_live_acceptance_service = LiveAcceptanceService(
    scheduler=_plugin_scheduler,
    repository=_live_check_repository,
)


def _run_search_job_blocking(job_id: str) -> None:
    asyncio.run(_search_service.run_job(job_id))


@console_route("post", "/search-jobs")
async def create_search_job(payload: dict):
    keyword = payload.get("keyword", "")
    page = payload.get("page", 1)
    limit = payload.get("limit")
    job = _search_service.create_job(keyword=keyword, page=page, limit=limit)
    job.status = "running"
    queued_event = {
        "type": "queued",
        "keyword": keyword,
        "page": page,
        "sourceCount": len(job.sources),
        "completedCount": 0,
    }
    job.events.append(queued_event)
    threading.Thread(target=_run_search_job_blocking, args=(job.job_id,), daemon=True).start()
    return {
        "jobId": job.job_id,
        "status": job.status,
        "keyword": keyword,
        "page": page,
        "sourceCount": len(job.sources),
        "completedCount": 0,
        "successCount": 0,
        "errorCount": 0,
        "timeoutCount": 0,
        "elapsedMs": 0,
        "candidateGroups": [],
        "events": [queued_event],
    }


@console_route("get", "/search-jobs/{job_id}")
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
        "candidateGroups": job.candidate_groups,
        "browserChallenges": job.browser_challenges,
    }


@console_route("get", "/search-jobs/{job_id}/events")
def get_search_job_events(job_id: str, after: int = 0):
    events = _search_service.get_events(job_id, after_index=after)
    return {"jobId": job_id, "events": events, "nextAfter": after + len(events)}


@console_route("get", "/search-jobs/{job_id}/candidates")
def get_search_job_candidates(job_id: str):
    job = _search_service.get_job(job_id)
    if not job:
        return {"error": "任务不存在", "items": []}
    return {"jobId": job_id, "items": _search_service.get_candidates(job_id)}


@console_route("post", "/search-jobs/{job_id}/candidates/{candidate_id}/verify")
async def verify_search_job_candidate(job_id: str, candidate_id: str, payload: dict | None = None):
    candidate = _search_service.find_candidate(job_id, candidate_id)
    if not candidate:
        return {"error": "候选不存在", "jobId": job_id, "candidateId": candidate_id}
    job = _search_service.get_job(job_id)
    chapter_index = (payload or {}).get("chapterIndex", 0)
    result = await _live_acceptance_service.verify_candidate(
        candidate,
        keyword=job.keyword if job else "",
        chapter_index=chapter_index,
    )
    return {"jobId": job_id, "candidateId": candidate_id, "result": result}


@console_route("post", "/search-jobs/{job_id}/cancel")
def cancel_search_job(job_id: str):
    ok = _search_service.cancel_job(job_id)
    return {"jobId": job_id, "cancelled": ok}


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
    return await _plugin_scheduler.explore(source_id, group_id=group_id, page=page)


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


@console_route("delete", "/cache")
def clear_cache():
    import sqlite3
    from app.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM search_cache")
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

@console_route("get", "/settings")
def get_settings():
    import sqlite3
    from app.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute("SELECT key, value_json FROM admin_settings").fetchall()
    settings = {r[0]: r[1] for r in rows}
    settings["sourcePool"] = _read_json(SOURCE_POOL_CONFIG_PATH, {})
    settings["legacy"] = {
        "ruleEngines": _legacy_archived("rule_engines"),
        "sourceSubscriptions": _legacy_archived("source_subscriptions"),
    }
    return settings


@console_route("post", "/settings")
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


# ---- Progress ----

@console_route("get", "/progress")
def get_progress():
    repo = PluginHealthRepository()
    stats = repo.get_stats()
    plugin_count = len(_plugin_scheduler._plugins)
    enabled_plugin_count = sum(1 for p in _plugin_scheduler._plugins.values() if p.metadata.enabled)
    plugin_stats = {
        "total": plugin_count,
        "enabled": enabled_plugin_count,
        "healthy": stats.get("healthy", 0),
        "disabled": stats.get("disabled", 0),
        "proxyNeeded": stats.get("proxyNeeded", 0),
    }
    progress = {
        "pluginStats": plugin_stats,
        "configured_sources": stats.get("total", 0),  # compat alias
        "enabled_sources": stats.get("enabled", 0),  # compat alias
        "healthy_sources": stats.get("healthy", 0),  # compat alias
        "proxy_sources": stats.get("proxyNeeded", 0),  # compat alias
        "unsupported_sources": stats.get("unsupported", 0),  # compat alias
        "plugin_count": plugin_count,  # compat alias
        "enabled_plugin_count": enabled_plugin_count,  # compat alias
    }
    update_progress(progress)
    config = load_aggregate_config()
    return {
        "aggregate": config.get("parser_progress", {}),
        "pluginStats": plugin_stats,
        "sources": stats,  # compat alias
        "plugins": {  # compat alias
            "total": plugin_count,
            "enabled": enabled_plugin_count,
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
    repo = PluginHealthRepository()
    items = []
    for plugin in _plugin_scheduler._plugins.values():
        health = repo.get_plugin(plugin.metadata.id) or {}
        result = health.get("lastTestResult")
        items.append({
            "pluginId": plugin.metadata.id,
            "name": plugin.metadata.name,
            "hasFixtureSmoke": (_plugin_scheduler.loader.plugins_dir / plugin.metadata.id / "tests" / "smoke.yaml").exists(),
            "lastSmokePass": result.get("pass") if isinstance(result, dict) else None,
            "lastError": health.get("lastError", ""),
            "authMode": (plugin.metadata.auth or {}).get("mode", "none"),
            "capabilities": plugin.capabilities,
        })
    passed = sum(1 for item in items if item["lastSmokePass"] is True)
    failed = sum(1 for item in items if item["lastSmokePass"] is False)
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
    items = []
    for plugin_id in sorted(_plugin_scheduler._plugins):
        result = await _plugin_scheduler.smoke(plugin_id)
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
    repo = PluginHealthRepository()
    stats = repo.get_stats()
    plugin_count = len(_plugin_scheduler._plugins)
    enabled_plugin_count = sum(1 for p in _plugin_scheduler._plugins.values() if p.metadata.enabled)
    plugin_stats = {
        "total": plugin_count,
        "enabled": enabled_plugin_count,
        "healthy": stats.get("healthy", 0),
        "disabled": stats.get("disabled", 0),
        "proxyNeeded": stats.get("proxyNeeded", 0),
    }
    return {
        "pluginStats": plugin_stats,
        "sourceStats": stats,  # compatibility alias
        "plugins": {  # compatibility alias
            "total": plugin_count,
            "enabled": enabled_plugin_count,
        },
        "version": "0.1.0",
        "phase": APP_PHASE,
    }


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
