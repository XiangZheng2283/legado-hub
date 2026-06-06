"""Explore / ranking / discover service."""

from __future__ import annotations

from app.legado_engine.models import LegadoSource
from app.legado_engine.source_adapter import adapt_source_dict
from app.legado_engine.explore import ExploreExecutor
from app.legado_engine.http_runtime import HttpRuntime
from app.engine.proxy import ProxyConfig
from app.services.source_repository import SourceRepository


class ExploreCatalog:
    def __init__(self, repo: SourceRepository | None = None):
        self.repo = repo or SourceRepository()

    def _get_proxy_config(self) -> ProxyConfig:
        import json
        from pathlib import Path
        pool_path = Path(__file__).resolve().parent.parent.parent / "config" / "source_pool.json"
        if pool_path.exists():
            data = json.loads(pool_path.read_text(encoding="utf-8"))
            return ProxyConfig.from_dict(data.get("proxy", {}))
        return ProxyConfig()

    def list_explore_sources(self) -> list[dict]:
        """List sources that have exploreUrl enabled."""
        sources = self.repo.get_sources(enabled_only=True, limit=1000)
        result = []
        for src in sources:
            caps = src.get("parserCapabilities", {})
            if caps.get("has_explore"):
                result.append(src)
        return result

    def get_explore_groups(self, source_id: str) -> list[dict]:
        """Get explore groups for a source."""
        raw = self.repo.load_raw_source(source_id)
        if not raw:
            return []
        source = adapt_source_dict(raw)
        proxy_config = self._get_proxy_config()
        executor = ExploreExecutor(proxy_config=proxy_config)
        return executor.parse_explore_groups(source)

    async def explore_items(
        self,
        source_id: str,
        explore_url: str,
        page: int = 1,
    ) -> dict:
        """Execute explore for a specific URL."""
        raw = self.repo.load_raw_source(source_id)
        if not raw:
            return {"success": False, "error": "书源不存在", "items": []}

        source = adapt_source_dict(raw)
        proxy_config = self._get_proxy_config()
        http = HttpRuntime(proxy_url=proxy_config.url if proxy_config.enabled else "")
        executor = ExploreExecutor(http=http, proxy_config=proxy_config)

        result = await executor.execute_explore(source, explore_url, page=page)
        return {
            "success": result.success,
            "error": result.error,
            "items": result.data or [],
            "trace": [t.to_dict() for t in result.trace],
        }
