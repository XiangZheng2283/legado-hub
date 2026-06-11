"""Enhanced book catalog with reader support, fallback, and tracing."""

from __future__ import annotations

import sqlite3
from app.config import DB_PATH, HOST, PORT, SOURCE_POOL_CONFIG_PATH
from app.core.proxy import ProxyConfig
from app.source_plugins.id_codec import decode_chapter_id
from app.services.cache import Cache
from app.source_plugins.scheduler import PluginScheduler
from app.services.plugin_health_repository import PluginHealthRepository


class BookCatalog:
    def __init__(self, repo: PluginHealthRepository | None = None, cache: Cache | None = None):
        self.repo = repo or PluginHealthRepository()
        self.cache = cache or Cache()
        self.scheduler = PluginScheduler()

    def _get_proxy_config(self) -> ProxyConfig:
        import json
        pool_path = SOURCE_POOL_CONFIG_PATH
        if pool_path.exists():
            data = json.loads(pool_path.read_text(encoding="utf-8"))
            return ProxyConfig.from_dict(data.get("proxy", {}))
        return ProxyConfig()

    def _get_search_config(self) -> dict:
        import json
        pool_path = SOURCE_POOL_CONFIG_PATH
        if pool_path.exists():
            return json.loads(pool_path.read_text(encoding="utf-8"))
        return {}

    async def book_detail(self, book_id: str) -> dict:
        from app.services.catalog import Catalog
        catalog = Catalog(repo=self.repo, cache=self.cache)
        return await catalog.book_detail(book_id)

    async def toc(self, book_id: str) -> dict:
        from app.services.catalog import Catalog
        catalog = Catalog(repo=self.repo, cache=self.cache)
        return await catalog.toc(book_id)

    async def chapter(self, chapter_id: str) -> dict:
        from app.services.catalog import Catalog
        catalog = Catalog(repo=self.repo, cache=self.cache)
        return await catalog.chapter(chapter_id)

    async def chapter_with_fallback(
        self,
        chapter_id: str,
        fallback_source_ids: list[str] | None = None,
    ) -> dict:
        """Get chapter with fallback to alternative sources."""
        primary = await self.chapter(chapter_id)
        if primary.get("content") or not fallback_source_ids:
            return {**primary, "fallbackUsed": False, "fallbackTrace": []}

        # Decode primary source and chapter URL
        try:
            primary_source_id, chapter_url = decode_chapter_id(chapter_id)
        except Exception:
            return {**primary, "fallbackUsed": False, "fallbackTrace": [{"error": "invalid chapter_id"}]}

        fallback_trace = []

        for sid in fallback_source_ids:
            if sid == primary_source_id:
                continue
            plugin = self.scheduler._plugins.get(sid)
            if not plugin or "chapter" not in plugin.capabilities:
                fallback_trace.append({"sourceId": sid, "status": "skipped", "error": "plugin not found or no chapter capability"})
                continue

            ctx = self.scheduler._make_ctx(sid)
            try:
                content = await plugin.source.chapter(ctx, chapter_url)
                content_text = ""
                if isinstance(content, dict):
                    content_text = content.get("content", "")
                elif hasattr(content, "content"):
                    content_text = content.content
                if content_text:
                    fallback_trace.append({"sourceId": sid, "status": "success"})
                    return {
                        "implemented": True,
                        "chapterId": chapter_id,
                        "title": content.get("title", "") if isinstance(content, dict) else getattr(content, "title", ""),
                        "content": content_text,
                        "fallbackUsed": True,
                        "fallbackSourceId": sid,
                        "fallbackTrace": fallback_trace,
                        "debug": {},
                    }
                else:
                    fallback_trace.append({"sourceId": sid, "status": "failed", "error": "empty content"})
            except Exception as e:
                fallback_trace.append({"sourceId": sid, "status": "exception", "error": str(e)})
            finally:
                await ctx._fetcher.close()

        return {
            **primary,
            "fallbackUsed": False,
            "fallbackTrace": fallback_trace,
        }

    def get_book_sources(self, book_id: str) -> list[dict]:
        """Get candidate sources for a book by name/author."""
        import sqlite3
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute(
                "SELECT name, author FROM book_records WHERE book_id = ?", (book_id,)
            ).fetchone()
        if not row:
            return []
        # Return enabled plugins as candidate sources
        plugins = self.scheduler._enabled_plugins()
        return [{"sourceId": p.metadata.id, "sourceName": p.metadata.name} for p in plugins]

    def get_chapter_navigation(self, book_id: str, chapter_id: str) -> dict:
        """Get previous and next chapter IDs."""
        toc = self.cache.get_toc(book_id)
        if not toc:
            return {"prev": None, "next": None}
        chapters = toc.get("chapters", [])
        for i, ch in enumerate(chapters):
            if ch.get("chapterId") == chapter_id:
                prev_ch = chapters[i - 1] if i > 0 else None
                next_ch = chapters[i + 1] if i < len(chapters) - 1 else None
                return {
                    "prev": prev_ch.get("chapterId") if prev_ch else None,
                    "next": next_ch.get("chapterId") if next_ch else None,
                    "prevTitle": prev_ch.get("title") if prev_ch else None,
                    "nextTitle": next_ch.get("title") if next_ch else None,
                }
        return {"prev": None, "next": None}


