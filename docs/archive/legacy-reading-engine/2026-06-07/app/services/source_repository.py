"""Source repository manager: scan, index, and manage all Legado sources.

- Canonical repository: data/sources/raw/by-site/legado/ (~2307 files)
- Multi-object JSON files are expanded into independent source records
- Stable IDs: <site-slug> for single-object, <site-slug>#<index> for multi-object
- Active pool: subset of enabled, healthy sources
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

from app.config import DB_PATH, PROJECT_ROOT, RAW_SOURCES_DIR
from app.rules.legado_loader import load_source_file, has_required_fields, make_source_id
from app.rules.legado_adapter import adapt_source_dict


class SourceRepository:
    """Manages the full source repository and active pool."""

    def __init__(
        self,
        repo_dir: Path | None = None,
        db_path: Path | None = None,
        subscription_config_path: Path | None = None,
    ):
        from app import config as app_config
        from app.storage.db import initialize_database

        self.repo_dir = repo_dir or RAW_SOURCES_DIR
        self.db_path = db_path or app_config.DB_PATH
        self.subscription_config_path = subscription_config_path or PROJECT_ROOT / "config" / "source_subscriptions.json"
        initialize_database(self.db_path)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _subscription_origins(self) -> dict[str, dict]:
        config_path = self.subscription_config_path
        if not config_path.exists():
            return {}
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

        origins: dict[str, dict] = {}
        for item in config.get("subscriptions", []):
            sub_id = item.get("id", "")
            if not sub_id:
                continue
            origin = {
                "subscription_id": sub_id,
                "upstream_url": item.get("url", ""),
                "engine_type": item.get("engine", "legado"),
            }
            for key in self._origin_path_keys(item):
                origins[key] = origin
        return origins

    def _origin_path_keys(self, item: dict) -> list[str]:
        keys: list[str] = []
        if item.get("last_output_path"):
            keys.append(self._normalize_origin_path(item["last_output_path"]))
        sub_id = str(item.get("id", ""))
        if sub_id:
            keys.append(self._normalize_origin_path(self.repo_dir / f"sub-{self._slugify(sub_id)}.json"))
        return [key for key in keys if key]

    def _normalize_origin_path(self, path_value) -> str:
        path = Path(path_value)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        try:
            return str(path.resolve().relative_to(PROJECT_ROOT)).replace("\\", "/")
        except ValueError:
            return str(path.resolve()).replace("\\", "/")

    def _origin_for_path(self, file_path: Path, origins: dict[str, dict]) -> dict:
        key = self._normalize_origin_path(file_path)
        return origins.get(key, {"subscription_id": "", "upstream_url": "", "engine_type": "legado"})

    def _slugify(self, value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+", "-", value).strip("-").lower()
        return slug[:80] or "subscription"

    def scan_and_index(self, limit: int | None = None) -> dict:
        """Scan all JSON files in the repository and index them into source_health.

        Returns a summary dict with counts.
        """
        files = sorted(self.repo_dir.glob("*.json"))
        if limit:
            files = files[:limit]

        total_files = len(files)
        total_objects = 0
        indexed = 0
        skipped = 0
        errors = 0

        origins = self._subscription_origins()

        with self._conn() as conn:
            for file_path in files:
                try:
                    objects = load_source_file(file_path)
                except Exception as e:
                    errors += 1
                    continue

                try:
                    rel_path = str(file_path.relative_to(Path(__file__).resolve().parent.parent.parent))
                except ValueError:
                    rel_path = str(file_path)
                is_multi = len(objects) > 1
                origin = self._origin_for_path(file_path, origins)

                for idx, raw in enumerate(objects):
                    total_objects += 1
                    if not isinstance(raw, dict):
                        skipped += 1
                        continue

                    source_name = raw.get("bookSourceName", "")
                    source_url = raw.get("bookSourceUrl", "")

                    sid = make_source_id(file_path.stem, idx, source_name, is_multi=is_multi)

                    has_required = has_required_fields(raw)
                    failure_reason = ""
                    if not has_required:
                        missing = [
                            f for f in ["bookSourceName", "bookSourceUrl", "searchUrl",
                                        "ruleSearch", "ruleBookInfo", "ruleToc", "ruleContent"]
                            if not raw.get(f)
                        ]
                        failure_reason = f"缺少必要字段: {', '.join(missing)}"

                    existing = conn.execute(
                        "SELECT enabled, health_status, failure_reason FROM source_health WHERE source_id = ?",
                        (sid,),
                    ).fetchone()
                    if has_required:
                        if existing and existing[1] == "disabled" and existing[2]:
                            enabled = existing[0]
                            health_status = existing[1]
                            persisted_failure_reason = existing[2]
                        else:
                            enabled = 1
                            health_status = existing[1] if existing and existing[1] not in ("missing_fields", "disabled") else "unknown"
                            persisted_failure_reason = ""
                    else:
                        enabled = 0
                        health_status = "missing_fields"
                        persisted_failure_reason = failure_reason

                    conn.execute(
                        """
                        INSERT OR REPLACE INTO source_health (
                            source_id, source_file_path, source_index, book_source_name,
                            book_source_url, enabled, health_status, failure_reason,
                            parser_capabilities_json, subscription_id, upstream_url,
                            engine_type, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                        """,
                        (
                            sid,
                            rel_path,
                            idx,
                            source_name,
                            source_url,
                            enabled,
                            health_status,
                            persisted_failure_reason,
                            json.dumps(self._detect_capabilities(raw), ensure_ascii=False),
                            origin.get("subscription_id", ""),
                            origin.get("upstream_url", ""),
                            origin.get("engine_type", "legado"),
                        ),
                    )
                    indexed += 1

            conn.commit()

        return {
            "total_files": total_files,
            "total_objects": total_objects,
            "indexed": indexed,
            "skipped": skipped,
            "errors": errors,
        }

    def enable_all_valid_sources(self) -> int:
        """Enable all indexed sources that are valid and not hard-disabled."""
        with self._conn() as conn:
            cursor = conn.execute(
                """
                UPDATE source_health
                SET enabled = 1,
                    health_status = CASE WHEN health_status = 'missing_fields' THEN health_status ELSE COALESCE(NULLIF(health_status, ''), 'unknown') END,
                    updated_at = datetime('now')
                WHERE health_status != 'missing_fields'
                  AND NOT (health_status = 'disabled' AND COALESCE(failure_reason, '') != '')
                """
            )
            conn.commit()
            return cursor.rowcount

    def _detect_capabilities(self, raw: dict) -> dict:
        """Detect parser capabilities for a source."""
        caps = {
            "has_search": bool(raw.get("searchUrl")),
            "has_book_info": bool(raw.get("ruleBookInfo")),
            "has_toc": bool(raw.get("ruleToc")),
            "has_content": bool(raw.get("ruleContent")),
            "has_explore": bool(raw.get("exploreUrl")),
            "has_headers": bool(raw.get("header")),
            "has_cookie_jar": raw.get("enabledCookieJar", False),
            "has_limited_js": False,
            "has_fallback": False,
            "has_exclusion": False,
            "unsupported_syntax": [],
        }

        # Classify syntax by the current rule engine contract.
        rules_text = json.dumps(raw, ensure_ascii=False)
        if "<js>" in rules_text:
            caps["unsupported_syntax"].append("<js> block")
        if "@js:" in rules_text:
            caps["has_limited_js"] = True
        if "||" in rules_text:
            caps["has_fallback"] = True
        if "!0" in rules_text or "!1" in rules_text:
            caps["has_exclusion"] = True
        if raw.get("loginUrl"):
            caps["unsupported_syntax"].append("loginUrl required")
        if raw.get("webView"):
            caps["unsupported_syntax"].append("webView required")

        return caps

    def get_source_count(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM source_health").fetchone()
            return row[0] if row else 0

    def get_source(self, source_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT source_id, source_file_path, source_index, book_source_name,
                       book_source_url, enabled, health_status, failure_reason,
                       proxy_mode, proxy_status, last_error, parser_capabilities_json,
                       last_test_result_json, success_count, failure_count,
                       subscription_id, upstream_url, engine_type
                FROM source_health WHERE source_id = ?
                """,
                (source_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "sourceId": row[0],
            "sourceFilePath": row[1],
            "sourceIndex": row[2],
            "bookSourceName": row[3],
            "bookSourceUrl": row[4],
            "enabled": bool(row[5]),
            "healthStatus": row[6],
            "failureReason": row[7] or "",
            "proxyMode": row[8] or "auto",
            "proxyStatus": row[9] or "unknown",
            "lastError": row[10] or "",
            "parserCapabilities": json.loads(row[11]) if row[11] else {},
            "lastTestResult": json.loads(row[12]) if row[12] else None,
            "successCount": row[13] or 0,
            "failureCount": row[14] or 0,
            "subscriptionId": row[15] or "",
            "upstreamUrl": row[16] or "",
            "engineType": row[17] or "legado",
        }

    def get_sources(
        self,
        enabled_only: bool = False,
        health_status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        query = """
            SELECT source_id, source_file_path, source_index, book_source_name,
                   book_source_url, enabled, health_status, failure_reason,
                   proxy_mode, proxy_status, last_error, parser_capabilities_json,
                   last_test_result_json, success_count, failure_count,
                   subscription_id, upstream_url, engine_type
            FROM source_health
            WHERE 1=1
        """
        params: list = []
        if enabled_only:
            query += " AND enabled = 1"
        if health_status:
            query += " AND health_status = ?"
            params.append(health_status)
        query += " ORDER BY book_source_name LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()

        return [
            {
                "sourceId": r[0],
                "sourceFilePath": r[1],
                "sourceIndex": r[2],
                "bookSourceName": r[3],
                "bookSourceUrl": r[4],
                "enabled": bool(r[5]),
                "healthStatus": r[6],
                "failureReason": r[7] or "",
                "proxyMode": r[8] or "auto",
                "proxyStatus": r[9] or "unknown",
                "lastError": r[10] or "",
                "parserCapabilities": json.loads(r[11]) if r[11] else {},
                "lastTestResult": json.loads(r[12]) if r[12] else None,
                "successCount": r[13] or 0,
                "failureCount": r[14] or 0,
                "subscriptionId": r[15] or "",
                "upstreamUrl": r[16] or "",
                "engineType": r[17] or "legado",
            }
            for r in rows
        ]

    def set_enabled(self, source_id: str, enabled: bool) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE source_health SET enabled = ?, updated_at = datetime('now') WHERE source_id = ?",
                (1 if enabled else 0, source_id),
            )
            conn.commit()

    def set_proxy_mode(self, source_id: str, proxy_mode: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE source_health SET proxy_mode = ?, updated_at = datetime('now') WHERE source_id = ?",
                (proxy_mode, source_id),
            )
            conn.commit()

    def record_attempt(
        self,
        source_id: str,
        stage: str,
        url: str,
        direct_status: str,
        proxy_status: str,
        proxy_used: bool,
        latency_ms: int,
        error: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO source_attempts
                (source_id, stage, url, direct_status, proxy_status, proxy_used, latency_ms, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source_id, stage, url, direct_status, proxy_status, 1 if proxy_used else 0, latency_ms, error),
            )
            conn.commit()

    def record_failure(
        self,
        source_id: str,
        stage: str,
        error: str,
        is_hard_failure: bool = False,
    ) -> None:
        """Record a failure and optionally disable the source."""
        with self._conn() as conn:
            # Update failure count
            conn.execute(
                """
                UPDATE source_health
                SET failure_count = failure_count + 1,
                    last_error = ?,
                    updated_at = datetime('now')
                WHERE source_id = ?
                """,
                (error, source_id),
            )

            if is_hard_failure:
                conn.execute(
                    """
                    UPDATE source_health
                    SET enabled = 0,
                        health_status = 'disabled',
                        failure_reason = ?,
                        updated_at = datetime('now')
                    WHERE source_id = ?
                    """,
                    (f"[{stage}] {error}", source_id),
                )

            conn.commit()

    def record_success(self, source_id: str, latency_ms: int) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE source_health
                SET success_count = success_count + 1,
                    last_success_at = datetime('now'),
                    health_status = CASE WHEN health_status IN ('unknown', 'disabled') THEN 'healthy' ELSE health_status END,
                    updated_at = datetime('now')
                WHERE source_id = ?
                """,
                (source_id,),
            )
            conn.commit()

    def get_attempts(self, source_id: str, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT stage, url, direct_status, proxy_status, proxy_used, latency_ms, error, created_at
                FROM source_attempts
                WHERE source_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (source_id, limit),
            ).fetchall()
        return [
            {
                "stage": r[0],
                "url": r[1],
                "directStatus": r[2],
                "proxyStatus": r[3],
                "proxyUsed": bool(r[4]),
                "latencyMs": r[5],
                "error": r[6] or "",
                "createdAt": r[7],
            }
            for r in rows
        ]

    def load_raw_source(self, source_id: str) -> dict | None:
        """Load the raw Legado source dict for execution."""
        info = self.get_source(source_id)
        if not info:
            return None

        file_path = Path(info["sourceFilePath"])
        if not file_path.is_absolute():
            base = Path(__file__).resolve().parent.parent.parent
            file_path = base / file_path

        if not file_path.exists():
            return None

        try:
            objects = load_source_file(file_path)
            idx = info.get("sourceIndex", 0)
            if 0 <= idx < len(objects):
                raw = objects[idx]
                adapted = adapt_source_dict(raw)
                adapted["enabled"] = info["enabled"]
                adapted["proxyMode"] = info["proxyMode"]
                adapted["configId"] = source_id
                return adapted
        except Exception:
            pass
        return None

    def get_stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM source_health").fetchone()[0]
            enabled = conn.execute("SELECT COUNT(*) FROM source_health WHERE enabled = 1").fetchone()[0]
            healthy = conn.execute(
                "SELECT COUNT(*) FROM source_health WHERE enabled = 1 AND health_status = 'healthy'"
            ).fetchone()[0]
            proxy_needed = conn.execute(
                "SELECT COUNT(*) FROM source_health WHERE proxy_status IN ('proxy_succeeded', 'proxy_needed', 'forced_proxy')"
            ).fetchone()[0]
            disabled = conn.execute(
                "SELECT COUNT(*) FROM source_health WHERE enabled = 0"
            ).fetchone()[0]
            unsupported = conn.execute(
                "SELECT COUNT(*) FROM source_health WHERE health_status = 'unsupported'"
            ).fetchone()[0]

        return {
            "total": total,
            "enabled": enabled,
            "healthy": healthy,
            "proxyNeeded": proxy_needed,
            "disabled": disabled,
            "unsupported": unsupported,
        }

    def update_test_result(self, source_id: str, result: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE source_health
                SET last_test_result_json = ?,
                    updated_at = datetime('now')
                WHERE source_id = ?
                """,
                (json.dumps(result, ensure_ascii=False), source_id),
            )
            conn.commit()
