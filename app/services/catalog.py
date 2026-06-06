"""Concurrent search across enabled sources with batched execution, failure recording, and proxy fallback."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from app.config import HOST, PORT
from app.engine.proxy import ProxyConfig
from app.legado_engine.analyzer import decode_book_id, decode_chapter_id
from app.rules.models import SearchResultItem, SourceError
from app.services.cache import Cache
from app.services.legado_engine_runner import LegadoEngineRunner
from app.services.source_repository import SourceRepository


class Catalog:
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

    def _record_attempt(
        self,
        source_id: str,
        stage: str,
        url: str,
        proxy_used: bool,
        success: bool,
        latency_ms: int,
        error: str = "",
    ) -> None:
        self.repo.record_attempt(
            source_id=source_id,
            stage=stage,
            url=url,
            direct_status="success" if success and not proxy_used else ("failed" if not proxy_used else "-"),
            proxy_status="success" if success and proxy_used else ("failed" if proxy_used else "-"),
            proxy_used=proxy_used,
            latency_ms=latency_ms,
            error=error,
        )

    async def search(
        self,
        keyword: str,
        page: int = 1,
    ) -> dict:
        cached = self.cache.get_search(keyword, page)
        if cached is not None:
            return cached

        config = self._get_search_config()
        max_concurrency = config.get("max_concurrency", 6)
        source_batch_size = config.get("source_batch_size", 20)
        source_timeout = config.get("source_timeout_seconds", 8.0)
        overall_timeout = config.get("overall_search_timeout_seconds", 30.0)
        max_sources = config.get("max_sources_per_search", 200)
        user_agent = config.get("default_user_agent", "")
        proxy_config = self._get_proxy_config()

        # Load enabled sources from repository, limited to max_sources
        sources = self.repo.get_sources(enabled_only=True, limit=max_sources)
        if not sources:
            return {
                "implemented": True,
                "keyword": keyword,
                "page": page,
                "items": [],
                "debug": {
                    "sourceCount": 0,
                    "attemptedCount": 0,
                    "successCount": 0,
                    "errorCount": 0,
                    "disabledCount": 0,
                    "timeoutCount": 0,
                    "elapsedMs": 0,
                    "errors": [],
                    "partialSuccess": False,
                },
            }

        all_items: list[SearchResultItem] = []
        errors: list[SourceError] = []
        start_time = time.perf_counter()
        timeout_count = 0
        success_count = 0
        attempted_count = 0
        batch_count = 0

        semaphore = asyncio.Semaphore(max_concurrency)

        async def _search_one(src_info: dict) -> tuple[list[SearchResultItem], SourceError | None]:
            sid = src_info["sourceId"]
            proxy_mode = src_info.get("proxyMode", "auto")
            executor = LegadoEngineRunner(
                user_agent=user_agent,
                timeout=source_timeout,
                proxy_url=proxy_config.url if proxy_config.enabled else "",
                proxy_mode=proxy_mode,
                proxy_config=proxy_config,
            )

            t0 = time.perf_counter()
            try:
                source = self.repo.load_raw_source(sid)
                if not source:
                    err = SourceError(sourceId=sid, stage="search", url="", proxyUsed=False, error="无法加载书源")
                    self._record_attempt(sid, "search", "", False, False, 0, "无法加载书源")
                    return [], err

                items, err = await asyncio.wait_for(
                    executor.search(source, sid, keyword, page),
                    timeout=source_timeout,
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                meta = executor.get_last_meta()
                proxy_used = meta.get("proxyUsed", False)

                if err:
                    self._record_attempt(sid, "search", err.url or "", proxy_used, False, latency_ms, err.error)
                    # Hard failures: missing rules, unsupported syntax, parse failure
                    if any(k in err.error.lower() for k in ["unsupported", "missing", "parse", "invalid"]):
                        self.repo.record_failure(sid, "search", err.error, is_hard_failure=True)
                    return [], err

                self._record_attempt(sid, "search", "", proxy_used, True, latency_ms)
                self.repo.record_success(sid, latency_ms)
                return items, None

            except asyncio.TimeoutError:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._record_attempt(sid, "search", "", False, False, latency_ms, "timeout")
                err = SourceError(sourceId=sid, stage="search", url="", proxyUsed=False, error="timeout")
                return [], err
            except Exception as e:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._record_attempt(sid, "search", "", False, False, latency_ms, str(e))
                err = SourceError(sourceId=sid, stage="search", url="", proxyUsed=False, error=str(e))
                return [], err
            finally:
                await executor.close()

        source_batch_size = int(source_batch_size) if source_batch_size else 20
        if source_batch_size <= 0:
            source_batch_size = 20
        batches = [sources[i : i + source_batch_size] for i in range(0, len(sources), source_batch_size)]
        batch_count = len(batches)

        for batch in batches:
            if int((time.perf_counter() - start_time) * 1000) >= overall_timeout * 1000:
                errors.append(SourceError(sourceId="", stage="search", url="", error="overall timeout"))
                break

            remaining_timeout = max(0.1, overall_timeout - (time.perf_counter() - start_time))
            tasks = [asyncio.create_task(_search_one(src)) for src in batch]
            attempted_count += len(batch)
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=remaining_timeout,
                )
            except asyncio.TimeoutError:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                results = []
                for task in tasks:
                    if task.done() and not task.cancelled():
                        try:
                            results.append(task.result())
                        except Exception as e:
                            results.append(([], SourceError(sourceId="", stage="search", url="", error=str(e))))
                    else:
                        results.append(([], SourceError(sourceId="", stage="search", url="", error="overall timeout")))

            for src, (items, err) in zip(batch, results):
                sid = src["sourceId"]
                if isinstance(items, Exception):
                    errors.append(SourceError(sourceId=sid, stage="search", url="", error=str(items)))
                    continue
                if err:
                    errors.append(err)
                    if "timeout" in err.error.lower():
                        timeout_count += 1
                if items:
                    success_count += 1
                    for item in items:
                        score = 0
                        if keyword.lower() in item.name.lower():
                            score += 100
                        if item.author:
                            score += 10
                        if item.lastChapter:
                            score += 5
                        if item.intro:
                            score += 3
                        item.score = score
                    all_items.extend(items)

        # Merge same name + author
        merged = self._merge_results(all_items)
        merged.sort(key=lambda x: (-x.score, x.name))

        base_api = f"http://{HOST}:{PORT}"
        for item in merged:
            item.bookUrl = f"{base_api}/api/legado/book/{item.bookId}"

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        partial_success = success_count > 0 and len(errors) > 0

        response = {
            "implemented": True,
            "keyword": keyword,
            "page": page,
            "items": [item.model_dump() for item in merged],
            "debug": {
                "sourceCount": len(sources),
                "batchSize": source_batch_size,
                "batchCount": batch_count,
                "attemptedCount": attempted_count,
                "successCount": success_count,
                "errorCount": len(errors),
                "disabledCount": 0,
                "timeoutCount": timeout_count,
                "elapsedMs": elapsed_ms,
                "errors": [err.model_dump() for err in errors if err],
                "partialSuccess": partial_success,
            },
        }

        self.cache.set_search(keyword, page, response)
        return response

    async def stream_search(self, keyword: str, page: int = 1, max_sources_override: int | None = None):
        """Yield backend-admin search progress events as dictionaries."""
        config = self._get_search_config()
        max_concurrency = config.get("max_concurrency", 6)
        source_batch_size = config.get("source_batch_size", 20)
        source_timeout = config.get("source_timeout_seconds", 8.0)
        overall_timeout = config.get("overall_search_timeout_seconds", 30.0)
        max_sources = config.get("max_sources_per_search", 200)
        if max_sources_override is not None:
            max_sources = max(0, int(max_sources_override))
        user_agent = config.get("default_user_agent", "")
        proxy_config = self._get_proxy_config()
        sources = self.repo.get_sources(enabled_only=True, limit=max_sources)

        source_batch_size = int(source_batch_size) if source_batch_size else 20
        if source_batch_size <= 0:
            source_batch_size = 20
        batches = [sources[i : i + source_batch_size] for i in range(0, len(sources), source_batch_size)]
        start_time = time.perf_counter()
        all_items: list[SearchResultItem] = []
        errors: list[SourceError] = []
        success_count = 0
        completed_count = 0
        timeout_count = 0

        yield {
            "type": "summary",
            "keyword": keyword,
            "page": page,
            "sourceCount": len(sources),
            "batchSize": source_batch_size,
            "batchCount": len(batches),
            "maxConcurrency": max_concurrency,
            "overallTimeoutSeconds": overall_timeout,
        }

        if not sources:
            yield {
                "type": "done",
                "items": [],
                "debug": {
                    "sourceCount": 0,
                    "attemptedCount": 0,
                    "successCount": 0,
                    "errorCount": 0,
                    "timeoutCount": 0,
                    "elapsedMs": 0,
                    "partialSuccess": False,
                },
            }
            return

        async def _search_one(src_info: dict) -> dict:
            sid = src_info["sourceId"]
            proxy_mode = src_info.get("proxyMode", "auto")
            executor = LegadoEngineRunner(
                user_agent=user_agent,
                timeout=source_timeout,
                proxy_url=proxy_config.url if proxy_config.enabled else "",
                proxy_mode=proxy_mode,
                proxy_config=proxy_config,
            )
            t0 = time.perf_counter()
            try:
                source = self.repo.load_raw_source(sid)
                if not source:
                    err = SourceError(sourceId=sid, stage="search", url="", proxyUsed=False, error="无法加载书源")
                    self._record_attempt(sid, "search", "", False, False, 0, "无法加载书源")
                    return {"source": src_info, "items": [], "error": err, "latencyMs": 0, "proxyUsed": False}

                items, err = await asyncio.wait_for(
                    executor.search(source, sid, keyword, page),
                    timeout=source_timeout,
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                meta = executor.get_last_meta()
                proxy_used = meta.get("proxyUsed", False)
                if err:
                    self._record_attempt(sid, "search", err.url or "", proxy_used, False, latency_ms, err.error)
                    if any(k in err.error.lower() for k in ["unsupported", "missing", "parse", "invalid"]):
                        self.repo.record_failure(sid, "search", err.error, is_hard_failure=True)
                    return {"source": src_info, "items": [], "error": err, "latencyMs": latency_ms, "proxyUsed": proxy_used}

                self._record_attempt(sid, "search", "", proxy_used, True, latency_ms)
                self.repo.record_success(sid, latency_ms)
                return {"source": src_info, "items": items, "error": None, "latencyMs": latency_ms, "proxyUsed": proxy_used}
            except asyncio.TimeoutError:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._record_attempt(sid, "search", "", False, False, latency_ms, "timeout")
                err = SourceError(sourceId=sid, stage="search", url="", proxyUsed=False, error="timeout")
                return {"source": src_info, "items": [], "error": err, "latencyMs": latency_ms, "proxyUsed": False}
            except Exception as exc:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                self._record_attempt(sid, "search", "", False, False, latency_ms, str(exc))
                err = SourceError(sourceId=sid, stage="search", url="", proxyUsed=False, error=str(exc))
                return {"source": src_info, "items": [], "error": err, "latencyMs": latency_ms, "proxyUsed": False}
            finally:
                await executor.close()

        for batch_index, batch in enumerate(batches, start=1):
            elapsed = time.perf_counter() - start_time
            if elapsed >= overall_timeout:
                errors.append(SourceError(sourceId="", stage="search", url="", error="overall timeout"))
                yield {"type": "overall_timeout", "elapsedMs": int(elapsed * 1000)}
                break

            for src in batch:
                yield {
                    "type": "source_start",
                    "batchIndex": batch_index,
                    "sourceId": src["sourceId"],
                    "sourceName": src.get("bookSourceName") or src["sourceId"],
                    "proxyMode": src.get("proxyMode", "auto"),
                }

            tasks = [asyncio.create_task(_search_one(src)) for src in batch]
            pending = set(tasks)
            while pending:
                remaining_timeout = max(0.1, overall_timeout - (time.perf_counter() - start_time))
                done, pending = await asyncio.wait(pending, timeout=remaining_timeout, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    for task in pending:
                        task.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    timeout_count += len(pending)
                    errors.append(SourceError(sourceId="", stage="search", url="", error="overall timeout"))
                    yield {"type": "overall_timeout", "elapsedMs": int((time.perf_counter() - start_time) * 1000)}
                    pending = set()
                    break

                for task in done:
                    result = task.result()
                    src = result["source"]
                    items = result["items"]
                    err = result["error"]
                    completed_count += 1
                    if err:
                        errors.append(err)
                        if "timeout" in err.error.lower():
                            timeout_count += 1
                    if items:
                        success_count += 1
                        for item in items:
                            score = 0
                            if keyword.lower() in item.name.lower():
                                score += 100
                            if item.author:
                                score += 10
                            if item.lastChapter:
                                score += 5
                            if item.intro:
                                score += 3
                            item.score = score
                        all_items.extend(items)

                    yield {
                        "type": "source_done",
                        "sourceId": src["sourceId"],
                        "sourceName": src.get("bookSourceName") or src["sourceId"],
                        "status": "error" if err else "success",
                        "resultCount": len(items),
                        "latencyMs": result["latencyMs"],
                        "proxyUsed": result["proxyUsed"],
                        "error": err.model_dump() if err else None,
                        "completedCount": completed_count,
                        "sourceCount": len(sources),
                    }
                    for item in items:
                        yield {
                            "type": "result",
                            "item": item.model_dump(),
                            "sourceId": src["sourceId"],
                            "sourceName": src.get("bookSourceName") or src["sourceId"],
                        }

            yield {
                "type": "batch_done",
                "batchIndex": batch_index,
                "completedCount": completed_count,
                "sourceCount": len(sources),
            }

        merged = self._merge_results(all_items)
        merged.sort(key=lambda x: (-x.score, x.name))
        base_api = f"http://{HOST}:{PORT}"
        for item in merged:
            item.bookUrl = f"{base_api}/api/legado/book/{item.bookId}"

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        response = {
            "implemented": True,
            "keyword": keyword,
            "page": page,
            "items": [item.model_dump() for item in merged],
            "debug": {
                "sourceCount": len(sources),
                "batchSize": source_batch_size,
                "batchCount": len(batches),
                "attemptedCount": completed_count,
                "successCount": success_count,
                "errorCount": len(errors),
                "disabledCount": 0,
                "timeoutCount": timeout_count,
                "elapsedMs": elapsed_ms,
                "errors": [err.model_dump() for err in errors if err],
                "partialSuccess": success_count > 0 and len(errors) > 0,
            },
        }
        self.cache.set_search(keyword, page, response)
        yield {
            "type": "done",
            "items": response["items"],
            "debug": response["debug"],
        }

    def _merge_results(self, items: list[SearchResultItem]) -> list[SearchResultItem]:
        """Merge results with same name and author."""
        groups: dict[tuple[str, str], list[SearchResultItem]] = {}
        for item in items:
            key = (item.name.strip(), item.author.strip())
            if key not in groups:
                groups[key] = []
            groups[key].append(item)

        merged: list[SearchResultItem] = []
        for key, group_items in groups.items():
            if len(group_items) == 1:
                merged.append(group_items[0])
                continue
            # Pick best candidate (highest score, or first if tie)
            best = max(group_items, key=lambda x: x.score)
            # Preserve source candidates info in intro or similar
            sources_info = ", ".join(
                f"{g.sourceName}({g.sourceId})" for g in group_items
            )
            best.intro = f"{best.intro} [来源: {sources_info}]" if best.intro else f"[来源: {sources_info}]"
            merged.append(best)
        return merged

    async def book_detail(self, book_id: str, user_agent: str = "") -> dict:
        cached = self.cache.get_book(book_id)
        if cached is not None:
            return cached

        try:
            source_id, book_url = decode_book_id(book_id)
        except Exception:
            return {"implemented": True, "data": None, "debug": {"error": "invalid book_id format"}}

        source = self.repo.load_raw_source(source_id)
        if not source:
            return {"implemented": True, "data": None, "debug": {"error": f"source not found: {source_id}"}}

        config = self._get_search_config()
        user_agent = config.get("default_user_agent", user_agent)
        source_timeout = config.get("source_timeout_seconds", 8.0)
        proxy_config = self._get_proxy_config()
        proxy_mode = source.get("proxyMode", "auto")

        executor = LegadoEngineRunner(
            user_agent=user_agent,
            timeout=source_timeout,
            proxy_url=proxy_config.url if proxy_config.enabled else "",
            proxy_mode=proxy_mode,
            proxy_config=proxy_config,
        )
        try:
            detail, err = await executor.book_detail(source, source_id, book_url)
            meta = executor.get_last_meta()
            proxy_used = meta.get("proxyUsed", False)
            if err:
                self._record_attempt(source_id, "detail", book_url, proxy_used, False, 0, err.error)
            else:
                self._record_attempt(source_id, "detail", book_url, proxy_used, True, 0)
                self.repo.record_success(source_id, 0)
        finally:
            await executor.close()

        if err:
            return {"implemented": True, "data": None, "debug": {"error": err.model_dump()}}

        if detail is None:
            return {"implemented": True, "data": None, "debug": {}}

        data = detail.model_dump()
        base_api = f"http://{HOST}:{PORT}"
        data["bookUrl"] = f"{base_api}/api/legado/book/{book_id}"
        data["tocUrl"] = f"{base_api}/api/legado/book/{book_id}/toc"

        # Create/update book record for tracking
        self._ensure_book_record(book_id, data)

        response = {"implemented": True, "data": data, "debug": {}}
        self.cache.set_book(book_id, source_id, book_url, response)
        return response

    def _ensure_book_record(self, book_id: str, data: dict) -> None:
        import sqlite3
        from app.config import DB_PATH
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO book_records
                (book_id, name, author, last_chapter, last_seen_at, created_at)
                VALUES (?, ?, ?, ?, datetime('now'), COALESCE((SELECT created_at FROM book_records WHERE book_id=?), datetime('now')))
                """,
                (book_id, data.get("name", ""), data.get("author", ""), data.get("lastChapter", ""), book_id),
            )
            conn.commit()

    async def toc(self, book_id: str, user_agent: str = "") -> dict:
        cached = self.cache.get_toc(book_id)
        if cached is not None:
            return cached

        try:
            source_id, book_url = decode_book_id(book_id)
        except Exception:
            return {"implemented": True, "bookId": book_id, "chapters": [], "debug": {"error": "invalid book_id format"}}

        source = self.repo.load_raw_source(source_id)
        if not source:
            return {"implemented": True, "bookId": book_id, "chapters": [], "debug": {"error": f"source not found: {source_id}"}}

        config = self._get_search_config()
        user_agent = config.get("default_user_agent", user_agent)
        source_timeout = config.get("source_timeout_seconds", 8.0)
        proxy_config = self._get_proxy_config()
        proxy_mode = source.get("proxyMode", "auto")

        executor = LegadoEngineRunner(
            user_agent=user_agent,
            timeout=source_timeout,
            proxy_url=proxy_config.url if proxy_config.enabled else "",
            proxy_mode=proxy_mode,
            proxy_config=proxy_config,
        )
        try:
            detail, _ = await executor.book_detail(source, source_id, book_url)
            toc_url = detail.tocUrl if detail else book_url
            chapters, err = await executor.toc(source, source_id, toc_url)
            meta = executor.get_last_meta()
            proxy_used = meta.get("proxyUsed", False)
            if err:
                self._record_attempt(source_id, "toc", toc_url, proxy_used, False, 0, err.error)
            else:
                self._record_attempt(source_id, "toc", toc_url, proxy_used, True, 0)
                self.repo.record_success(source_id, 0)
        finally:
            await executor.close()

        if err:
            return {"implemented": True, "bookId": book_id, "chapters": [], "debug": {"error": err.model_dump()}}

        base_api = f"http://{HOST}:{PORT}"
        for ch in chapters:
            ch.chapterUrl = f"{base_api}/api/legado/chapter/{ch.chapterId}"

        response = {
            "implemented": True,
            "bookId": book_id,
            "chapters": [ch.model_dump() for ch in chapters],
            "debug": {},
        }
        self.cache.set_toc(book_id, response)
        return response

    async def chapter(self, chapter_id: str, user_agent: str = "") -> dict:
        cached = self.cache.get_chapter(chapter_id)
        if cached is not None:
            return cached

        try:
            source_id, chapter_url = decode_chapter_id(chapter_id)
        except Exception:
            return {"implemented": True, "chapterId": chapter_id, "title": "", "content": "", "debug": {"error": "invalid chapter_id format"}}

        source = self.repo.load_raw_source(source_id)
        if not source:
            return {"implemented": True, "chapterId": chapter_id, "title": "", "content": "", "debug": {"error": f"source not found: {source_id}"}}

        config = self._get_search_config()
        user_agent = config.get("default_user_agent", user_agent)
        source_timeout = config.get("source_timeout_seconds", 8.0)
        proxy_config = self._get_proxy_config()
        proxy_mode = source.get("proxyMode", "auto")

        executor = LegadoEngineRunner(
            user_agent=user_agent,
            timeout=source_timeout,
            proxy_url=proxy_config.url if proxy_config.enabled else "",
            proxy_mode=proxy_mode,
            proxy_config=proxy_config,
        )
        try:
            content, err = await executor.content(source, source_id, chapter_url)
            meta = executor.get_last_meta()
            proxy_used = meta.get("proxyUsed", False)
            if err:
                self._record_attempt(source_id, "content", chapter_url, proxy_used, False, 0, err.error)
            else:
                self._record_attempt(source_id, "content", chapter_url, proxy_used, True, 0)
                self.repo.record_success(source_id, 0)
        finally:
            await executor.close()

        if err:
            return {"implemented": True, "chapterId": chapter_id, "title": "", "content": "", "debug": {"error": err.model_dump()}}

        if content is None:
            return {"implemented": True, "chapterId": chapter_id, "title": "", "content": "", "debug": {}}

        response = {
            "implemented": True,
            "chapterId": chapter_id,
            "title": content.title,
            "content": content.content,
            "debug": {},
        }
        self.cache.set_chapter(chapter_id, source_id, chapter_url, response)
        return response

    async def test_source(
        self,
        source_id: str,
        keyword: str = "凡人修仙传",
        page: int = 1,
        stage: str = "search",
        proxy_mode_override: str | None = None,
    ) -> dict:
        """Test a single source without affecting active pool state."""
        src_info = self.repo.get_source(source_id)
        if not src_info:
            return {"pass": False, "error": "书源不存在", "stage": stage}

        source = self.repo.load_raw_source(source_id)
        if not source:
            return {"pass": False, "error": "无法加载书源文件", "stage": stage}

        config = self._get_search_config()
        source_timeout = config.get("source_timeout_seconds", 8.0)
        user_agent = config.get("default_user_agent", "")
        proxy_config = self._get_proxy_config()
        proxy_mode = proxy_mode_override or src_info.get("proxyMode", "auto")

        executor = LegadoEngineRunner(
            user_agent=user_agent,
            timeout=source_timeout,
            proxy_url=proxy_config.url if proxy_config.enabled else "",
            proxy_mode=proxy_mode,
            proxy_config=proxy_config,
        )

        result: dict[str, Any] = {
            "pass": False,
            "sourceId": source_id,
            "stage": stage,
            "proxyMode": proxy_mode,
            "keyword": keyword,
        }

        t0 = time.perf_counter()
        try:
            if stage == "search":
                items, err = await executor.search(source, source_id, keyword, page)
                latency_ms = int((time.perf_counter() - t0) * 1000)
                meta = executor.get_last_meta()
                if err:
                    result["error"] = err.error
                    result["proxyUsed"] = meta.get("proxyUsed", False)
                    result["latencyMs"] = latency_ms
                    # Don't auto-disable on test failure, just record
                    self._record_attempt(source_id, "test_search", "", meta.get("proxyUsed", False), False, latency_ms, err.error)
                else:
                    result["pass"] = True
                    result["itemsCount"] = len(items)
                    result["sample"] = [item.model_dump() for item in items[:3]]
                    result["proxyUsed"] = meta.get("proxyUsed", False)
                    result["latencyMs"] = latency_ms
                    self._record_attempt(source_id, "test_search", "", meta.get("proxyUsed", False), True, latency_ms)
                    self.repo.record_success(source_id, latency_ms)

            elif stage == "detail":
                # Use bookUrl from source if available, otherwise fail
                book_url = source.get("sourceUrl", "")
                if not book_url:
                    result["error"] = "缺少书源URL"
                else:
                    detail, err = await executor.book_detail(source, source_id, book_url)
                    latency_ms = int((time.perf_counter() - t0) * 1000)
                    meta = executor.get_last_meta()
                    if err:
                        result["error"] = err.error
                        result["proxyUsed"] = meta.get("proxyUsed", False)
                        result["latencyMs"] = latency_ms
                        self._record_attempt(source_id, "test_detail", book_url, meta.get("proxyUsed", False), False, latency_ms, err.error)
                    else:
                        result["pass"] = True
                        result["data"] = detail.model_dump() if detail else {}
                        result["proxyUsed"] = meta.get("proxyUsed", False)
                        result["latencyMs"] = latency_ms
                        self._record_attempt(source_id, "test_detail", book_url, meta.get("proxyUsed", False), True, latency_ms)
                        self.repo.record_success(source_id, latency_ms)

            elif stage == "toc":
                book_url = source.get("sourceUrl", "")
                if not book_url:
                    result["error"] = "缺少书源URL"
                else:
                    detail, _ = await executor.book_detail(source, source_id, book_url)
                    toc_url = detail.tocUrl if detail else book_url
                    chapters, err = await executor.toc(source, source_id, toc_url)
                    latency_ms = int((time.perf_counter() - t0) * 1000)
                    meta = executor.get_last_meta()
                    if err:
                        result["error"] = err.error
                        result["proxyUsed"] = meta.get("proxyUsed", False)
                        result["latencyMs"] = latency_ms
                        self._record_attempt(source_id, "test_toc", toc_url, meta.get("proxyUsed", False), False, latency_ms, err.error)
                    else:
                        result["pass"] = True
                        result["chaptersCount"] = len(chapters)
                        result["proxyUsed"] = meta.get("proxyUsed", False)
                        result["latencyMs"] = latency_ms
                        self._record_attempt(source_id, "test_toc", toc_url, meta.get("proxyUsed", False), True, latency_ms)
                        self.repo.record_success(source_id, latency_ms)

            elif stage == "content":
                # For content test, need a chapter URL. Try to get one from TOC.
                book_url = source.get("sourceUrl", "")
                if not book_url:
                    result["error"] = "缺少书源URL"
                else:
                    detail, _ = await executor.book_detail(source, source_id, book_url)
                    toc_url = detail.tocUrl if detail else book_url
                    chapters, err = await executor.toc(source, source_id, toc_url)
                    if err or not chapters:
                        result["error"] = err.error if err else "目录为空，无法测试正文"
                    else:
                        chapter_url = chapters[0].chapterUrl
                        content, err = await executor.content(source, source_id, chapter_url)
                        latency_ms = int((time.perf_counter() - t0) * 1000)
                        meta = executor.get_last_meta()
                        if err:
                            result["error"] = err.error
                            result["proxyUsed"] = meta.get("proxyUsed", False)
                            result["latencyMs"] = latency_ms
                            self._record_attempt(source_id, "test_content", chapter_url, meta.get("proxyUsed", False), False, latency_ms, err.error)
                        else:
                            result["pass"] = True
                            result["contentLength"] = len(content.content) if content else 0
                            result["proxyUsed"] = meta.get("proxyUsed", False)
                            result["latencyMs"] = latency_ms
                            self._record_attempt(source_id, "test_content", chapter_url, meta.get("proxyUsed", False), True, latency_ms)
                            self.repo.record_success(source_id, latency_ms)

            else:
                result["error"] = f"未知测试阶段: {stage}"

        except asyncio.TimeoutError:
            result["error"] = "timeout"
            result["latencyMs"] = int((time.perf_counter() - t0) * 1000)
            self._record_attempt(source_id, f"test_{stage}", "", False, False, result["latencyMs"], "timeout")
        except Exception as e:
            result["error"] = str(e)
            result["latencyMs"] = int((time.perf_counter() - t0) * 1000)
            self._record_attempt(source_id, f"test_{stage}", "", False, False, result["latencyMs"], str(e))
        finally:
            await executor.close()

        # Update test result in DB
        self.repo.update_test_result(source_id, result)
        return result
