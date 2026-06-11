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
from app.services.update_scheduler import UpdateScheduler
from app.services.cache import Cache
from app.services.source_ping import SourcePingService
from app.services.login_browser_service import login_browser_service
from app.services.official_auth.manager import official_auth_manager
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


def _plugin_access_type(plugin) -> str:
    browser_mode = (plugin.metadata.browser or {}).get("mode", "none")
    return "Browser" if browser_mode == "required" else "HTTP"


def _plugin_source_type(plugin) -> str:
    return _plugin_access_type(plugin)


def _plugin_last_modified(plugin) -> str:
    return getattr(plugin.source, "last_modified", "") if plugin.source else ""


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
                "health": repo.get_plugin(p.metadata.id),
            }
            for p in plugins.values()
        ],
        "total": len(plugins),
    }


@console_route("get", "/official-sources")
def list_official_sources():
    plugins = _plugin_scheduler._plugins
    auth_repo = PluginAuthRepository()
    items = []
    for plugin in plugins.values():
        auth_mode = (plugin.metadata.auth or {}).get("mode", "none")
        if not plugin.metadata.is_official_source() and auth_mode == "none":
            continue
        status = auth_repo.get_status(plugin.metadata.id)
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
            "authStatus": status,
        })
    items.sort(key=lambda item: (not item["official"], item["name"], item["pluginId"]))
    return {"items": items, "total": len(items)}


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
    repo = PluginHealthRepository()
    repo.set_enabled(plugin_id, enabled)
    return {"pluginId": plugin_id, "enabled": enabled}


@console_route("post", "/plugins/batch-enable")
def batch_enable_plugins(payload: dict):
    plugin_ids = payload.get("pluginIds", [])
    enabled = payload.get("enabled", True)
    repo = PluginHealthRepository()
    results = []
    for plugin_id in plugin_ids:
        plugin = _plugin_scheduler._plugins.get(plugin_id)
        if plugin:
            plugin.metadata.enabled = enabled
            repo.set_enabled(plugin_id, enabled)
            results.append({"pluginId": plugin_id, "enabled": enabled})
        else:
            results.append({"pluginId": plugin_id, "error": "插件不存在"})
    return {"results": results}


@console_route("post", "/plugins/batch-delete")
def batch_delete_plugins(payload: dict):
    plugin_ids = payload.get("pluginIds", [])
    repo = PluginHealthRepository()
    results = []
    for plugin_id in plugin_ids:
        plugin = _plugin_scheduler._plugins.get(plugin_id)
        if plugin:
            plugin.metadata.enabled = False
        # Also remove from health repo
        repo.set_enabled(plugin_id, False)
        with repo._conn() as conn:
            conn.execute("DELETE FROM plugin_health WHERE plugin_id = ?", (plugin_id,))
            conn.execute("DELETE FROM plugin_attempts WHERE plugin_id = ?", (plugin_id,))
            conn.commit()
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
                "cookieDomains": stored.get("cookieDomains", []),
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
            auth_repo = PluginAuthRepository()
            auth_repo.set_cookies(plugin_id, session.cookies)
            # Also update auth status so the next /auth check reflects the new cookies
            auth_repo.update_status(
                plugin_id,
                {
                    "authenticated": False,  # will be verified by real auth_status check
                    "accountName": "",
                    "expiresAt": "",
                    "message": "Cookie 已通过浏览器登录获取，等待状态校验",
                    "requiredActions": ["check_auth_status"],
                },
            )
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
    return official_auth_manager.verify_phone_code(plugin_id, payload)


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
    # Enrich with lastModified from loaded plugins
    for item in items:
        plugin_id = item.get("pluginId", "")
        plugin = _plugin_scheduler._plugins.get(plugin_id)
        if plugin:
            item["lastModified"] = _plugin_last_modified(plugin)
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
    source_ids = payload.get("sourceIds")
    job = _search_service.create_job(keyword=keyword, page=page, limit=limit, source_ids=source_ids)
    job.status = "running"
    queued_event = {
        "type": "queued",
        "keyword": keyword,
        "page": page,
        "sourceCount": len(job.sources),
        "completedCount": 0,
    }
    job.events.append(queued_event)
    _search_service.persist_job(job)
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


@console_route("get", "/search-jobs")
def list_search_jobs(limit: int = 20):
    return {"items": _search_service.list_jobs(limit=limit)}


@console_route("get", "/search-jobs/{job_id}")
def get_search_job(job_id: str):
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
            # Rebuild candidate groups from filtered items
            from app.services.live_acceptance import group_candidates
            candidate_groups = group_candidates(items, job.keyword)
        debug = dict(result.get("debug", {}))
        debug["scoreFilter"] = score_filter
        debug["filteredCount"] = filtered_count
        result = {**result, "items": items, "debug": debug}
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
        "result": result,
        "candidateGroups": candidate_groups,
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
            SELECT keyword, page, response_json, created_at
            FROM search_cache
            ORDER BY created_at DESC
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
    for keyword, page, response_json, created_at in search_rows:
        payload = _json_payload(response_json)
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        searches.append({
            "keyword": keyword,
            "page": page,
            "itemCount": len(items),
            "createdAt": created_at,
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
    if isinstance(settings.get("contentWorkflow"), str):
        settings["contentWorkflow"] = _json_payload(settings.get("contentWorkflow"))
    settings.setdefault("searchScoreFilter", 100)
    settings.setdefault("contentWorkflow", {
        "aggregationMode": "balanced",
        "autoAggregate": True,
        "processAggregateOnRead": True,
        "aggregateCheckIntervalMinutes": 30,
        "returnOnlyAggregateSource": False,
        "sourceCandidateLimit": 6,
        "purifyMode": "conservative",
        "blockedWordRepair": False,
        "aiProvider": "",
        "model": "",
    })
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
        _plugin_scheduler.config = current
        _search_service.scheduler.config = current
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
            "lastModified": _plugin_last_modified(plugin),
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
    # Count from actually loaded plugins so numbers always match the plugin list
    plugins = _plugin_scheduler._plugins
    total = len(plugins)
    enabled = sum(1 for p in plugins.values() if p.metadata.enabled)
    disabled = total - enabled
    plugin_stats = {
        "total": total,
        "enabled": enabled,
        "disabled": disabled,
    }
    return {
        "pluginStats": plugin_stats,
        "sourceStats": plugin_stats,  # compatibility alias
        "plugins": {  # compatibility alias
            "total": total,
            "enabled": enabled,
        },
        "version": "0.1.0",
        "phase": APP_PHASE,
    }


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
