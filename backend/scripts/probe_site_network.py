"""Probe browser runtime network requests for a source page.

Examples:
    python backend/scripts/probe_site_network.py --url "https://www.xbiqugu.com/wapbook/6425.html"
    python backend/scripts/probe_site_network.py --url "https://m.biquge365.net/shu/679551/" --contains api ajax chapter
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


DEFAULT_HINTS = [
    "api",
    "ajax",
    "chapter",
    "chapterlist",
    "chapters",
    "content",
    "reader",
    "read",
    "book",
    "novel",
    "txt",
    "page",
]


def _json_default(value: Any) -> str:
    return str(value)


def _lower_headers(headers: dict[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    return {str(key).lower(): str(value) for key, value in headers.items()}


def _content_type(headers: dict[str, str]) -> str:
    return headers.get("content-type", "")


def _looks_textual(content_type: str) -> bool:
    value = content_type.lower()
    return any(
        token in value
        for token in [
            "text/",
            "json",
            "javascript",
            "xml",
            "html",
            "x-www-form-urlencoded",
        ]
    )


def _matched_hints(url: str, content_type: str, hints: list[str]) -> list[str]:
    haystack = f"{url}\n{content_type}".lower()
    return [hint for hint in hints if hint.lower() in haystack]


def _safe_query(url: str) -> dict[str, str]:
    try:
        return dict(parse_qsl(urlparse(url).query, keep_blank_values=True))
    except Exception:
        return {}


def _classify(entry: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    url = str(entry.get("url", "")).lower()
    resource_type = str(entry.get("resourceType", "")).lower()
    content_type = str(entry.get("contentType", "")).lower()
    sample = str(entry.get("bodySample", "")).lower()
    if resource_type in {"xhr", "fetch"}:
        labels.append("runtime-api")
    if "json" in content_type or sample[:1] in {"{", "["}:
        labels.append("json")
    if any(token in url for token in ["chapterlist", "chapters", "catalog", "mulu"]):
        labels.append("catalog-candidate")
    if any(token in url for token in ["content", "reader", "read", "chapter"]):
        labels.append("content-candidate")
    if "api" in url or "ajax" in url:
        labels.append("api-candidate")
    if "html" in content_type and resource_type == "document":
        labels.append("document")
    return sorted(set(labels))


async def _read_body_sample(response: Any, limit: int) -> tuple[str, int | None, str]:
    if limit <= 0:
        return "", None, ""
    headers = _lower_headers(getattr(response, "headers", {}) or {})
    content_type = _content_type(headers)
    if not _looks_textual(content_type):
        return "", None, "non-textual"
    try:
        body = await response.body()
    except PlaywrightError as exc:
        return "", None, f"body-unavailable: {exc}"
    except Exception as exc:
        return "", None, f"body-error: {exc}"
    size = len(body)
    for encoding in ["utf-8", "gb18030", "gbk", "big5"]:
        try:
            text = body.decode(encoding)
            break
        except UnicodeDecodeError:
            text = ""
    if not text:
        text = body.decode("utf-8", errors="replace")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit], size, ""


async def probe(args: argparse.Namespace) -> dict[str, Any]:
    hints = args.contains or DEFAULT_HINTS
    started = time.perf_counter()
    request_index: dict[Any, dict[str, Any]] = {}
    entries: list[dict[str, Any]] = []
    console_messages: list[dict[str, str]] = []
    page_errors: list[str] = []
    response_tasks: list[asyncio.Task] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=not args.headful)
        context_kwargs: dict[str, Any] = {
            "user_agent": args.user_agent,
            "ignore_https_errors": True,
        }
        if args.har:
            context_kwargs.update({
                "record_har_path": str(Path(args.har).resolve()),
                "record_har_content": "omit" if args.har_omit_content else "embed",
            })
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()
        page.set_default_timeout(args.timeout_ms)

        def on_request(request: Any) -> None:
            post_data = ""
            try:
                post_data = request.post_data or ""
            except Exception:
                post_data = ""
            entry = {
                "url": request.url,
                "method": request.method,
                "resourceType": request.resource_type,
                "requestHeaders": dict(request.headers or {}),
                "postDataSample": post_data[: args.post_data_limit],
                "status": 0,
                "responseHeaders": {},
                "contentType": "",
                "bodySize": None,
                "bodySample": "",
                "bodyError": "",
                "matchedHints": [],
                "labels": [],
                "query": _safe_query(request.url),
                "durationMs": None,
                "_startedAt": time.perf_counter(),
            }
            request_index[request] = entry
            entries.append(entry)

        async def on_response(response: Any) -> None:
            request = response.request
            entry = request_index.get(request)
            if entry is None:
                entry = {
                    "url": response.url,
                    "method": getattr(request, "method", "GET"),
                    "resourceType": getattr(request, "resource_type", ""),
                    "requestHeaders": {},
                    "postDataSample": "",
                    "status": 0,
                    "responseHeaders": {},
                    "contentType": "",
                    "bodySize": None,
                    "bodySample": "",
                    "bodyError": "",
                    "matchedHints": [],
                    "labels": [],
                    "query": _safe_query(response.url),
                    "_startedAt": time.perf_counter(),
                }
                entries.append(entry)
            headers = _lower_headers(response.headers or {})
            entry["status"] = response.status
            entry["responseHeaders"] = headers
            entry["contentType"] = _content_type(headers)
            entry["matchedHints"] = _matched_hints(entry["url"], entry["contentType"], hints)
            entry["durationMs"] = int((time.perf_counter() - entry.get("_startedAt", time.perf_counter())) * 1000)
            if args.body_sample_limit > 0 and (
                args.include_all_bodies
                or entry["resourceType"] in {"xhr", "fetch", "document"}
                or entry["matchedHints"]
            ):
                sample, size, body_error = await _read_body_sample(response, args.body_sample_limit)
                entry["bodySample"] = sample
                entry["bodySize"] = size
                entry["bodyError"] = body_error
            entry["labels"] = _classify(entry)

        def schedule_response_capture(response: Any) -> None:
            response_tasks.append(asyncio.create_task(on_response(response)))

        page.on("request", on_request)
        page.on("response", schedule_response_capture)
        page.on("console", lambda message: console_messages.append({"type": message.type, "text": message.text[:500]}))
        page.on("pageerror", lambda error: page_errors.append(str(error)[:1000]))

        navigation: dict[str, Any] = {"ok": False, "status": 0, "finalUrl": "", "error": ""}
        try:
            response = await page.goto(args.url, wait_until=args.wait_until, timeout=args.timeout_ms)
            navigation["ok"] = response is None or response.ok
            navigation["status"] = response.status if response else 0
            navigation["finalUrl"] = page.url
        except PlaywrightTimeoutError as exc:
            navigation["error"] = f"timeout: {exc}"
        except Exception as exc:
            navigation["error"] = f"{type(exc).__name__}: {exc}"

        if args.wait_ms > 0:
            await page.wait_for_timeout(args.wait_ms)

        if args.scroll:
            await page.evaluate(
                """async () => {
                    for (let y = 0; y < document.body.scrollHeight; y += Math.max(400, window.innerHeight || 800)) {
                        window.scrollTo(0, y);
                        await new Promise(resolve => setTimeout(resolve, 250));
                    }
                    window.scrollTo(0, 0);
                }"""
            )
            if args.wait_after_scroll_ms > 0:
                await page.wait_for_timeout(args.wait_after_scroll_ms)

        title = ""
        try:
            title = await page.title()
        except Exception:
            title = ""
        html_length = 0
        try:
            html_length = len(await page.content())
        except Exception:
            html_length = 0

        if response_tasks:
            await asyncio.gather(*response_tasks, return_exceptions=True)

        await context.close()
        await browser.close()

    for entry in entries:
        entry.pop("_startedAt", None)

    filtered_entries = entries
    if args.only_interesting:
        filtered_entries = [
            entry
            for entry in entries
            if entry.get("resourceType") in {"xhr", "fetch"}
            or entry.get("matchedHints")
            or entry.get("labels")
        ]

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    summary = {
        "url": args.url,
        "navigation": navigation,
        "title": title,
        "htmlLength": html_length,
        "elapsedMs": elapsed_ms,
        "requestCount": len(entries),
        "interestingCount": len(filtered_entries),
        "resourceTypeCounts": {},
        "labelCounts": {},
    }
    for entry in entries:
        resource_type = entry.get("resourceType", "") or "unknown"
        summary["resourceTypeCounts"][resource_type] = summary["resourceTypeCounts"].get(resource_type, 0) + 1
        for label in entry.get("labels", []):
            summary["labelCounts"][label] = summary["labelCounts"].get(label, 0) + 1

    return {
        "summary": summary,
        "entries": filtered_entries,
        "console": console_messages[: args.console_limit],
        "pageErrors": page_errors,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe browser network requests for a page")
    parser.add_argument("--url", required=True, help="Target page URL")
    parser.add_argument("--out", default="", help="Write JSON result to this path")
    parser.add_argument("--har", default="", help="Optional HAR output path")
    parser.add_argument("--har-omit-content", action="store_true", help="Do not embed response bodies in HAR")
    parser.add_argument("--contains", nargs="*", default=None, help="Hint keywords for interesting URLs/content-types")
    parser.add_argument("--only-interesting", action="store_true", help="Only output xhr/fetch or hint-matched entries")
    parser.add_argument("--include-all-bodies", action="store_true", help="Try reading body samples for all textual responses")
    parser.add_argument("--body-sample-limit", type=int, default=800, help="Max chars of response body sample per entry; 0 disables")
    parser.add_argument("--post-data-limit", type=int, default=500, help="Max chars of request post data sample")
    parser.add_argument("--console-limit", type=int, default=50, help="Max console messages in output")
    parser.add_argument("--timeout-ms", type=int, default=45000, help="Navigation/action timeout")
    parser.add_argument("--wait-ms", type=int, default=3000, help="Extra wait after initial load")
    parser.add_argument("--wait-after-scroll-ms", type=int, default=1500, help="Extra wait after optional scroll")
    parser.add_argument("--wait-until", default="domcontentloaded", choices=["commit", "domcontentloaded", "load", "networkidle"])
    parser.add_argument("--scroll", action="store_true", help="Scroll page to trigger lazy-loaded requests")
    parser.add_argument("--headful", action="store_true", help="Show browser window")
    parser.add_argument(
        "--user-agent",
        default=(
            "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
        ),
        help="User-Agent used by the browser context",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        result = asyncio.run(probe(args))
    except PlaywrightError as exc:
        message = str(exc)
        if "Executable doesn't exist" in message or "playwright install" in message:
            print("ERROR: Playwright Chromium is not installed. Run: python -m playwright install chromium", file=sys.stderr)
            return 2
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(result, ensure_ascii=False, indent=2, default=_json_default)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"Wrote {out_path}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
