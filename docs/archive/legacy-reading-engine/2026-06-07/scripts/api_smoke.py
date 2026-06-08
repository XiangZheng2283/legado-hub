"""Read-only API smoke checks for a running LegadoHub server."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen


BASE = "http://127.0.0.1:8765"


def get(path: str) -> tuple[int, str, str]:
    with urlopen(BASE + path, timeout=30) as resp:
        return resp.status, resp.headers.get("content-type", ""), resp.read().decode("utf-8")


def post(path: str, payload: dict) -> tuple[int, str, str]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(BASE + path, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=30) as resp:
        return resp.status, resp.headers.get("content-type", ""), resp.read().decode("utf-8")


def check(desc: str, condition: bool, details: str = "") -> bool:
    print(f"{'[OK]' if condition else '[FAIL]'} {desc}{': ' + details if details else ''}")
    return condition


def expect_json_keys(desc: str, response: tuple[int, str, str], keys: list[str]) -> bool:
    status, _content_type, body = response
    if status != 200:
        return check(desc, False, f"status={status}")
    data = json.loads(body)
    missing = [key for key in keys if key not in data]
    return check(desc, not missing, f"missing={missing}" if missing else f"keys={','.join(keys)}")


def main() -> int:
    results = []

    print("\n=== Settings ===")
    results.append(expect_json_keys("Load settings", get("/api/admin/settings"), ["sourcePool", "ruleEngines", "sourceSubscriptions"]))

    print("\n=== Subscriptions ===")
    status, _ct, body = get("/api/admin/source-subscriptions")
    data = json.loads(body) if status == 200 else {}
    results.append(check("List subscriptions", status == 200 and isinstance(data.get("items"), list), f"items={len(data.get('items', []))}"))

    print("\n=== Sources ===")
    results.append(expect_json_keys("List sources", get("/api/admin/sources?enabled_only=true&limit=5"), ["items", "stats"]))

    print("\n=== Search Job ===")
    status, _ct, body = post("/api/admin/search-jobs", {"keyword": "test", "page": 1, "limit": 0})
    data = json.loads(body) if status == 200 else {}
    job_id = data.get("jobId", "")
    results.append(check("Create zero-source search job", status == 200 and bool(job_id), f"jobId={job_id}"))
    if job_id:
        results.append(expect_json_keys("Get search job", get(f"/api/admin/search-jobs/{job_id}"), ["jobId", "status"]))

    print("\n=== Explore / Books / Cache ===")
    results.append(expect_json_keys("List explore sources", get("/api/admin/explore/sources"), ["items"]))
    results.append(expect_json_keys("List books", get("/api/admin/books?limit=5"), ["items"]))
    results.append(expect_json_keys("Get cache stats", get("/api/admin/cache"), ["searchCache", "bookCache", "tocCache", "chapterCache"]))

    print("\n=== Verification ===")
    results.append(expect_json_keys("Run API verification", post("/api/admin/verification/run", {"category": "api"}), ["summary", "items"]))

    print("\n" + "=" * 40)
    print(f"Results: {sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
