"""Run bounded live checks for all enabled third-party source plugins."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import yaml

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.live_acceptance import LiveAcceptanceService
from app.source_plugins.scheduler import get_plugin_scheduler, shutdown_plugin_scheduler


THIRDPARTY_ROOT = BACKEND_ROOT.parent / "plugins" / "sources" / "thirdparty"
SOURCE_REFS_ROOT = BACKEND_ROOT / "data" / "library_private"


def _probe_keyword(plugin_id: str, override: str | None) -> str:
    if override:
        return override
    smoke_path = THIRDPARTY_ROOT / plugin_id / "smoke" / "smoke.yaml"
    if smoke_path.is_file():
        smoke = yaml.safe_load(smoke_path.read_text(encoding="utf-8")) or {}
        keyword = str(smoke.get("keyword") or "").strip()
        if keyword:
            return keyword
    return "天命之上"


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    diagnostic = (result.get("diagnostics") or [{}])[0]
    return {
        "id": result.get("pluginId", ""),
        "status": result.get("status", "failed"),
        "elapsedMs": (result.get("timings") or {}).get("elapsedMs", 0),
        "searchCount": (result.get("search") or {}).get("count", 0),
        "tocCount": (result.get("toc") or {}).get("count", 0),
        "contentLength": (result.get("chapter") or {}).get("contentLength", 0),
        "chapterTitle": (result.get("chapter") or {}).get("title", ""),
        "contentPreview": (result.get("chapter") or {}).get("preview", ""),
        "selected": {
            "name": (result.get("selectedCandidate") or {}).get("name", ""),
            "author": (result.get("selectedCandidate") or {}).get("author", ""),
            "bookUrl": (result.get("selectedCandidate") or {}).get("bookUrl", ""),
        },
        "detail": {
            "name": (result.get("detail") or {}).get("name", ""),
            "tocUrl": (result.get("detail") or {}).get("tocUrl", ""),
        },
        "issue": {
            "stage": diagnostic.get("stage", ""),
            "code": diagnostic.get("code", ""),
            "message": diagnostic.get("message", ""),
        },
    }


async def _probe_from_explore(
    service: LiveAcceptanceService,
    scheduler,
    plugin_id: str,
    chapter_index: int,
) -> dict[str, Any] | None:
    plugin = scheduler._plugins[plugin_id]
    source = plugin.source
    if not callable(getattr(source, "explore_groups", None)) or not callable(getattr(source, "explore", None)):
        return None
    ctx = scheduler._make_ctx(plugin_id)
    timeout = service._timeout_for_plugin(plugin)
    try:
        groups = await service._call_plugin(plugin, lambda: source.explore_groups(ctx), timeout=timeout)
        if not groups:
            return None
        group_id = (groups[0] or {}).get("groupId", "")
        items = await service._call_plugin(plugin, lambda: source.explore(ctx, group_id, 1), timeout=timeout)
        candidate = next((item for item in items or [] if isinstance(item, dict)), None)
        if not candidate:
            return None
        detail, toc_items, chapter = await service._read_candidate(plugin, ctx, candidate, chapter_index, timeout)
        return {
            "status": "passed" if len(chapter.get("content", "") or "") > 500 else "failed",
            "candidate": {"name": candidate.get("name", ""), "bookUrl": candidate.get("bookUrl", "")},
            "detail": {"name": detail.get("name", ""), "tocUrl": detail.get("tocUrl", "")},
            "tocCount": len(toc_items),
            "contentLength": len(chapter.get("content", "") or ""),
        }
    finally:
        await ctx._fetcher.close()


def _local_candidate(plugin_id: str) -> dict[str, Any] | None:
    for path in SOURCE_REFS_ROOT.glob("*/source_refs.json"):
        try:
            refs = json.loads(path.read_text(encoding="utf-8")).get("sourceMapRefs") or []
        except (OSError, ValueError):
            continue
        for ref in refs:
            if ref.get("sourceId") == plugin_id and ref.get("bookUrl"):
                return {
                    "sourceId": plugin_id,
                    "name": path.parent.name.rsplit("_", 1)[0],
                    "bookUrl": ref["bookUrl"],
                    "tocUrl": ref.get("tocUrl", ""),
                }
    return None


async def _probe_candidate(
    service: LiveAcceptanceService,
    scheduler,
    plugin_id: str,
    candidate: dict[str, Any],
    chapter_index: int,
) -> dict[str, Any]:
    plugin = scheduler._plugins[plugin_id]
    ctx = scheduler._make_ctx(plugin_id)
    timeout = service._timeout_for_plugin(plugin)
    try:
        detail, toc_items, chapter = await service._read_candidate(plugin, ctx, candidate, chapter_index, timeout)
        return {
            "status": "passed" if len(chapter.get("content", "") or "") > 500 else "failed",
            "candidate": {"name": candidate.get("name", ""), "bookUrl": candidate.get("bookUrl", "")},
            "detail": {"name": detail.get("name", ""), "tocUrl": detail.get("tocUrl", "")},
            "tocCount": len(toc_items),
            "contentLength": len(chapter.get("content", "") or ""),
            "chapterTitle": chapter.get("title", ""),
            "contentPreview": (chapter.get("content", "") or "")[:300],
        }
    finally:
        await ctx._fetcher.close()


async def _run(args: argparse.Namespace) -> list[dict[str, Any]]:
    scheduler = get_plugin_scheduler(reload=True)
    scheduler.config["source_timeout_seconds"] = args.operation_timeout
    scheduler.config["source_hard_timeout_seconds"] = args.operation_timeout
    service = LiveAcceptanceService(scheduler=scheduler)
    plugin_ids = args.plugin or sorted(
        plugin_id
        for plugin_id, plugin in scheduler._plugins.items()
        if not plugin.metadata.is_official_source() and plugin.metadata.enabled
    )
    results: list[dict[str, Any]] = []
    try:
        for plugin_id in plugin_ids:
            keyword = _probe_keyword(plugin_id, args.keyword)
            try:
                result = await asyncio.wait_for(
                    service.run_plugin_live_check(
                        plugin_id,
                        keyword=keyword,
                        chapter_index=args.chapter_index,
                        persist=False,
                    ),
                    timeout=args.timeout,
                )
                summary = _summary(result)
                if summary["status"] != "passed":
                    try:
                        fallback = await asyncio.wait_for(
                            _probe_from_explore(service, scheduler, plugin_id, args.chapter_index),
                            timeout=args.timeout,
                        )
                    except Exception as exc:
                        fallback = {"status": "failed", "message": str(exc)}
                    if fallback:
                        summary["exploreRead"] = fallback
                        if fallback.get("status") == "passed":
                            summary["status"] = "partial"
                if summary["status"] not in {"passed", "partial"} and args.use_local_source_refs:
                    candidate = _local_candidate(plugin_id)
                    if candidate:
                        try:
                            local_read = await asyncio.wait_for(
                                _probe_candidate(service, scheduler, plugin_id, candidate, args.chapter_index),
                                timeout=args.timeout,
                            )
                        except Exception as exc:
                            local_read = {"status": "failed", "message": str(exc)}
                        summary["localRead"] = local_read
                        if local_read.get("status") == "passed":
                            summary["status"] = "partial"
            except asyncio.TimeoutError:
                summary = {
                    "id": plugin_id,
                    "status": "timeout",
                    "elapsedMs": int(args.timeout * 1000),
                    "searchCount": 0,
                    "tocCount": 0,
                    "contentLength": 0,
                    "issue": {"stage": "probe", "code": "timeout", "message": "probe timeout"},
                }
            except Exception as exc:
                summary = {
                    "id": plugin_id,
                    "status": "failed",
                    "elapsedMs": 0,
                    "searchCount": 0,
                    "tocCount": 0,
                    "contentLength": 0,
                    "issue": {"stage": "probe", "code": type(exc).__name__, "message": str(exc)},
                }
            results.append(summary)
            print(json.dumps(summary, ensure_ascii=True), flush=True)
            await asyncio.sleep(args.interval)
    finally:
        await shutdown_plugin_scheduler()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword", help="override every plugin's fixture keyword")
    parser.add_argument("--plugin", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=40.0)
    parser.add_argument("--operation-timeout", type=float, default=30.0)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--chapter-index", type=int, default=3)
    parser.add_argument("--use-local-source-refs", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    results = asyncio.run(_run(args))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
