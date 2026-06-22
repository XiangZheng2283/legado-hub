"""Phase-6 validation script for the host-layer refactor.

Run from the repo root or backend/:

    python scripts/validate_refactor.py

It checks:
1. Configuration and Cookie boundaries.
2. Database schema (new tables present, old tables absent).
3. Tightened proxy policy.
4. SearchCoordinator can be created and accepts jobs.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
CONFIG_DIR = BACKEND_ROOT / "config"
COOKIE_DIR = CONFIG_DIR / "cookies"
DB_PATH = BACKEND_ROOT / "data" / "app.db"

# Make the backend package importable regardless of the invocation directory.
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def check_path(path: Path, should_exist: bool) -> bool:
    exists = path.exists()
    label = "exists" if should_exist else "does not exist"
    ok = exists == should_exist
    print(f"  [{'OK' if ok else 'FAIL'}] {path} {label}")
    return ok


def validate_config_cookie_boundary() -> bool:
    print("\n[1] Config / Cookie boundary")
    ok = True
    ok &= check_path(CONFIG_DIR / "app_config.json", True)
    ok &= check_path(COOKIE_DIR, True)
    ok &= check_path(CONFIG_DIR / "source_pool.json", False)
    ok &= check_path(CONFIG_DIR / "aggregate_source.json", False)

    from app.core.app_config import AppConfig
    from app.services.cookie_store import CookieStore

    cfg = AppConfig.get()
    ok &= isinstance(cfg.proxy.enabled, bool)
    ok &= isinstance(cfg.search.global_source_concurrency, int)
    print(f"  [{'OK' if ok else 'FAIL'}] AppConfig loads from app_config.json")

    store = CookieStore()
    store.save("__validation__", {"test": True})
    payload = store.load("__validation__")
    store.clear("__validation__")
    ok &= payload == {"test": True}
    ok &= not store.has("__validation__")
    print(f"  [{'OK' if ok else 'FAIL'}] CookieStore round-trip works")
    return ok


def validate_database_schema() -> bool:
    print("\n[2] Database schema")
    from app.storage.db import initialize_database

    initialize_database()
    conn = sqlite3.connect(DB_PATH)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    ok = True
    required = {
        "schema_meta",
        "search_jobs",
        "search_results",
        "search_query_cache",
        "book_cache",
        "toc_cache",
        "chapter_cache",
        "aggregate_book_tasks",
        "aggregate_chapter_tasks",
        "aggregate_ai_usage",
    }
    forbidden = {
        "plugin_health",
        "plugin_attempts",
        "search_job_events",
        "plugin_runtime_state",
        "plugin_auth_state",
        "admin_settings",
        "aggregate_settings",
        "source_registry",
        "search_cache",
    }
    for table in required:
        present = table in tables
        print(f"  [{'OK' if present else 'FAIL'}] required table '{table}' present")
        ok &= present
    for table in forbidden:
        absent = table not in tables
        print(f"  [{'OK' if absent else 'FAIL'}] old table '{table}' absent")
        ok &= absent

    # Verify the tightened search_jobs / search_query_cache structure.
    def cols(table: str) -> set[str]:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}

    search_jobs_cols = cols("search_jobs")
    for col in ("source_scope", "normalized_keyword"):
        present = col in search_jobs_cols
        print(f"  [{'OK' if present else 'FAIL'}] search_jobs.{col} present")
        ok &= present
    for col in ("result_json", "sources_json"):
        absent = col not in search_jobs_cols
        print(f"  [{'OK' if absent else 'FAIL'}] search_jobs.{col} removed")
        ok &= absent

    sqc_cols = cols("search_query_cache")
    for col in ("source_scope", "result_json"):
        present = col in sqc_cols
        print(f"  [{'OK' if present else 'FAIL'}] search_query_cache.{col} present")
        ok &= present

    conn.close()
    return ok


def validate_legacy_repositories_gone() -> bool:
    print("\n[2.5] Legacy repository files and imports")
    ok = True
    for path in (
        BACKEND_ROOT / "app" / "services" / "plugin_health_repository.py",
        BACKEND_ROOT / "app" / "services" / "plugin_auth_repository.py",
    ):
        absent = not path.exists()
        print(f"  [{'OK' if absent else 'FAIL'}] {path.name} deleted")
        ok &= absent

    for mod in (
        "app.services.plugin_health_repository",
        "app.services.plugin_auth_repository",
    ):
        try:
            __import__(mod)
            print(f"  [FAIL] {mod} still importable")
            ok = False
        except ImportError:
            print(f"  [OK] {mod} no longer importable")
    return ok


def validate_proxy_policy() -> bool:
    print("\n[3] Proxy policy")
    from unittest.mock import MagicMock

    from app.source_plugins.scheduler import PluginScheduler

    scheduler = PluginScheduler()
    ok = True

    def make_plugin(proxy_mode: str, required: bool):
        p = MagicMock()
        p.metadata.proxy = {"mode": proxy_mode, "required": required}
        return p

    scheduler.config = {
        "proxy": {"enabled": True, "url": "http://proxy.example", "allowAutoRetry": False}
    }
    # never -> direct
    ok &= scheduler._resolve_proxy_url(make_plugin("never", False)) == ""
    # auto without required/allowAutoRetry -> direct
    ok &= scheduler._resolve_proxy_url(make_plugin("auto", False)) == ""
    # auto with required but no allowAutoRetry -> direct
    ok &= scheduler._resolve_proxy_url(make_plugin("auto", True)) == ""
    # always -> proxy
    ok &= scheduler._resolve_proxy_url(make_plugin("always", False)) == "http://proxy.example"

    scheduler.config["proxy"]["allowAutoRetry"] = True
    # auto + required + allowAutoRetry -> proxy
    ok &= scheduler._resolve_proxy_url(make_plugin("auto", True)) == "http://proxy.example"
    # auto without required + allowAutoRetry -> direct
    ok &= scheduler._resolve_proxy_url(make_plugin("auto", False)) == ""

    scheduler.config = {"proxy": {"enabled": False, "url": "http://proxy.example"}}
    ok &= scheduler._resolve_proxy_url(make_plugin("always", False)) == ""

    print(f"  [{'OK' if ok else 'FAIL'}] tightened proxy rules")
    return ok


def validate_search_coordinator() -> bool:
    print("\n[4] SearchCoordinator")
    import asyncio

    from app.services.search_coordinator import SearchCoordinator

    coordinator = SearchCoordinator()

    # Patch per-source search to a fast synthetic implementation so validation
    # does not depend on external network conditions.
    async def fake_search_one(self, plugin_id: str, keyword: str, page: int) -> dict:
        await asyncio.sleep(0.05)
        return {
            "items": [
                {
                    "sourceId": plugin_id,
                    "sourceName": plugin_id,
                    "name": f"{keyword} result",
                    "author": "test",
                    "bookUrl": f"https://example.com/{plugin_id}/{keyword}",
                    "score": 120,
                }
            ],
            "error": None,
            "latencyMs": 50,
            "proxyUsed": False,
        }

    coordinator.scheduler.search_one = lambda pid, kw, pg: fake_search_one(
        coordinator.scheduler, pid, kw, pg
    )

    # Scope-aware deduplication: same keyword + page but different source_ids
    # must produce different jobs. These submits happen outside a running event
    # loop, so they intentionally create pending jobs without scheduling tasks.
    j1 = coordinator.submit("scope-check", page=1, source_ids=["qidian_com_web"], allow_cache=False)
    j2 = coordinator.submit("scope-check", page=1, source_ids=["biquge365_net"], allow_cache=False)
    ok_scope = j1.job_id != j2.job_id
    print(f"  [{'OK' if ok_scope else 'FAIL'}] different source_ids produce different jobs")
    ok_default_scope = bool(j1.source_scope and j2.source_scope)
    print(f"  [{'OK' if ok_default_scope else 'FAIL'}] jobs carry a source_scope")

    async def run_one():
        job = coordinator.submit("validation", page=1, limit=1, allow_cache=False)
        ok_submit = job.status in {"pending", "running"}
        print(f"  [{'OK' if ok_submit else 'FAIL'}] submit returns a job (status={job.status})")

        # submit() schedules the task when called inside a running loop.
        for _ in range(100):
            if job.status in {"completed", "cancelled"}:
                break
            await asyncio.sleep(0.05)

        ok_terminal = job.status in {"completed", "cancelled"}
        print(f"  [{'OK' if ok_terminal else 'FAIL'}] job reaches terminal state")

        # Historical detail reconstruction from DB.
        job_id = job.job_id
        coordinator._jobs.clear()
        coordinator._jobs_by_key.clear()
        coordinator._completed_jobs.clear()
        loaded = coordinator.get_job(job_id)
        ok_rebuild = loaded is not None and bool(loaded.result)
        print(f"  [{'OK' if ok_rebuild else 'FAIL'}] job detail rebuilds from DB after memory drop")
        return ok_submit and ok_terminal and ok_rebuild

    ok = asyncio.run(run_one()) and ok_scope and ok_default_scope
    return ok


def main() -> int:
    print("Phase-6 validation")
    ok = True
    ok &= validate_config_cookie_boundary()
    ok &= validate_database_schema()
    ok &= validate_legacy_repositories_gone()
    ok &= validate_proxy_policy()
    ok &= validate_search_coordinator()
    print("\n" + ("All checks passed." if ok else "Some checks failed."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
