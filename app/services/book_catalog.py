"""Enhanced book catalog with reader support, fallback, and tracing."""

from __future__ import annotations

import sqlite3
from app.config import DB_PATH, HOST, PORT
from app.engine.proxy import ProxyConfig
from app.legado_engine.analyzer import decode_chapter_id
from app.services.cache import Cache
from app.services.legado_engine_runner import LegadoEngineRunner
from app.services.source_repository import SourceRepository


class BookCatalog:
    def __init__(self, repo: SourceRepository | None = None, cache: Cache | None = None):
        self.repo = repo or SourceRepository()
        self.cache = cache or Cache()

    def _get_proxy_config(self) -> ProxyConfig:
        import json
        from pathlib import Path
        pool_path = Path(__file__).resolve().parent.parent.parent / "config" / "source_pool.json"
        if pool_path.exists():
            data = json.loads(pool_path.read_text(encoding="utf-8"))
            return ProxyConfig.from_dict(data.get("proxy", {}))
        return ProxyConfig()

    def _get_search_config(self) -> dict:
        import json
        from pathlib import Path
        pool_path = Path(__file__).resolve().parent.parent.parent / "config" / "source_pool.json"
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

        config = self._get_search_config()
        source_timeout = config.get("source_timeout_seconds", 8.0)
        user_agent = config.get("default_user_agent", "")
        proxy_config = self._get_proxy_config()
        fallback_trace = []

        for sid in fallback_source_ids:
            if sid == primary_source_id:
                continue
            source = self.repo.load_raw_source(sid)
            if not source:
                fallback_trace.append({"sourceId": sid, "status": "skipped", "error": "source not found"})
                continue

            proxy_mode = source.get("proxyMode", "auto")
            executor = LegadoEngineRunner(
                user_agent=user_agent,
                timeout=source_timeout,
                proxy_url=proxy_config.url if proxy_config.enabled else "",
                proxy_mode=proxy_mode,
                proxy_config=proxy_config,
            )
            try:
                content, err = await executor.content(source, sid, chapter_url)
                if err:
                    fallback_trace.append({
                        "sourceId": sid,
                        "status": "failed",
                        "error": err.error,
                        "proxyUsed": err.proxyUsed,
                    })
                else:
                    fallback_trace.append({
                        "sourceId": sid,
                        "status": "success",
                        "proxyUsed": executor.get_last_meta().get("proxyUsed", False),
                    })
                    return {
                        "implemented": True,
                        "chapterId": chapter_id,
                        "title": content.title if content else "",
                        "content": content.content if content else "",
                        "fallbackUsed": True,
                        "fallbackSourceId": sid,
                        "fallbackTrace": fallback_trace,
                        "debug": {},
                    }
            except Exception as e:
                fallback_trace.append({"sourceId": sid, "status": "exception", "error": str(e)})
            finally:
                await executor.close()

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
        name, author = row
        # Find sources that might have this book (simple name match)
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT source_id, book_source_name FROM source_health WHERE enabled = 1 LIMIT 200"
            ).fetchall()
        return [{"sourceId": r[0], "sourceName": r[1]} for r in rows]

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
