"""Real-source live acceptance and candidate verification service."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

from app.services.live_check_repository import LiveCheckRepository
from app.source_plugins.scheduler import PluginScheduler, get_plugin_scheduler
from app.source_plugins.loader import PluginLoader


def normalize_text(value: str) -> str:
    return "".join((value or "").lower().split())


def normalize_author_key(value: str) -> str:
    author = normalize_text(value)
    if author in {"", "佚名", "未知", "未知作者", "匿名", "作者", "不详"}:
        return ""
    return author


def candidate_id_for(item: dict[str, Any]) -> str:
    raw = "|".join(
        [
            item.get("sourceId", ""),
            item.get("bookUrl", ""),
            item.get("name", ""),
            item.get("author", ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def score_candidate(item: dict[str, Any], keyword: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    name = item.get("name", "")
    author = item.get("author", "")
    normalized_name = normalize_text(name)
    normalized_keyword = normalize_text(keyword)
    if normalized_keyword and normalized_keyword == normalized_name:
        score += 200
        reasons.append("exact_title")
    elif normalized_keyword and normalized_keyword in normalized_name:
        score += 100
        reasons.append("title_contains_keyword")
    if author:
        score += 10
        reasons.append("has_author")
    if item.get("lastChapter"):
        score += 8
        reasons.append("has_latest_chapter")
    if item.get("intro"):
        score += 3
        reasons.append("has_intro")
    return score, reasons


def group_candidates(items: list[dict[str, Any]], keyword: str) -> list[dict[str, Any]]:
    try:
        plugins = PluginLoader().load_all()
    except Exception:
        plugins = {}

    def is_official(source_id: str) -> bool:
        plugin = plugins.get(source_id)
        return bool(plugin and plugin.metadata.is_official_source())

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    unresolved_by_name: dict[str, list[dict[str, Any]]] = {}
    for raw in items:
        item = dict(raw)
        item.setdefault("candidateId", candidate_id_for(item))
        score, reasons = score_candidate(item, keyword)
        item["score"] = max(int(item.get("score", 0) or 0), score)
        item["scoreReasons"] = reasons
        name_key = normalize_text(item.get("name", ""))
        author_key = normalize_author_key(item.get("author", ""))
        if not name_key:
            groups.setdefault((item["candidateId"], ""), []).append(item)
            continue
        if not author_key:
            unresolved_by_name.setdefault(name_key, []).append(item)
            continue
        groups.setdefault((name_key, author_key), []).append(item)

    for name_key, unresolved_items in unresolved_by_name.items():
        matching_keys = [key for key in groups if key[0] == name_key]
        if not matching_keys:
            groups[(name_key, "")] = list(unresolved_items)
            continue
        if len(matching_keys) == 1:
            groups[matching_keys[0]].extend(unresolved_items)
            continue
        best_key = max(
            matching_keys,
            key=lambda key: max(item.get("score", 0) for item in groups[key]),
        )
        groups[best_key].extend(unresolved_items)

    result: list[dict[str, Any]] = []
    for index, ((name_key, author_key), group_items) in enumerate(groups.items(), start=1):
        best = max(
            group_items,
            key=lambda candidate: (
                1 if is_official(candidate.get("sourceId", "")) else 0,
                candidate.get("score", 0),
            ),
        )
        source_items = sorted(group_items, key=lambda candidate: -candidate.get("score", 0))
        source_ids = sorted({item.get("sourceId", "") for item in group_items if item.get("sourceId")})
        official_items = [item for item in group_items if is_official(item.get("sourceId", ""))]
        group_id = hashlib.sha256(
            f"{name_key}|{author_key}|{'|'.join(source_ids)}".encode("utf-8")
        ).hexdigest()[:24]
        result.append(
            {
                "candidateId": group_id,
                "rank": index,
                "name": best.get("name", ""),
                "author": best.get("author", ""),
                "latestChapter": best.get("lastChapter", ""),
                "kind": best.get("kind", ""),
                "intro": best.get("intro", ""),
                "score": best.get("score", 0),
                "scoreReasons": best.get("scoreReasons", []),
                "sourceCount": len(source_ids),
                "bestSourceId": best.get("sourceId", ""),
                "hasOfficialSource": bool(official_items),
                "officialSourceIds": sorted({item.get("sourceId", "") for item in official_items if item.get("sourceId")}),
                "primaryOfficialSourceId": official_items[0].get("sourceId", "") if official_items else "",
                "isPrimarySourceOfficial": is_official(best.get("sourceId", "")),
                "items": source_items,
            }
        )
    result.sort(key=lambda group: (-group.get("score", 0), group.get("name", "")))
    for index, group in enumerate(result, start=1):
        group["rank"] = index
    return result


class LiveAcceptanceService:
    """Run real source search/detail/toc/chapter checks."""

    def __init__(
        self,
        scheduler: PluginScheduler | None = None,
        repository: LiveCheckRepository | None = None,
    ):
        self.scheduler = scheduler or get_plugin_scheduler()
        self.repository = repository or LiveCheckRepository()

    async def run_plugin_live_check(
        self,
        plugin_id: str,
        keyword: str = "凡人修仙传",
        candidate_index: int = 0,
        chapter_index: int = 0,
        persist: bool = True,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        diagnostics: list[dict[str, Any]] = []
        plugin = self.scheduler._plugins.get(plugin_id)
        if not plugin:
            result = self._failed(plugin_id, keyword, "plugin_not_found", "插件不存在", started, diagnostics)
            return self.repository.record(result) if persist else result
        if "search" not in plugin.capabilities:
            result = self._failed(plugin_id, keyword, "search_not_supported", "插件不支持搜索", started, diagnostics)
            return self.repository.record(result) if persist else result

        search_items: list[dict[str, Any]] = []
        explore_groups: list[dict[str, Any]] = []
        explore_items: list[dict[str, Any]] = []
        explore_selected: dict[str, Any] = {}
        explore_detail: dict[str, Any] = {}
        explore_toc_items: list[dict[str, Any]] = []
        explore_chapter: dict[str, Any] = {}
        detail: dict[str, Any] = {}
        toc_items: list[dict[str, Any]] = []
        chapter: dict[str, Any] = {}
        selected: dict[str, Any] = {}

        ctx = self.scheduler._make_ctx(plugin_id)
        timeout = self._timeout_for_plugin(plugin)
        try:
            effective_keyword = keyword
            if "explore" in plugin.capabilities:
                try:
                    explore_groups = await asyncio.wait_for(plugin.source.explore_groups(ctx), timeout=timeout)
                    explore_groups = [item for item in explore_groups or [] if isinstance(item, dict)]
                    if not explore_groups:
                        diagnostics.append(self._diag(plugin_id, "explore_groups", "explore_groups_empty", "发现/排行榜分组为空"))
                        result = self._result(
                            plugin_id, keyword, "failed", search_items, selected, detail, toc_items, chapter, started, diagnostics,
                            explore_groups=explore_groups, explore_items=explore_items, explore_selected=explore_selected,
                            explore_detail=explore_detail, explore_toc_items=explore_toc_items, explore_chapter=explore_chapter,
                        )
                        return self.repository.record(result) if persist else result
                    group = explore_groups[min(max(candidate_index, 0), len(explore_groups) - 1)]
                    group_id = group.get("groupId", "")
                    explore_items = await asyncio.wait_for(plugin.source.explore(ctx, group_id, 1), timeout=timeout)
                    explore_items = [item for item in explore_items or [] if isinstance(item, dict)]
                    for item in explore_items:
                        item.setdefault("sourceId", plugin_id)
                        item.setdefault("sourceName", plugin.metadata.name)
                        item.setdefault("groupId", group_id)
                        item.setdefault("groupTitle", group.get("title", ""))
                    if not explore_items:
                        diagnostics.append(self._diag(plugin_id, "explore", "explore_empty", "发现/排行榜无书籍"))
                        result = self._result(
                            plugin_id, keyword, "failed", search_items, selected, detail, toc_items, chapter, started, diagnostics,
                            explore_groups=explore_groups, explore_items=explore_items, explore_selected=explore_selected,
                            explore_detail=explore_detail, explore_toc_items=explore_toc_items, explore_chapter=explore_chapter,
                        )
                        return self.repository.record(result) if persist else result
                    explore_selected = explore_items[0]
                    explore_detail, explore_toc_items, explore_chapter = await self._read_candidate(
                        plugin, ctx, explore_selected, chapter_index, timeout
                    )
                    explore_content_length = len(explore_chapter.get("content", "") or "")
                    if explore_content_length <= 500:
                        diagnostics.append(self._diag(plugin_id, "explore_chapter", "chapter_too_short", f"排行榜正文长度不足: {explore_content_length}"))
                    if not explore_selected.get("name"):
                        diagnostics.append(self._diag(plugin_id, "explore", "explore_name_empty", "排行榜书名为空，无法进入搜索闭环"))
                        result = self._result(
                            plugin_id, keyword, "failed", search_items, selected, detail, toc_items, chapter, started, diagnostics,
                            explore_groups=explore_groups, explore_items=explore_items, explore_selected=explore_selected,
                            explore_detail=explore_detail, explore_toc_items=explore_toc_items, explore_chapter=explore_chapter,
                        )
                        return self.repository.record(result) if persist else result
                    effective_keyword = explore_selected.get("name", keyword)
                except Exception as exc:
                    if not plugin.metadata.uses_search_provider("search"):
                        raise
                    diagnostics.append(self._diag(
                        plugin_id,
                        "explore",
                        getattr(exc, "code", "explore_unavailable"),
                        f"排行榜入口不可用，降级到搜索链路: {exc}",
                        extra=self._bypass_extra_for_exception(exc),
                    ))

            search_items = await asyncio.wait_for(
                plugin.source.search(ctx, effective_keyword, 1),
                timeout=timeout,
            )
            search_items = [item for item in search_items or [] if isinstance(item, dict)]
            for item in search_items:
                item.setdefault("sourceId", plugin_id)
                item.setdefault("sourceName", plugin.metadata.name)
            if not search_items:
                diagnostics.append(self._diag(plugin_id, "search", "empty_search", "搜索无结果"))
                result = self._result(
                    plugin_id, effective_keyword, "failed", search_items, selected, detail, toc_items, chapter, started, diagnostics,
                    explore_groups=explore_groups, explore_items=explore_items, explore_selected=explore_selected,
                    explore_detail=explore_detail, explore_toc_items=explore_toc_items, explore_chapter=explore_chapter,
                )
                return self.repository.record(result) if persist else result

            groups = group_candidates(search_items, effective_keyword)
            ranked_items = [item for group in groups for item in group.get("items", [])]
            selected = ranked_items[min(max(candidate_index, 0), len(ranked_items) - 1)]
            if explore_selected and effective_keyword not in selected.get("name", ""):
                diagnostics.append(self._diag(
                    plugin_id,
                    "search",
                    "search_candidate_mismatch",
                    f"搜索闭环未选回排行榜书籍: {effective_keyword} -> {selected.get('name', '')}",
                ))

            detail, toc_items, chapter = await self._read_candidate(plugin, ctx, selected, chapter_index, timeout)
            if not toc_items:
                diagnostics.append(self._diag(plugin_id, "toc", "toc_empty", "目录为空"))
                result = self._result(
                    plugin_id, effective_keyword, "failed", search_items, selected, detail, toc_items, chapter, started, diagnostics,
                    explore_groups=explore_groups, explore_items=explore_items, explore_selected=explore_selected,
                    explore_detail=explore_detail, explore_toc_items=explore_toc_items, explore_chapter=explore_chapter,
                )
                return self.repository.record(result) if persist else result

            content_length = len(chapter.get("content", "") or "")
            if content_length <= 500:
                diagnostics.append(self._diag(plugin_id, "chapter", "chapter_too_short", f"正文长度不足: {content_length}"))
            explore_passed = not explore_selected or len(explore_chapter.get("content", "") or "") > 500
            search_match = not explore_selected or effective_keyword in selected.get("name", "")
            status = "passed" if content_length > 500 and explore_passed and search_match else "failed"
            result = self._result(
                plugin_id, effective_keyword, status, search_items, selected, detail, toc_items, chapter, started, diagnostics,
                explore_groups=explore_groups, explore_items=explore_items, explore_selected=explore_selected,
                explore_detail=explore_detail, explore_toc_items=explore_toc_items, explore_chapter=explore_chapter,
            )
            return self.repository.record(result) if persist else result
        except asyncio.TimeoutError:
            diagnostics.append(self._diag(
                plugin_id,
                "runtime",
                "BROWSER_REQUIRED" if self._timeout_requires_bypass(plugin) else "timeout",
                "书源调用超时，后续应走绕过策略" if self._timeout_requires_bypass(plugin) else "书源调用超时",
                extra={"bypassRequired": True, "bypassStrategy": "skip_source_until_bypass_available"} if self._timeout_requires_bypass(plugin) else {},
            ))
            result = self._result(
                plugin_id, keyword, "timeout", search_items, selected, detail, toc_items, chapter, started, diagnostics,
                explore_groups=explore_groups, explore_items=explore_items, explore_selected=explore_selected,
                explore_detail=explore_detail, explore_toc_items=explore_toc_items, explore_chapter=explore_chapter,
            )
            return self.repository.record(result) if persist else result
        except Exception as exc:
            diagnostics.append(self._diag(
                plugin_id,
                "runtime",
                getattr(exc, "code", "plugin_exception"),
                str(exc),
                extra=self._bypass_extra_for_exception(exc),
            ))
            result = self._result(
                plugin_id, keyword, "failed", search_items, selected, detail, toc_items, chapter, started, diagnostics,
                explore_groups=explore_groups, explore_items=explore_items, explore_selected=explore_selected,
                explore_detail=explore_detail, explore_toc_items=explore_toc_items, explore_chapter=explore_chapter,
            )
            return self.repository.record(result) if persist else result
        finally:
            await ctx._fetcher.close()

    async def _read_candidate(
        self,
        plugin,
        ctx,
        candidate: dict[str, Any],
        chapter_index: int,
        timeout: float,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        detail: dict[str, Any] = {}
        if "detail" in plugin.capabilities:
            detail = await asyncio.wait_for(
                plugin.source.detail(ctx, candidate.get("bookUrl", "")),
                timeout=timeout,
            )
            if not isinstance(detail, dict):
                detail = {}
        toc_url = detail.get("tocUrl") or candidate.get("tocUrl") or candidate.get("bookUrl", "")
        if not toc_url:
            return detail, [], {}
        toc_items = await asyncio.wait_for(plugin.source.toc(ctx, toc_url), timeout=timeout)
        toc_items = [item for item in toc_items or [] if isinstance(item, dict)]
        if not toc_items:
            return detail, toc_items, {}
        chapter_item = toc_items[min(max(chapter_index, 0), len(toc_items) - 1)]
        chapter = await asyncio.wait_for(plugin.source.chapter(ctx, chapter_item.get("chapterUrl", "")), timeout=timeout)
        if not isinstance(chapter, dict):
            chapter = {}
        return detail, toc_items, chapter

    async def verify_candidate(
        self,
        candidate: dict[str, Any],
        keyword: str = "",
        chapter_index: int = 0,
        include_reviews: bool = True,
    ) -> dict[str, Any]:
        plugin_id = candidate.get("sourceId", "")
        plugin = self.scheduler._plugins.get(plugin_id)
        diagnostics: list[dict[str, Any]] = []
        started = time.perf_counter()
        if not plugin:
            return self._failed(plugin_id, keyword, "plugin_not_found", "插件不存在", started, diagnostics)

        # For interactive console preview we prefer fresh chapter rendering so
        #正文清洗/分段调整能立即反映，不被旧 chapter_cache 长时间遮住。
        from app.services.catalog import Catalog
        from app.source_plugins.id_codec import encode_book_id
        catalog = Catalog()
        book_id = candidate.get("bookId") or encode_book_id(plugin_id, candidate.get("bookUrl", ""))
        cached_detail = catalog.cache.get_book(book_id)
        if cached_detail and cached_detail.get("data"):
            detail = dict(cached_detail["data"])
            toc_result = catalog.cache.get_toc(book_id)
            if toc_result:
                toc_items = toc_result.get("chapters") or toc_result.get("items") or []
                toc_items = [dict(item) for item in toc_items if isinstance(item, dict)]
                if detail and toc_items:
                    diagnostics.append(self._diag(plugin_id, "cache", "chapter_cache_bypassed", "控制台预览跳过旧章节缓存，强制重新拉取正文"))

        ctx = self.scheduler._make_ctx(plugin_id)
        timeout = self._timeout_for_plugin(plugin)
        detail: dict[str, Any] = {}
        toc_items: list[dict[str, Any]] = []
        chapter: dict[str, Any] = {}
        reviews: dict[str, Any] = {"paragraphs": {}, "chapterEnd": [], "chapterEndHot": [], "authorReviews": [], "summary": {}}
        try:
            if "detail" in plugin.capabilities:
                detail = await asyncio.wait_for(
                    plugin.source.detail(ctx, candidate.get("bookUrl", "")),
                    timeout=timeout,
                )
                if not isinstance(detail, dict):
                    detail = {}
            toc_url = detail.get("tocUrl") or candidate.get("tocUrl") or candidate.get("bookUrl", "")
            toc_items = await asyncio.wait_for(plugin.source.toc(ctx, toc_url), timeout=timeout)
            toc_items = [item for item in toc_items or [] if isinstance(item, dict)]
            if toc_items:
                chapter_item = toc_items[min(max(chapter_index, 0), len(toc_items) - 1)]
                chapter = await asyncio.wait_for(
                    plugin.source.chapter(ctx, chapter_item.get("chapterUrl", "")),
                    timeout=timeout,
                )
                if not isinstance(chapter, dict):
                    chapter = {}
                if include_reviews and "chapter_reviews" in plugin.capabilities:
                    try:
                        review_source_url = chapter.get("chapterUrl") or chapter_item.get("chapterUrl", "")
                        if review_source_url:
                            fetched_reviews = await asyncio.wait_for(
                                plugin.source.chapter_reviews(ctx, review_source_url),
                                timeout=timeout,
                            )
                            if isinstance(fetched_reviews, dict):
                                reviews = {
                                    "paragraphs": fetched_reviews.get("paragraphs", {}),
                                    "chapterEnd": fetched_reviews.get("chapterEnd", []),
                                    "summary": fetched_reviews.get("summary", {}),
                                    "debug": fetched_reviews.get("debug", {}),
                                }
                    except Exception as exc:
                        diagnostics.append(self._diag(
                            plugin_id,
                            "reviews",
                            getattr(exc, "code", "reviews_unavailable"),
                            f"本章说获取失败: {exc}",
                            extra=self._bypass_extra_for_exception(exc),
                        ))
            else:
                diagnostics.append(self._diag(plugin_id, "toc", "toc_empty", "目录为空"))
            status = "passed" if len(chapter.get("content", "") or "") > 500 else "failed"
            result = self._result(plugin_id, keyword, status, [candidate], candidate, detail, toc_items, chapter, started, diagnostics, reviews=reviews)
            # Write to cache for subsequent fast reads
            if detail and toc_items:
                self._write_verify_cache(book_id, plugin_id, candidate, detail, toc_items, chapter)
            return result
        except asyncio.TimeoutError:
            diagnostics.append(self._diag(plugin_id, "runtime", "timeout", "候选验证超时"))
            return self._result(plugin_id, keyword, "timeout", [candidate], candidate, detail, toc_items, chapter, started, diagnostics, reviews=reviews)
        except Exception as exc:
            diagnostics.append(self._diag(
                plugin_id,
                "runtime",
                getattr(exc, "code", "plugin_exception"),
                str(exc),
                extra=self._bypass_extra_for_exception(exc),
            ))
            return self._result(
                plugin_id,
                keyword,
                "failed",
                [candidate],
                candidate,
                detail,
                toc_items,
                chapter,
                started,
                diagnostics,
                reviews=reviews,
            )
        finally:
            await ctx._fetcher.close()

    async def fetch_reviews(
        self,
        candidate: dict[str, Any],
        chapter_index: int = 0,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Fetch chapter reviews independently of chapter content.

        This is intended for VIP chapters where the main text may only be a
        preview, but reviews are still publicly available. Reviews are fetched
        directly from the source's chapter_reviews capability using cached
        detail/toc when available.
        """
        plugin_id = candidate.get("sourceId", "")
        plugin = self.scheduler._plugins.get(plugin_id)
        diagnostics: list[dict[str, Any]] = []
        started = time.perf_counter()
        reviews: dict[str, Any] = {"paragraphs": {}, "chapterEnd": [], "chapterEndHot": [], "authorReviews": [], "summary": {}}

        if not plugin:
            return {
                "ok": False,
                "error": "插件不存在",
                "pluginId": plugin_id,
                "reviews": reviews,
                "diagnostics": diagnostics,
                "elapsedMs": round((time.perf_counter() - started) * 1000),
            }

        from app.services.catalog import Catalog
        from app.source_plugins.id_codec import encode_book_id
        catalog = Catalog()
        book_url = candidate.get("bookUrl", "")
        book_id = candidate.get("bookId") or encode_book_id(plugin_id, book_url)

        ctx = self.scheduler._make_ctx(plugin_id)
        effective_timeout = timeout if timeout is not None else self._timeout_for_plugin(plugin)
        detail: dict[str, Any] = {}
        toc_items: list[dict[str, Any]] = []
        chapter_item: dict[str, Any] = {}

        try:
            # Prefer cached detail/toc to avoid redundant work.
            cached_detail = catalog.cache.get_book(book_id)
            if isinstance(cached_detail, dict) and cached_detail.get("data"):
                detail = dict(cached_detail["data"])
                diagnostics.append(self._diag(plugin_id, "cache", "book_cache_hit", "书评请求命中书籍详情缓存"))

            cached_toc = catalog.cache.get_toc(book_id)
            if isinstance(cached_toc, dict):
                toc_items = cached_toc.get("chapters") or cached_toc.get("items") or []
                toc_items = [dict(item) for item in toc_items if isinstance(item, dict)]
                if toc_items:
                    diagnostics.append(self._diag(plugin_id, "cache", "toc_cache_hit", "书评请求命中目录缓存"))

            if not detail and "detail" in plugin.capabilities:
                detail = await asyncio.wait_for(
                    plugin.source.detail(ctx, book_url),
                    timeout=effective_timeout,
                )
                if not isinstance(detail, dict):
                    detail = {}

            if not toc_items and "toc" in plugin.capabilities:
                toc_url = detail.get("tocUrl") or book_url
                toc_items = await asyncio.wait_for(
                    plugin.source.toc(ctx, toc_url),
                    timeout=effective_timeout,
                )
                toc_items = [dict(item) for item in toc_items or [] if isinstance(item, dict)]

            if not toc_items:
                diagnostics.append(self._diag(plugin_id, "toc", "toc_empty", "目录为空"))
                return {
                    "ok": False,
                    "error": "目录为空",
                    "pluginId": plugin_id,
                    "reviews": reviews,
                    "diagnostics": diagnostics,
                    "elapsedMs": round((time.perf_counter() - started) * 1000),
                }

            chapter_item = toc_items[min(max(chapter_index, 0), len(toc_items) - 1)]
            chapter_url = chapter_item.get("chapterUrl", "")

            if "chapter_reviews" not in plugin.capabilities:
                diagnostics.append(self._diag(plugin_id, "reviews", "capability_missing", "书源未实现 chapter_reviews"))
                return {
                    "ok": False,
                    "error": "书源未实现本章说",
                    "pluginId": plugin_id,
                    "chapterIndex": chapter_index,
                    "chapterUrl": chapter_url,
                    "reviews": reviews,
                    "diagnostics": diagnostics,
                    "elapsedMs": round((time.perf_counter() - started) * 1000),
                }

            if chapter_url:
                fetched_reviews = await asyncio.wait_for(
                    plugin.source.chapter_reviews(ctx, chapter_url),
                    timeout=effective_timeout,
                )
                if isinstance(fetched_reviews, dict):
                    reviews = {
                        "paragraphs": fetched_reviews.get("paragraphs", {}),
                        "chapterEnd": fetched_reviews.get("chapterEnd", []),
                        "chapterEndHot": fetched_reviews.get("chapterEndHot", []),
                        "authorReviews": fetched_reviews.get("authorReviews", []),
                        "summary": fetched_reviews.get("summary", {}),
                        "debug": fetched_reviews.get("debug", {}),
                    }
            else:
                diagnostics.append(self._diag(plugin_id, "reviews", "chapter_url_missing", "章节 URL 为空"))

            return {
                "ok": True,
                "pluginId": plugin_id,
                "candidateId": candidate.get("candidateId") or candidate_id_for(candidate),
                "chapterIndex": chapter_index,
                "chapterUrl": chapter_url,
                "reviews": reviews,
                "diagnostics": diagnostics,
                "elapsedMs": round((time.perf_counter() - started) * 1000),
            }
        except asyncio.TimeoutError:
            diagnostics.append(self._diag(plugin_id, "runtime", "timeout", "本章说获取超时"))
            return {
                "ok": False,
                "error": "timeout",
                "pluginId": plugin_id,
                "chapterIndex": chapter_index,
                "chapterUrl": chapter_item.get("chapterUrl", ""),
                "reviews": reviews,
                "diagnostics": diagnostics,
                "elapsedMs": round((time.perf_counter() - started) * 1000),
            }
        except Exception as exc:
            diagnostics.append(self._diag(
                plugin_id,
                "runtime",
                getattr(exc, "code", "plugin_exception"),
                f"本章说获取失败: {exc}",
                extra=self._bypass_extra_for_exception(exc),
            ))
            return {
                "ok": False,
                "error": str(exc),
                "pluginId": plugin_id,
                "chapterIndex": chapter_index,
                "chapterUrl": chapter_item.get("chapterUrl", ""),
                "reviews": reviews,
                "diagnostics": diagnostics,
                "elapsedMs": round((time.perf_counter() - started) * 1000),
            }
        finally:
            await ctx._fetcher.close()

    def _write_verify_cache(
        self,
        book_id: str,
        plugin_id: str,
        candidate: dict[str, Any],
        detail: dict[str, Any],
        toc_items: list[dict[str, Any]],
        chapter: dict[str, Any],
    ) -> None:
        from app.services.catalog import Catalog
        from app.config import HOST, PORT
        from app.source_plugins.id_codec import encode_chapter_id
        catalog = Catalog()
        base_api = f"http://{HOST}:{PORT}"
        book_url = candidate.get("bookUrl", "")
        # Cache book detail
        detail_response = {
            "implemented": True,
            "data": detail,
            "debug": {},
        }
        catalog.cache.set_book(book_id, plugin_id, book_url, detail_response)
        # Cache toc
        toc_response = {
            "implemented": True,
            "bookId": book_id,
            "chapters": toc_items,
            "debug": {},
        }
        catalog.cache.set_toc(book_id, toc_response)
        # Cache chapter
        chapter_url = chapter.get("chapterUrl", "")
        if chapter_url:
            chapter_id = encode_chapter_id(plugin_id, chapter_url)
            chapter_response = {
                "implemented": True,
                "chapterId": chapter_id,
                "title": chapter.get("title", ""),
                "content": chapter.get("content", ""),
                "debug": {},
            }
            catalog.cache.set_chapter(chapter_id, plugin_id, chapter_url, chapter_response)

    def _result(
        self,
        plugin_id: str,
        keyword: str,
        status: str,
        search_items: list[dict[str, Any]],
        selected: dict[str, Any],
        detail: dict[str, Any],
        toc_items: list[dict[str, Any]],
        chapter: dict[str, Any],
        started: float,
        diagnostics: list[dict[str, Any]],
        reviews: dict[str, Any] | None = None,
        explore_groups: list[dict[str, Any]] | None = None,
        explore_items: list[dict[str, Any]] | None = None,
        explore_selected: dict[str, Any] | None = None,
        explore_detail: dict[str, Any] | None = None,
        explore_toc_items: list[dict[str, Any]] | None = None,
        explore_chapter: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        content = chapter.get("content", "") or ""
        explore_groups = explore_groups or []
        explore_items = explore_items or []
        explore_selected = explore_selected or {}
        explore_detail = explore_detail or {}
        explore_toc_items = explore_toc_items or []
        explore_chapter = explore_chapter or {}
        reviews = reviews or {"paragraphs": {}, "chapterEnd": [], "summary": {}}
        explore_content = explore_chapter.get("content", "") or ""
        return {
            "pluginId": plugin_id,
            "keyword": keyword,
            "status": status,
            "passed": status == "passed",
            "explore": {
                "groupCount": len(explore_groups),
                "itemCount": len(explore_items),
                "groups": explore_groups,
                "selected": {
                    "sourceId": explore_selected.get("sourceId", ""),
                    "sourceName": explore_selected.get("sourceName", ""),
                    "name": explore_selected.get("name", ""),
                    "author": explore_selected.get("author", ""),
                    "bookUrl": explore_selected.get("bookUrl", ""),
                    "groupId": explore_selected.get("groupId", ""),
                    "groupTitle": explore_selected.get("groupTitle", ""),
                },
                "detailPassed": bool(explore_detail.get("name") or explore_detail.get("tocUrl")),
                "tocCount": len(explore_toc_items),
                "chapterTitle": explore_chapter.get("title", ""),
                "contentLength": len(explore_content),
                "passed": len(explore_content) > 500 if explore_groups or explore_items else None,
            },
            "search": {
                "count": len(search_items),
                "firstName": search_items[0].get("name", "") if search_items else "",
                "groups": group_candidates(search_items, keyword),
            },
            "selectedCandidate": {
                "candidateId": selected.get("candidateId") or candidate_id_for(selected) if selected else "",
                "sourceId": selected.get("sourceId", ""),
                "sourceName": selected.get("sourceName", ""),
                "name": selected.get("name", ""),
                "author": selected.get("author", ""),
                "bookUrl": selected.get("bookUrl", ""),
                "lastChapter": selected.get("lastChapter", ""),
            },
            "detail": {
                "name": detail.get("name", ""),
                "author": detail.get("author", ""),
                "coverUrl": detail.get("coverUrl", ""),
                "intro": detail.get("intro", ""),
                "kind": detail.get("kind", selected.get("kind", "") if selected else ""),
                "lastChapter": detail.get("lastChapter", selected.get("lastChapter", "") if selected else ""),
                "wordCount": detail.get("wordCount", selected.get("wordCount", "") if selected else ""),
                "wordCountText": detail.get("wordCountText", selected.get("wordCountText", "") if selected else ""),
                "bookUrl": detail.get("bookUrl", selected.get("bookUrl", "") if selected else ""),
                "tocUrl": detail.get("tocUrl", ""),
                "passed": bool(detail.get("name") or detail.get("tocUrl")),
            },
            "toc": {
                "chapterCount": len(toc_items),
                "count": len(toc_items),
                "firstTitle": toc_items[0].get("title", "") if toc_items else "",
                "items": toc_items,
                "passed": len(toc_items) > 0,
            },
            "chapter": {
                "title": chapter.get("title", ""),
                "chapterUrl": chapter.get("chapterUrl", ""),
                "contentLength": len(content),
                "preview": content[:300],
                "content": content,
                "passed": len(content) > 500,
            },
            "reviews": {
                "paragraphs": reviews.get("paragraphs", {}) if isinstance(reviews, dict) else {},
                "chapterEnd": reviews.get("chapterEnd", []) if isinstance(reviews, dict) else [],
                "summary": reviews.get("summary", {}) if isinstance(reviews, dict) else {},
                "debug": reviews.get("debug", {}) if isinstance(reviews, dict) else {},
                "passed": bool(
                    (reviews.get("paragraphs") if isinstance(reviews, dict) else {})
                    or (reviews.get("chapterEnd") if isinstance(reviews, dict) else [])
                    or (reviews.get("summary") if isinstance(reviews, dict) else {})
                ),
            },
            "diagnostics": diagnostics,
            "timings": {"elapsedMs": int((time.perf_counter() - started) * 1000)},
        }

    def _failed(
        self,
        plugin_id: str,
        keyword: str,
        code: str,
        message: str,
        started: float,
        diagnostics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        diagnostics.append(self._diag(plugin_id, "runtime", code, message))
        return self._result(plugin_id, keyword, "failed", [], {}, {}, [], {}, started, diagnostics)

    def _timeout_for_plugin(self, plugin) -> float:
        timeout_getter = getattr(self.scheduler, "timeout_for_plugin", None)
        if callable(timeout_getter):
            return float(timeout_getter(plugin))
        return float(getattr(self.scheduler, "config", {}).get("source_timeout_seconds", 8.0))

    def _diag(self, plugin_id: str, stage: str, code: str, message: str, extra: dict | None = None) -> dict[str, Any]:
        return {"sourceId": plugin_id, "stage": stage, "code": code, "message": message, "extra": extra or {}}

    def _bypass_extra_for_exception(self, exc: Exception) -> dict[str, Any]:
        code = getattr(exc, "code", "")
        if code not in {"CLOUDFLARE_REQUIRED", "BROWSER_REQUIRED"}:
            return {}
        return {"bypassRequired": True, "bypassStrategy": "skip_source_until_bypass_available"}

    def _timeout_requires_bypass(self, plugin) -> bool:
        browser_mode = (plugin.metadata.browser or {}).get("mode", "")
        return browser_mode in {"required", "optional"}


