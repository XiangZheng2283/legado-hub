"""逐个书源调试脚本。

用法:
    cd backend
    python scripts/test_sources.py --keyword "剑宗外门"
    python scripts/test_sources.py --keyword "谁让他修仙的！"
    python scripts/test_sources.py --keyword "都重生了谁谈恋爱啊"
    python scripts/test_sources.py --keyword "剑宗外门" --source 69shuba_com
"""

import asyncio
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.source_plugins.scheduler import PluginScheduler

TEST_KEYWORDS = ["剑宗外门", "谁让他修仙的！", "都重生了谁谈恋爱啊"]


async def test_source_search(scheduler, keyword: str, source_id: str | None = None):
    plugins = scheduler._enabled_plugins()
    if source_id:
        plugins = [p for p in plugins if p.metadata.id == source_id]

    results = []
    for plugin in plugins:
        sid = plugin.metadata.id
        name = plugin.metadata.name
        if "search" not in plugin.capabilities:
            results.append({"sourceId": sid, "name": name, "status": "skipped", "reason": "no search capability"})
            continue

        ctx = scheduler._make_ctx(sid)
        source_timeout = scheduler.search_timeout_for_plugin(plugin)
        t0 = time.perf_counter()
        try:
            raw_items = await asyncio.wait_for(
                plugin.source.search(ctx, keyword, 1),
                timeout=source_timeout,
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)
            items = []
            for item in raw_items or []:
                if isinstance(item, dict):
                    item.setdefault("sourceId", sid)
                    item.setdefault("sourceName", name)
                    items.append(item)
            results.append({
                "sourceId": sid,
                "name": name,
                "status": "success",
                "itemCount": len(items),
                "latencyMs": latency_ms,
                "items": [{"name": i.get("name"), "author": i.get("author"), "bookUrl": i.get("bookUrl")} for i in items[:3]],
            })
        except asyncio.TimeoutError:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            results.append({"sourceId": sid, "name": name, "status": "timeout", "latencyMs": latency_ms})
        except Exception as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            results.append({"sourceId": sid, "name": name, "status": "error", "error": str(exc), "latencyMs": latency_ms})
        finally:
            await ctx._fetcher.close()

    return results


def print_results(results: list[dict]):
    success = [r for r in results if r["status"] == "success" and r.get("itemCount", 0) > 0]
    empty = [r for r in results if r["status"] == "success" and r.get("itemCount", 0) == 0]
    timeout = [r for r in results if r["status"] == "timeout"]
    error = [r for r in results if r["status"] == "error"]
    skipped = [r for r in results if r["status"] == "skipped"]

    print(f"\n{'='*60}")
    print(f"有结果: {len(success)} | 无结果: {len(empty)} | 超时: {len(timeout)} | 错误: {len(error)} | 跳过: {len(skipped)}")
    print(f"{'='*60}\n")

    for r in success:
        print(f"[OK] {r['name']} ({r['sourceId']}) - {r['itemCount']}条结果, {r['latencyMs']}ms")
        for item in r.get("items", []):
            print(f"   -> {item.get('name')} | {item.get('author')} | {item.get('bookUrl', '')[:60]}")

    for r in empty:
        print(f"[EMPTY] {r['name']} ({r['sourceId']}) - 无结果, {r['latencyMs']}ms")

    for r in timeout:
        print(f"[TIMEOUT] {r['name']} ({r['sourceId']}) - 超时, {r['latencyMs']}ms")

    for r in error:
        print(f"[ERROR] {r['name']} ({r['sourceId']}) - 错误: {r['error']}, {r['latencyMs']}ms")

    for r in skipped:
        print(f"[SKIP] {r['name']} ({r['sourceId']}) - 跳过: {r['reason']}")


async def main():
    parser = argparse.ArgumentParser(description="逐个书源调试")
    parser.add_argument("--keyword", type=str, help="搜索关键词")
    parser.add_argument("--source", type=str, help="指定书源ID")
    parser.add_argument("--all", action="store_true", help="测试全部3本小说")
    args = parser.parse_args()

    scheduler = PluginScheduler()
    scheduler.reload()

    keywords = TEST_KEYWORDS if args.all else [args.keyword or TEST_KEYWORDS[0]]

    for keyword in keywords:
        print(f"\n[测试关键词] {keyword}")
        results = await test_source_search(scheduler, keyword, args.source)
        print_results(results)


if __name__ == "__main__":
    asyncio.run(main())
