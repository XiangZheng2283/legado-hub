"""Real-source end-to-end validation for the refactored search layer.

This script exercises SearchCoordinator with the actual enabled plugins and
real network requests. It intentionally avoids synthetic sources so we can see
how default search, explicit official sources, scope isolation, history
reconstruction, cache scope, and stage routing behave in production-like
conditions.

Run from the repo root or backend/:

    python scripts/validate_real_sources.py

The script respects the host timeout settings in app_config.json. Slow or
unreachable sources are expected and are reported, not treated as failures
unless the host layer itself misbehaves.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.search_coordinator import SearchCoordinator


def _official_ids(coordinator: SearchCoordinator) -> set[str]:
    return {
        pid
        for pid, p in coordinator.scheduler._plugins.items()
        if p.metadata.is_official_source()
    }


async def _await_job(job, timeout: float = 60.0) -> None:
    deadline = time.perf_counter() + timeout
    while job.status not in {"completed", "cancelled"}:
        if time.perf_counter() > deadline:
            break
        await asyncio.sleep(0.1)


def _summarize_job(job) -> dict:
    result = job.result or {}
    items = [dict(i) for i in result.get("items", []) if isinstance(i, dict)]
    debug = result.get("debug", {})
    stages = {}
    for ev in job.events:
        if ev.get("type") == "stage_start":
            stages[ev.get("stage")] = ev.get("sourceCount", 0)
    return {
        "job_id": job.job_id,
        "status": job.status,
        "sources": [s.get("sourceId") for s in job.sources],
        "source_scope": job.source_scope,
        "items": len(items),
        "candidate_groups": len(job.candidate_groups),
        "elapsed_ms": job.elapsed_ms,
        "completed": job.completed_count,
        "success": job.success_count,
        "errors": debug.get("errorCount", 0),
        "stages": stages,
        "first_item": items[0] if items else None,
    }


async def main() -> int:
    coordinator = SearchCoordinator()
    official_ids = _official_ids(coordinator)
    print(f"Official source ids: {sorted(official_ids) or 'none'}")
    print(f"Enabled plugins: {len(coordinator.scheduler._plugins)}")
    ok = True

    # ------------------------------------------------------------------
    # 1. Default search (official sources hidden)
    # ------------------------------------------------------------------
    print("\n[1] Default search: keyword='诡秘之主', no source_ids, limit=3")
    t0 = time.perf_counter()
    default_job = coordinator.submit("诡秘之主", page=1, limit=3, allow_cache=False)
    await _await_job(default_job, timeout=45.0)
    default_summary = _summarize_job(default_job)
    print(f"  status={default_summary['status']}, elapsed={default_summary['elapsed_ms']}ms")
    print(f"  sources={default_summary['sources']}")
    print(f"  items={default_summary['items']}, errors={default_summary['errors']}")
    print(f"  stages={default_summary['stages']}")
    used_official = set(default_summary["sources"]) & official_ids
    if used_official:
        print(f"  WARNING: default search included official sources: {used_official}")
        ok = False
    else:
        print("  OK: default search did not include official sources")

    # ------------------------------------------------------------------
    # 2. Explicit official source
    # ------------------------------------------------------------------
    explicit_official = "qidian_com_web" if "qidian_com_web" in official_ids else next(iter(official_ids), "")
    if explicit_official:
        print(f"\n[2] Explicit official source: {explicit_official}")
        official_job = coordinator.submit(
            "诡秘之主", page=1, source_ids=[explicit_official], allow_cache=False
        )
        await _await_job(official_job, timeout=45.0)
        official_summary = _summarize_job(official_job)
        print(f"  status={official_summary['status']}, elapsed={official_summary['elapsed_ms']}ms")
        print(f"  sources={official_summary['sources']}")
        print(f"  items={official_summary['items']}, errors={official_summary['errors']}")
        print(f"  stages={official_summary['stages']}")
        if explicit_official not in official_summary["sources"]:
            print(f"  WARNING: requested official source was not in job sources")
            ok = False
        else:
            print("  OK: explicit official source entered the job")
    else:
        print("\n[2] SKIP: no official source available")

    # ------------------------------------------------------------------
    # 3. Scope isolation: same keyword, different source_ids
    # ------------------------------------------------------------------
    enabled_non_official = [
        pid
        for pid, p in coordinator.scheduler._plugins.items()
        if p.metadata.enabled and not p.metadata.is_official_source()
    ][:2]
    if len(enabled_non_official) >= 2:
        a, b = enabled_non_official[0], enabled_non_official[1]
        print(f"\n[3] Scope isolation: {a} vs {b}")
        ja = coordinator.submit("诡秘之主", page=1, source_ids=[a], allow_cache=False)
        jb = coordinator.submit("诡秘之主", page=1, source_ids=[b], allow_cache=False)
        await _await_job(ja, timeout=30.0)
        await _await_job(jb, timeout=30.0)
        print(f"  job_a={ja.job_id}, sources={_summarize_job(ja)['sources']}")
        print(f"  job_b={jb.job_id}, sources={_summarize_job(jb)['sources']}")
        if ja.job_id == jb.job_id:
            print("  FAIL: same job id for different scopes")
            ok = False
        else:
            print("  OK: different scopes produced different jobs")

        # Cache scope isolation
        cached_a = coordinator.get_cached_result("诡秘之主", 1, coordinator._scope_key([a]))
        cached_b = coordinator.get_cached_result("诡秘之主", 1, coordinator._scope_key([b]))
        a_items = cached_a.get("items", []) if cached_a else []
        b_items = cached_b.get("items", []) if cached_b else []
        a_source_ids = {i.get("sourceId") for i in a_items if isinstance(i, dict)}
        b_source_ids = {i.get("sourceId") for i in b_items if isinstance(i, dict)}
        print(f"  cached_a sources={a_source_ids}, cached_b sources={b_source_ids}")
        if a_source_ids and b_source_ids and a_source_ids == b_source_ids:
            print("  WARNING: query cache scopes appear merged")
        else:
            print("  OK: query cache scopes isolated")
    else:
        print("\n[3] SKIP: not enough non-official sources for scope isolation")

    # ------------------------------------------------------------------
    # 4. History reconstruction
    # ------------------------------------------------------------------
    print("\n[4] History reconstruction after memory drop")
    hist_job = coordinator.submit("诡秘之主", page=1, source_ids=[enabled_non_official[0]], allow_cache=False) if enabled_non_official else None
    if hist_job:
        await _await_job(hist_job, timeout=30.0)
        original_id = hist_job.job_id
        original_items = [i.get("name") for i in (hist_job.result or {}).get("items", []) if isinstance(i, dict)]
        print(f"  original job {original_id} items={original_items}")
        coordinator._jobs.clear()
        coordinator._jobs_by_key.clear()
        coordinator._completed_jobs.clear()
        loaded = coordinator.get_job(original_id)
        loaded_items = [i.get("name") for i in (loaded.result or {}).get("items", []) if isinstance(i, dict)]
        print(f"  loaded job {loaded.job_id} items={loaded_items}")
        if original_items == loaded_items:
            print("  OK: loaded job matches original result")
        else:
            print(f"  WARNING: loaded result differs (original={original_items}, loaded={loaded_items})")
    else:
        print("  SKIP: no source available")

    # ------------------------------------------------------------------
    # 5. Cache fallback scope correctness (Catalog path)
    # ------------------------------------------------------------------
    print("\n[5] Catalog cache fallback scope")
    from app.services.catalog import Catalog

    catalog = Catalog()
    # Default scope fallback should hit the default search_query_cache entry.
    default_cached = catalog._merge_search_cache_fallback(
        {"items": [], "debug": {"errors": [{"sourceId": "dummy", "code": "TEST_ERROR"}]}},
        "诡秘之主",
        1,
        None,
    )
    print(f"  default scope fallback returned items={len(default_cached.get('items', []))}")
    # Explicit scope fallback should not accidentally hit default cache.
    explicit_cached = catalog._merge_search_cache_fallback(
        {"items": [], "debug": {"errors": [{"sourceId": "dummy", "code": "TEST_ERROR"}]}},
        "诡秘之主",
        1,
        [enabled_non_official[0]] if enabled_non_official else None,
    )
    print(f"  explicit scope fallback returned items={len(explicit_cached.get('items', []))}")

    # ------------------------------------------------------------------
    # 6. Stage routing summary across all jobs above
    # ------------------------------------------------------------------
    print("\n[6] Stage routing / access path summary")
    for label, job in [
        ("default", default_job),
        ("official", official_job if explicit_official else None),
        ("scope_a", ja if enabled_non_official else None),
        ("scope_b", jb if enabled_non_official else None),
    ]:
        if job is None:
            continue
        summary = _summarize_job(job)
        print(f"  {label}: stages={summary['stages']}, elapsed={summary['elapsed_ms']}ms")

    print("\n" + ("Real-source validation completed." if ok else "Real-source validation completed with warnings."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
