"""Collect public book-source rule files into a by-site local archive.

This script keeps archived source objects close to their upstream shape:

- Legado book sources are written as JSON arrays under
  data/sources/raw/by-site/legado/<host>.json
- So Novel rules are written as JSON arrays under
  data/sources/raw/by-site/so-novel/<host>.json
- Non-site rule packs are written under data/sources/raw/rule-packs/
- Upstream list metadata is written under data/sources/raw/upstream-metadata/

The companion manifest records origins, counts, and sources that could not be
resolved into downloadable rule files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import time
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK_ROOT = Path(
    r"C:\Users\moo\Documents\Codex\2026-06-05\aoaostar-legado-https-github-com-aoaostar\work"
)
RAW_DIR = PROJECT_ROOT / "data" / "sources" / "raw"
LEGADO_BY_SITE_DIR = RAW_DIR / "by-site" / "legado"
SO_NOVEL_BY_SITE_DIR = RAW_DIR / "by-site" / "so-novel"
RULE_PACK_DIR = RAW_DIR / "rule-packs"
UPSTREAM_METADATA_DIR = RAW_DIR / "upstream-metadata"
MANIFEST_PATH = RAW_DIR / "manifest.json"

USER_AGENT = "LegadoHub-source-collector/0.1 (+local archive)"
YIOVE_API_BASE = "https://shuyuan-api.yiove.com"
YIOVE_2026_START = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
YIOVE_2027_START = datetime(2027, 1, 1, tzinfo=timezone.utc).timestamp()


@dataclass(frozen=True)
class JsonPayload:
    origin_id: str
    origin_label: str
    origin_path: str
    payload: Any


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--work-root",
        type=Path,
        default=DEFAULT_WORK_ROOT,
        help="Directory containing cloned upstream repositories.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove generated raw archive directories before collecting.",
    )
    args = parser.parse_args()

    if args.clean and RAW_DIR.exists():
        shutil.rmtree(RAW_DIR)

    for directory in (LEGADO_BY_SITE_DIR, SO_NOVEL_BY_SITE_DIR, RULE_PACK_DIR, UPSTREAM_METADATA_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "projectRoot": str(PROJECT_ROOT),
        "workRoot": str(args.work_root),
        "outputs": {
            "legadoBySite": str(LEGADO_BY_SITE_DIR.relative_to(PROJECT_ROOT)),
            "soNovelBySite": str(SO_NOVEL_BY_SITE_DIR.relative_to(PROJECT_ROOT)),
            "rulePacks": str(RULE_PACK_DIR.relative_to(PROJECT_ROOT)),
            "upstreamMetadata": str(UPSTREAM_METADATA_DIR.relative_to(PROJECT_ROOT)),
        },
        "sources": [],
        "files": [],
        "summary": {},
    }

    legado_payloads = collect_legado_payloads(args.work_root, manifest)
    so_novel_payloads = collect_so_novel_payloads(args.work_root, manifest)
    collect_rule_packs(args.work_root, manifest)
    probe_yiove(manifest)

    legado_groups, legado_sources = group_legado_sources(legado_payloads)
    so_novel_groups, so_novel_sources = group_so_novel_rules(so_novel_payloads)

    legado_file_count = write_grouped_files(
        LEGADO_BY_SITE_DIR,
        legado_groups,
        "legado-book-source",
        manifest,
        legado_sources,
    )
    so_novel_file_count = write_grouped_files(
        SO_NOVEL_BY_SITE_DIR,
        so_novel_groups,
        "so-novel-rule",
        manifest,
        so_novel_sources,
    )

    rule_pack_file_count = len(list(RULE_PACK_DIR.glob("*.json")))
    upstream_metadata_file_count = len(list(UPSTREAM_METADATA_DIR.glob("*.json")))
    manifest["summary"] = {
        "legadoSiteFiles": legado_file_count,
        "legadoSourceObjects": sum(len(items) for items in legado_groups.values()),
        "soNovelSiteFiles": so_novel_file_count,
        "soNovelRuleObjects": sum(len(items) for items in so_novel_groups.values()),
        "rulePackFiles": rule_pack_file_count,
        "upstreamMetadataFiles": upstream_metadata_file_count,
        "totalFiles": legado_file_count + so_novel_file_count + rule_pack_file_count + upstream_metadata_file_count,
    }

    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest["summary"], ensure_ascii=False, indent=2))
    print(f"manifest: {MANIFEST_PATH}")
    return 0


def collect_legado_payloads(work_root: Path, manifest: dict[str, Any]) -> list[JsonPayload]:
    payloads: list[JsonPayload] = []

    xiu2_local = work_root / "XIU2-Yuedu" / "shuyuan"
    add_json_payload(payloads, manifest, "xiu2_yuedu_local", "XIU2/Yuedu local shuyuan", xiu2_local)

    xiu2_remote = fetch_json_url(
        "xiu2_yuedu_remote",
        "XIU2/Yuedu raw shuyuan",
        "https://raw.githubusercontent.com/XIU2/Yuedu/master/shuyuan",
        manifest,
    )
    if xiu2_remote is not None:
        payloads.append(xiu2_remote)

    aoaostar_dir = work_root / "aoaostar-legado" / "sources"
    if aoaostar_dir.exists():
        for path in sorted(aoaostar_dir.glob("*.json")):
            add_json_payload(
                payloads,
                manifest,
                f"aoaostar_release_{path.stem}",
                f"aoaostar/legado release {path.name}",
                path,
            )
        for path in sorted(aoaostar_dir.glob("*.zip")):
            payloads.extend(read_zip_json_payloads(path, "aoaostar_release_zip", manifest))
    else:
        add_source_status(manifest, "aoaostar_legado_release", "missing", str(aoaostar_dir))

    # sjshb57/legado-57 currently provides replacement/cleanup rules, not site
    # book sources. collect_rule_packs() archives it separately.
    payloads.extend(collect_yiove_2026_collections(manifest))
    return payloads


def collect_so_novel_payloads(work_root: Path, manifest: dict[str, Any]) -> list[JsonPayload]:
    payloads: list[JsonPayload] = []
    rules_dir = work_root / "freeok-so-novel" / "bundle" / "rules"
    for filename in ("main.json", "proxy-required.json", "rate-limit.json", "no-search.json", "cloudflare.json"):
        add_json_payload(
            payloads,
            manifest,
            f"freeok_so_novel_{Path(filename).stem}",
            f"freeok/so-novel {filename}",
            rules_dir / filename,
        )

    remote = fetch_json_url(
        "freeok_so_novel_main_remote",
        "freeok/so-novel remote main.json",
        "https://raw.githubusercontent.com/freeok/so-novel/main/bundle/rules/main.json",
        manifest,
    )
    if remote is not None:
        payloads.append(remote)
    return payloads


def collect_rule_packs(work_root: Path, manifest: dict[str, Any]) -> None:
    candidates = [
        (
            "sjshb57_legado_57_v2_8_6",
            work_root / "sjshb57-legado-57" / "v2.8.6.json",
            RULE_PACK_DIR / "sjshb57-legado-57-v2.8.6.json",
        ),
    ]

    for origin_id, source_path, target_path in candidates:
        if not source_path.exists():
            add_source_status(manifest, origin_id, "missing", str(source_path))
            continue
        payload = read_json_path(source_path)
        target_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        add_source_status(manifest, origin_id, "archived_rule_pack", str(source_path))
        manifest["files"].append(
            {
                "path": str(target_path.relative_to(PROJECT_ROOT)),
                "format": "legado-replacement-rule-pack",
                "count": len(payload) if isinstance(payload, list) else 1,
                "origins": [origin_id],
            }
        )


def collect_yiove_2026_collections(manifest: dict[str, Any]) -> list[JsonPayload]:
    payloads: list[JsonPayload] = []
    collections = fetch_yiove_collection_list(manifest)
    selected = [
        item
        for item in collections
        if YIOVE_2026_START <= float(item.get("create_time") or 0) < YIOVE_2027_START
    ]

    metadata_path = UPSTREAM_METADATA_DIR / "yiove-2026-book-source-collections.json"
    metadata_path.write_text(
        json.dumps(selected, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest["files"].append(
        {
            "path": str(metadata_path.relative_to(PROJECT_ROOT)),
            "format": "yiove-book-source-collection-metadata",
            "count": len(selected),
            "origins": ["yiove_shuyuan_2026_collections"],
        }
    )

    add_source_status(
        manifest,
        "yiove_shuyuan_2026_collections",
        "selected_collections",
        f"{YIOVE_API_BASE}/shuyuan/book-source-collections",
        {"count": len(selected), "totalCollections": len(collections)},
    )

    for item in selected:
        collection_id = str(item.get("id") or "").strip()
        if not collection_id:
            continue
        url = f"{YIOVE_API_BASE}/import/book-source-collection/{collection_id}"
        try:
            payload = json.loads(fetch_text(url))
            payloads.append(
                JsonPayload(
                    f"yiove_2026_collection_{collection_id}",
                    f"Yiove 2026 collection {item.get('name')}",
                    url,
                    payload,
                )
            )
            add_source_status(
                manifest,
                f"yiove_2026_collection_{collection_id}",
                "loaded_remote",
                url,
                {
                    "name": item.get("name"),
                    "createTime": item.get("create_time"),
                    "count": payload_count(payload),
                },
            )
        except Exception as exc:  # noqa: BLE001
            add_source_status(
                manifest,
                f"yiove_2026_collection_{collection_id}",
                "remote_failed",
                url,
                {"name": item.get("name"), "error": str(exc)},
            )
    return payloads


def fetch_yiove_collection_list(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    url = f"{YIOVE_API_BASE}/shuyuan/book-source-collections?page=1&page_size=100"
    try:
        payload = json.loads(fetch_text(url))
        items = payload.get("items", []) if isinstance(payload, dict) else []
        add_source_status(
            manifest,
            "yiove_shuyuan_collection_list",
            "loaded_remote",
            url,
            {
                "count": len(items),
                "total": payload.get("total") if isinstance(payload, dict) else None,
                "pages": payload.get("pages") if isinstance(payload, dict) else None,
            },
        )
        return [item for item in items if isinstance(item, dict)]
    except Exception as exc:  # noqa: BLE001
        add_source_status(
            manifest,
            "yiove_shuyuan_collection_list",
            "remote_failed",
            url,
            {"error": str(exc)},
        )
        return []


def probe_yiove(manifest: dict[str, Any]) -> None:
    page_url = "https://shuyuan.yiove.com/"
    try:
        html = fetch_text(page_url)
        assets = re.findall(r'src="([^"]+\.js)"', html)
        js_hits: list[str] = []
        for asset in assets:
            asset_url = asset if asset.startswith("http") else f"https://shuyuan.yiove.com{asset}"
            js_text = fetch_text(asset_url)
            js_hits.extend(sorted(set(re.findall(r"https?://[^\"'`\\)\s]+", js_text))))
        add_source_status(
            manifest,
            "yiove_shuyuan",
            "frontend_spa_probe_completed",
            page_url,
            {
                "jsUrlCount": len(js_hits),
                "candidateUrls": js_hits[:20],
                "apiBaseUrl": YIOVE_API_BASE,
                "note": "The public page is a SPA route; source data is collected from the API base URL.",
            },
        )
    except Exception as exc:  # noqa: BLE001 - manifest should keep probe failures
        add_source_status(manifest, "yiove_shuyuan", "probe_failed", page_url, {"error": str(exc)})


def add_json_payload(
    payloads: list[JsonPayload],
    manifest: dict[str, Any],
    origin_id: str,
    origin_label: str,
    path: Path,
) -> None:
    if not path.exists():
        add_source_status(manifest, origin_id, "missing", str(path))
        return
    payload = read_json_path(path)
    payloads.append(JsonPayload(origin_id, origin_label, str(path), payload))
    add_source_status(manifest, origin_id, "loaded", str(path), {"count": payload_count(payload)})


def read_zip_json_payloads(path: Path, origin_prefix: str, manifest: dict[str, Any]) -> list[JsonPayload]:
    payloads: list[JsonPayload] = []
    try:
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if not name.lower().endswith(".json"):
                    continue
                text = archive.read(name).decode("utf-8-sig")
                payloads.append(
                    JsonPayload(
                        f"{origin_prefix}_{path.stem}_{Path(name).stem}",
                        f"{path.name}:{name}",
                        f"{path}!{name}",
                        json.loads(text),
                    )
                )
        add_source_status(manifest, f"{origin_prefix}_{path.stem}", "loaded_zip", str(path), {"count": len(payloads)})
    except Exception as exc:  # noqa: BLE001
        add_source_status(manifest, f"{origin_prefix}_{path.stem}", "zip_failed", str(path), {"error": str(exc)})
    return payloads


def fetch_json_url(origin_id: str, origin_label: str, url: str, manifest: dict[str, Any]) -> JsonPayload | None:
    try:
        payload = json.loads(fetch_text(url))
        add_source_status(manifest, origin_id, "loaded_remote", url, {"count": payload_count(payload)})
        return JsonPayload(origin_id, origin_label, url, payload)
    except Exception as exc:  # noqa: BLE001
        add_source_status(manifest, origin_id, "remote_failed", url, {"error": str(exc)})
        return None


def fetch_text(url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
            with urlopen(request, timeout=60) as response:
                return response.read().decode("utf-8-sig")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < 2:
                time.sleep(1 + attempt)
    assert last_error is not None
    raise last_error


def read_json_path(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def group_legado_sources(payloads: list[JsonPayload]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    origins_by_host: dict[str, set[str]] = defaultdict(set)
    seen_hashes: set[str] = set()

    for item in payloads:
        for source in iter_list_payload(item.payload):
            if not isinstance(source, dict) or "bookSourceUrl" not in source:
                continue
            digest = stable_digest(source)
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            host = host_from_url(source.get("bookSourceUrl", "")) or "unknown"
            groups[host].append(source)
            origins_by_host[host].add(item.origin_id)

    return dict(groups), {host: sorted(origins) for host, origins in origins_by_host.items()}


def group_so_novel_rules(payloads: list[JsonPayload]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    origins_by_host: dict[str, set[str]] = defaultdict(set)
    seen_hashes: set[str] = set()

    for item in payloads:
        for rule in iter_list_payload(item.payload):
            if not isinstance(rule, dict) or "url" not in rule:
                continue
            digest = stable_digest(rule)
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            host = host_from_url(rule.get("url", "")) or "unknown"
            groups[host].append(rule)
            origins_by_host[host].add(item.origin_id)

    return dict(groups), {host: sorted(origins) for host, origins in origins_by_host.items()}


def write_grouped_files(
    target_dir: Path,
    groups: dict[str, list[dict[str, Any]]],
    format_name: str,
    manifest: dict[str, Any],
    origins_by_host: dict[str, list[str]],
) -> int:
    count = 0
    for host, items in sorted(groups.items()):
        filename = f"{safe_filename(host)}.json"
        path = target_dir / filename
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest["files"].append(
            {
                "path": str(path.relative_to(PROJECT_ROOT)),
                "site": host,
                "format": format_name,
                "count": len(items),
                "origins": origins_by_host.get(host, []),
            }
        )
        count += 1
    return count


def iter_list_payload(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "sources", "items", "rules"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def host_from_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.lower()
    domain_match = re.search(r"(?<![a-z0-9-])(?:[a-z0-9-]+\.)+[a-z]{2,}(?![a-z0-9-])", normalized)
    if domain_match:
        return domain_match.group(0).removeprefix("www.")
    ip_match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", normalized)
    if ip_match:
        return ip_match.group(0)
    match = re.search(r"https?://[^\s\"'<>，,]+", value)
    if not match:
        return ""
    url = match.group(0)
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    if not re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,}|(?:\d{1,3}\.){3}\d{1,3}", host):
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def safe_filename(value: str) -> str:
    value = value.strip().lower() or "unknown"
    value = re.sub(r"[^a-z0-9._-]+", "_", value)
    value = value.strip("._-")
    return value or hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def stable_digest(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def payload_count(payload: Any) -> int:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        return 1
    return 0


def add_source_status(
    manifest: dict[str, Any],
    source_id: str,
    status: str,
    location: str,
    details: dict[str, Any] | None = None,
) -> None:
    entry = {"id": source_id, "status": status, "location": location}
    if details:
        entry["details"] = details
    manifest["sources"].append(entry)


if __name__ == "__main__":
    raise SystemExit(main())
