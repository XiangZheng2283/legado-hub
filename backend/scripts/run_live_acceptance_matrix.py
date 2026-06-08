"""Run ranked live acceptance checks for source plugins.

The acceptance path is:
explore groups -> explore items -> detail -> toc -> chapter ->
search by the ranked book title -> detail/toc/chapter again.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import SOURCE_POOL_CONFIG_PATH
from app.services.browser_challenge import BrowserChallengeService
from app.services.browser_helper import BrowserHelperService
from app.services.live_acceptance import LiveAcceptanceService
from app.services.plugin_auth_repository import PluginAuthRepository
from app.source_plugins.scheduler import PluginScheduler


def _load_config() -> dict[str, Any]:
    if not SOURCE_POOL_CONFIG_PATH.exists():
        return {}
    return json.loads(SOURCE_POOL_CONFIG_PATH.read_text(encoding="utf-8"))


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "pluginId": result.get("pluginId", ""),
        "status": result.get("status", ""),
        "passed": bool(result.get("passed")),
        "exploreName": result.get("explore", {}).get("selected", {}).get("name", ""),
        "exploreContentLength": result.get("explore", {}).get("contentLength", 0),
        "searchCount": result.get("search", {}).get("count", 0),
        "selectedName": result.get("selectedCandidate", {}).get("name", ""),
        "tocCount": result.get("toc", {}).get("count", 0),
        "chapterContentLength": result.get("chapter", {}).get("contentLength", 0),
        "diagnostics": [
            {
                "stage": item.get("stage", ""),
                "code": item.get("code", ""),
                "message": item.get("message", ""),
            }
            for item in result.get("diagnostics", [])
        ],
        "browserChallenges": [
            {
                "stage": item.get("stage", ""),
                "reason": item.get("reason", ""),
                "openUrl": item.get("openUrl", ""),
            }
            for item in result.get("browserChallenges", [])
        ],
    }


def parse_cookie_header(header: str) -> dict[str, str]:
    """Parse a browser Cookie header into a simple name/value jar."""
    jar: dict[str, str] = {}
    for part in (header or "").split(";"):
        if "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if name:
            jar[name] = value
    return jar


def resolve_cookie_header(
    *,
    cookie_header: str = "",
    cookie_header_env: str = "",
    cookie_header_file: str = "",
) -> str:
    """Resolve a Cookie header from direct, environment, or file input."""
    sources = [bool(cookie_header), bool(cookie_header_env), bool(cookie_header_file)]
    if sum(1 for item in sources if item) > 1:
        raise ValueError("use only one of --cookie-header, --cookie-header-env, or --cookie-header-file")
    if cookie_header:
        return cookie_header
    if cookie_header_env:
        value = os.environ.get(cookie_header_env, "")
        if not value:
            raise ValueError(f"environment variable is empty or missing: {cookie_header_env}")
        return value
    if cookie_header_file:
        path = Path(cookie_header_file)
        if not path.exists():
            raise ValueError(f"cookie header file does not exist: {cookie_header_file}")
        return path.read_text(encoding="utf-8").strip()
    return ""


def cookie_domains_for_plugin(scheduler: PluginScheduler, plugin_id: str, explicit_domains: list[str] | None = None) -> list[str]:
    """Resolve domains where a supplied Cookie header should be saved."""
    if explicit_domains:
        return sorted({domain.strip().lstrip(".") for domain in explicit_domains if domain.strip()})
    plugin = scheduler._plugins.get(plugin_id)
    if not plugin:
        return []
    domains = set(plugin.metadata.auth.get("cookieDomains", []) or [])
    domains.update(plugin.metadata.domains or [])
    for profile in plugin.metadata.domain_profiles:
        domains.update(profile.get("domains", []) or [])
    return sorted(domain.strip().lstrip(".") for domain in domains if domain)


def clear_plugin_cookies(plugin_ids: list[str], repository: PluginAuthRepository | None = None) -> dict[str, Any]:
    """Clear persisted cookies for selected plugins before running checks."""
    if not plugin_ids:
        raise ValueError("--clear-cookies requires at least one --plugin")
    repository = repository or PluginAuthRepository()
    for plugin_id in plugin_ids:
        repository.clear_cookies(plugin_id)
    return {"clearedPlugins": plugin_ids}


def normalize_playwright_cookie_file(path: str) -> dict[str, dict[str, str]]:
    """Load Playwright/browser-helper cookies into a domain-keyed cookie map."""
    cookie_path = Path(path)
    if not cookie_path.exists():
        raise ValueError(f"browser cookie JSON file does not exist: {path}")
    try:
        data = json.loads(cookie_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"browser cookie JSON file is invalid: {path}") from exc
    cookies = data.get("cookies", data) if isinstance(data, dict) else data
    if not isinstance(cookies, list):
        raise ValueError("browser cookie JSON must be a Playwright cookie array or helper payload")
    normalized: dict[str, dict[str, str]] = {}
    for item in cookies:
        if not isinstance(item, dict):
            continue
        domain = str(item.get("domain", "")).strip().lstrip(".")
        name = str(item.get("name", "")).strip()
        value = str(item.get("value", ""))
        if domain and name:
            normalized.setdefault(domain, {})[name] = value
    if not normalized:
        raise ValueError("browser cookie JSON did not contain any domain cookies")
    return normalized


def apply_browser_cookie_json(
    *,
    plugin_ids: list[str],
    cookie_json_path: str,
    repository: PluginAuthRepository | None = None,
) -> dict[str, Any]:
    """Persist Playwright/browser-helper cookies for the selected plugins."""
    if not plugin_ids:
        raise ValueError("--browser-cookie-json requires at least one --plugin")
    normalized = normalize_playwright_cookie_file(cookie_json_path)
    repository = repository or PluginAuthRepository()
    for plugin_id in plugin_ids:
        current = repository.get_cookies(plugin_id)
        for domain, jar in normalized.items():
            current.setdefault(domain, {}).update(jar)
        repository.set_cookies(plugin_id, current)
    return {
        "cookieNames": sorted({name for jar in normalized.values() for name in jar}),
        "appliedDomains": {plugin_id: sorted(normalized.keys()) for plugin_id in plugin_ids},
        "sourceFile": cookie_json_path,
    }


def apply_cookie_header(
    *,
    scheduler: PluginScheduler,
    plugin_ids: list[str],
    cookie_header: str,
    cookie_domains: list[str] | None = None,
    repository: PluginAuthRepository | None = None,
) -> dict[str, Any]:
    """Persist a supplied browser Cookie header for the selected plugins."""
    jar = parse_cookie_header(cookie_header)
    if not jar:
        raise ValueError("--cookie-header did not contain any name=value cookies")
    if not plugin_ids:
        raise ValueError("--cookie-header requires at least one --plugin")
    repository = repository or PluginAuthRepository()
    applied: dict[str, list[str]] = {}
    for plugin_id in plugin_ids:
        domains = cookie_domains_for_plugin(scheduler, plugin_id, cookie_domains)
        if not domains:
            raise ValueError(f"cannot resolve cookie domains for plugin: {plugin_id}")
        current = repository.get_cookies(plugin_id)
        for domain in domains:
            current.setdefault(domain, {}).update(jar)
        repository.set_cookies(plugin_id, current)
        applied[plugin_id] = domains
    return {"cookieNames": sorted(jar.keys()), "appliedDomains": applied}


def open_browser_challenges(
    *,
    scheduler: PluginScheduler,
    plugin_ids: list[str],
    stage: str = "runtime",
    challenge_service: BrowserChallengeService | None = None,
    helper_service: BrowserHelperService | None = None,
) -> list[dict[str, Any]]:
    """Create challenge sessions and open visible browser helpers."""
    if not plugin_ids:
        raise ValueError("--open-browser-challenge requires at least one --plugin")
    challenge_service = challenge_service or BrowserChallengeService()
    helper_service = helper_service or BrowserHelperService()
    results = []
    for plugin_id in plugin_ids:
        plugin = scheduler._plugins.get(plugin_id)
        if not plugin:
            raise ValueError(f"plugin not found: {plugin_id}")
        session = challenge_service.create_for_plugin(plugin, stage=stage, reason="BROWSER_REQUIRED")
        helper = helper_service.start(session)
        if helper.get("started"):
            challenge_service.record_browser_helper(session["sessionId"], helper)
        results.append({
            "pluginId": plugin_id,
            "sessionId": session["sessionId"],
            "openUrl": session["openUrl"],
            "cookieDomains": session["cookieDomains"],
            "helper": helper,
        })
    return results


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    scheduler = PluginScheduler(config=_load_config())
    service = LiveAcceptanceService(scheduler=scheduler)
    plugin_ids = args.plugin or sorted(scheduler._plugins)
    opened_challenges = None
    cookie_clear = None
    cookie_injection = None
    browser_cookie_import = None
    if args.open_browser_challenge:
        opened_challenges = open_browser_challenges(
            scheduler=scheduler,
            plugin_ids=args.plugin or [],
            stage=args.challenge_stage,
        )
    if args.clear_cookies:
        cookie_clear = clear_plugin_cookies(args.plugin or [])
    cookie_header = resolve_cookie_header(
        cookie_header=args.cookie_header,
        cookie_header_env=args.cookie_header_env,
        cookie_header_file=args.cookie_header_file,
    )
    if cookie_header:
        cookie_injection = apply_cookie_header(
            scheduler=scheduler,
            plugin_ids=args.plugin or [],
            cookie_header=cookie_header,
            cookie_domains=args.cookie_domain or None,
        )
    if args.browser_cookie_json:
        browser_cookie_import = apply_browser_cookie_json(
            plugin_ids=args.plugin or [],
            cookie_json_path=args.browser_cookie_json,
        )
    items = []
    for plugin_id in plugin_ids:
        result = await service.run_plugin_live_check(
            plugin_id,
            keyword=args.keyword,
            persist=args.persist,
        )
        summary = _summary(result)
        items.append(summary)
        print(json.dumps(summary, ensure_ascii=False))
    payload = {
        "keyword": args.keyword,
        "total": len(items),
        "passed": sum(1 for item in items if item["passed"]),
        "failed": sum(1 for item in items if not item["passed"]),
        "items": items,
    }
    if cookie_clear:
        payload["cookieClear"] = cookie_clear
    if cookie_injection:
        payload["cookieInjection"] = cookie_injection
    if browser_cookie_import:
        payload["browserCookieImport"] = browser_cookie_import
    if opened_challenges:
        payload["openedBrowserChallenges"] = opened_challenges
    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run source plugin live acceptance matrix.")
    parser.add_argument("--keyword", default="剑宗外门", help="Fallback keyword; explore title is used for search-loop checks.")
    parser.add_argument("--plugin", action="append", help="Plugin id to check. Can be supplied multiple times.")
    parser.add_argument("--persist", action="store_true", help="Persist live check results to the repository.")
    parser.add_argument("--json-out", default="", help="Optional output JSON path.")
    parser.add_argument("--cookie-header", default="", help="Temporary browser Cookie header to save before running selected plugin checks.")
    parser.add_argument("--cookie-header-env", default="", help="Environment variable containing a browser Cookie header.")
    parser.add_argument("--cookie-header-file", default="", help="UTF-8 text file containing a browser Cookie header.")
    parser.add_argument("--cookie-domain", action="append", help="Cookie domain to use with --cookie-header. Can be supplied multiple times.")
    parser.add_argument("--browser-cookie-json", default="", help="Playwright/browser-helper cookie JSON file to import before checks.")
    parser.add_argument("--clear-cookies", action="store_true", help="Clear persisted cookies for selected plugins before running checks.")
    parser.add_argument("--open-browser-challenge", action="store_true", help="Open a visible browser helper for selected plugins before checks.")
    parser.add_argument("--challenge-stage", default="runtime", help="Stage label used when creating browser helper sessions.")
    args = parser.parse_args()
    payload = asyncio.run(_run(args))
    print("SUMMARY")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
