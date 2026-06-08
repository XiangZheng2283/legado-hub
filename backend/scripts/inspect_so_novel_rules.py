"""Inspect and classify So Novel seed rules.

Produces a deterministic JSON summary for plugin conversion planning.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse


def load_json(path: str) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text)


def _make_id(url: str) -> str:
    domain = urlparse(url).netloc
    return re.sub(r"[^a-z0-9]", "_", domain).strip("_")


def inspect_rules(
    main_path: str,
    proxy_required_path: str | None = None,
    rate_limit_path: str | None = None,
    cloudflare_path: str | None = None,
) -> dict:
    main_rules = load_json(main_path)
    proxy_rules = load_json(proxy_required_path) if proxy_required_path else []
    rate_rules = load_json(rate_limit_path) if rate_limit_path else []
    cloudflare_rules = load_json(cloudflare_path) if cloudflare_path else []

    proxy_ids = {_make_id(r.get("url", "")) for r in proxy_rules}
    rate_ids = {_make_id(r.get("url", "")) for r in rate_rules}
    cloudflare_ids = {_make_id(r.get("url", "")) for r in cloudflare_rules}

    total = len(main_rules)
    search_capable = 0
    simple_candidates = []
    no_search = []

    for rule in main_rules:
        rid = _make_id(rule.get("url", ""))
        name = rule.get("name", "")
        has_search = bool(rule.get("search"))
        if has_search:
            search_capable += 1
        else:
            no_search.append(rid)

        is_cloudflare = rid in cloudflare_ids
        is_proxy = rid in proxy_ids
        is_rate = rid in rate_ids

        # Simple candidates exclude cloudflare-first entries
        if not is_cloudflare and has_search:
            simple_candidates.append({
                "id": rid,
                "name": name,
                "url": rule.get("url", ""),
                "proxyRequired": is_proxy,
                "rateLimited": is_rate,
            })

    return {
        "totalRules": total,
        "searchCapable": search_capable,
        "noSearch": no_search,
        "simpleCandidates": simple_candidates,
        "simpleCandidateCount": len(simple_candidates),
        "proxyRequiredIds": sorted(proxy_ids - {''}),
        "rateLimitIds": sorted(rate_ids - {''}),
        "cloudflareIds": sorted(cloudflare_ids - {''}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect So Novel seed rules")
    parser.add_argument("--main", required=True, help="Path to main.json")
    parser.add_argument("--proxy-required", help="Path to proxy-required.json")
    parser.add_argument("--rate-limit", help="Path to rate-limit.json")
    parser.add_argument("--cloudflare", help="Path to cloudflare.json")
    args = parser.parse_args()

    result = inspect_rules(
        main_path=args.main,
        proxy_required_path=args.proxy_required,
        rate_limit_path=args.rate_limit,
        cloudflare_path=args.cloudflare,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
