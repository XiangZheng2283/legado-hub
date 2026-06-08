"""Project-managed source subscription configuration and sync."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import PROJECT_ROOT, RAW_SOURCES_DIR
from app.services.source_repository import SourceRepository


CONFIG_PATH = PROJECT_ROOT / "config" / "source_subscriptions.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+", "-", value).strip("-").lower()
    return slug[:80] or "subscription"


class SourceSubscriptionService:
    """Loads, mutates, and syncs source subscription links stored in project config."""

    def __init__(
        self,
        config_path: Path | None = None,
        target_dir: Path | None = None,
        repo: SourceRepository | None = None,
    ):
        self.config_path = config_path or CONFIG_PATH
        self.target_dir = target_dir or RAW_SOURCES_DIR
        self.repo = repo or SourceRepository(repo_dir=self.target_dir, subscription_config_path=self.config_path)
        self.repo.subscription_config_path = self.config_path

    def load_config(self) -> dict:
        if not self.config_path.exists():
            return {"version": 1, "target_dir": str(self.target_dir), "rescan_after_sync": True, "subscriptions": []}
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        data.setdefault("version", 1)
        try:
            target_dir = str(self.target_dir.relative_to(PROJECT_ROOT))
        except ValueError:
            target_dir = str(self.target_dir)
        data.setdefault("target_dir", target_dir)
        data.setdefault("rescan_after_sync", True)
        data.setdefault("subscriptions", [])
        return data

    def save_config(self, config: dict) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    def list_subscriptions(self) -> dict:
        config = self.load_config()
        return {
            "version": config.get("version", 1),
            "targetDir": config.get("target_dir", str(self.target_dir)),
            "rescanAfterSync": bool(config.get("rescan_after_sync", True)),
            "items": sorted(config.get("subscriptions", []), key=lambda item: item.get("priority", 1000)),
        }

    def add_subscription(self, payload: dict) -> dict:
        config = self.load_config()
        items = config.setdefault("subscriptions", [])
        name = str(payload.get("name") or payload.get("url") or "").strip()
        url = str(payload.get("url") or "").strip()
        if not url:
            raise ValueError("订阅链接不能为空")

        sub_id = str(payload.get("id") or _slugify(name or url)).strip()
        existing_ids = {item.get("id") for item in items}
        if sub_id in existing_ids:
            base_id = sub_id
            suffix = 2
            while f"{base_id}-{suffix}" in existing_ids:
                suffix += 1
            sub_id = f"{base_id}-{suffix}"

        item = {
            "id": sub_id,
            "name": name or sub_id,
            "engine": payload.get("engine", "legado"),
            "kind": payload.get("kind", "direct_json"),
            "url": url,
            "homepage": payload.get("homepage", ""),
            "enabled": bool(payload.get("enabled", True)),
            "built_in": False,
            "priority": int(payload.get("priority", 100)),
            "notes": payload.get("notes", ""),
        }
        if payload.get("import_url_template"):
            item["import_url_template"] = payload["import_url_template"]
        items.append(item)
        self.save_config(config)
        return item

    def update_subscription(self, subscription_id: str, payload: dict) -> dict | None:
        config = self.load_config()
        for item in config.get("subscriptions", []):
            if item.get("id") == subscription_id:
                for key in [
                    "name", "engine", "kind", "url", "homepage", "enabled", "priority",
                    "notes", "import_url_template", "max_collections",
                ]:
                    if key in payload:
                        item[key] = payload[key]
                item["updated_at"] = _now()
                self.save_config(config)
                return item
        return None

    async def sync_all(self, include_disabled: bool = False) -> dict:
        results = []
        for item in self.list_subscriptions()["items"]:
            if not include_disabled and not item.get("enabled", True):
                continue
            results.append(await self.sync_subscription(item["id"], rescan=False))
        summary = self.repo.scan_and_index() if self.load_config().get("rescan_after_sync", True) else {}
        return {
            "synced": len(results),
            "results": results,
            "rescan": summary,
        }

    async def sync_subscription(self, subscription_id: str, rescan: bool = True) -> dict:
        config = self.load_config()
        item = next((sub for sub in config.get("subscriptions", []) if sub.get("id") == subscription_id), None)
        if not item:
            return {"subscriptionId": subscription_id, "ok": False, "error": "订阅不存在"}

        started = _now()
        try:
            if item.get("engine", "legado") != "legado":
                raise ValueError(f"当前同步器不支持 {item.get('engine')} 引擎")
            if item.get("kind") == "github_tree_reference":
                raise ValueError("该来源是仓库目录引用，不是可直接导入订阅链接")

            sources = await self._fetch_subscription_sources(item)
            if not sources:
                raise ValueError("订阅未返回有效书源对象")

            output_path = self._write_sources(item, sources)
            item["last_sync_at"] = started
            item["last_sync_status"] = "success"
            item["last_sync_error"] = ""
            item["last_sync_count"] = len(sources)
            try:
                item["last_output_path"] = str(output_path.relative_to(PROJECT_ROOT))
            except ValueError:
                item["last_output_path"] = str(output_path)
            self.save_config(config)
            rescan_summary = self.repo.scan_and_index() if rescan and config.get("rescan_after_sync", True) else {}
            return {
                "subscriptionId": subscription_id,
                "ok": True,
                "count": len(sources),
                "outputPath": item["last_output_path"],
                "rescan": rescan_summary,
            }
        except Exception as exc:
            item["last_sync_at"] = started
            item["last_sync_status"] = "failed"
            item["last_sync_error"] = str(exc)
            self.save_config(config)
            return {"subscriptionId": subscription_id, "ok": False, "error": str(exc)}

    async def _fetch_subscription_sources(self, item: dict) -> list[dict]:
        if item.get("kind") == "yiove_collections":
            return await self._fetch_yiove_collections(item)
        text = await self._fetch_text(item["url"])
        return self._normalize_sources(json.loads(text))

    async def _fetch_yiove_collections(self, item: dict) -> list[dict]:
        data = json.loads(await self._fetch_text(item["url"]))
        collections = self._extract_yiove_collections(data)
        max_collections = int(item.get("max_collections") or 20)
        import_template = item.get("import_url_template", "")
        if not import_template:
            raise ValueError("Yiove 订阅缺少 import_url_template")

        sources: list[dict] = []
        for collection in collections[:max_collections]:
            collection_id = collection.get("id") or collection.get("collection_id") or collection.get("collectionId")
            if not collection_id:
                continue
            import_url = import_template.replace("{collection_id}", str(collection_id))
            try:
                payload = json.loads(await self._fetch_text(import_url))
                sources.extend(self._normalize_sources(payload))
            except Exception:
                continue
        return sources

    def _extract_yiove_collections(self, data: Any) -> list[dict]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if not isinstance(data, dict):
            return []
        for key in ("data", "items", "list", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = self._extract_yiove_collections(value)
                if nested:
                    return nested
        return []

    async def _fetch_text(self, url: str) -> str:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    def _normalize_sources(self, payload: Any) -> list[dict]:
        if isinstance(payload, dict):
            if "bookSourceName" in payload or "bookSourceUrl" in payload:
                return [payload]
            for key in ("data", "sources", "bookSources", "items", "list"):
                if key in payload:
                    return self._normalize_sources(payload[key])
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict) and ("bookSourceName" in item or "bookSourceUrl" in item)]
        return []

    def _write_sources(self, item: dict, sources: list[dict]) -> Path:
        self.target_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.target_dir / f"sub-{_slugify(item['id'])}.json"
        output_path.write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
        return output_path
