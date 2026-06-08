"""Real-source live acceptance and candidate verification service."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

from app.services.browser_challenge import BrowserChallengeService
from app.services.live_check_repository import LiveCheckRepository
from app.source_plugins.scheduler import PluginScheduler


def normalize_text(value: str) -> str:
    return "".join((value or "").lower().split())


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
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for raw in items:
        item = dict(raw)
        item.setdefault("candidateId", candidate_id_for(item))
        score, reasons = score_candidate(item, keyword)
        item["score"] = max(int(item.get("score", 0) or 0), score)
        item["scoreReasons"] = reasons
        key = (normalize_text(item.get("name", "")), normalize_text(item.get("author", "")))
        if not key[0]:
            key = (item["candidateId"], "")
        groups.setdefault(key, []).append(item)

    result: list[dict[str, Any]] = []
    for index, ((name_key, author_key), group_items) in enumerate(groups.items(), start=1):
        best = max(group_items, key=lambda candidate: candidate.get("score", 0))
        source_items = sorted(group_items, key=lambda candidate: -candidate.get("score", 0))
        source_ids = sorted({item.get("sourceId", "") for item in group_items if item.get("sourceId")})
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
        self.scheduler = scheduler or PluginScheduler()
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
                    if (plugin.metadata.browser or {}).get("searchFallback") != "search_engine":
                        raise
                    browser_challenges = self._browser_challenges_for_exception(plugin, "explore", exc)
                    diagnostics.append(self._diag(
                        plugin_id,
                        "explore",
                        getattr(exc, "code", "explore_unavailable"),
                        f"排行榜入口不可用，降级到搜索链路: {exc}",
                        extra={"browserChallenge": browser_challenges[0]} if browser_challenges else {},
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
            browser_challenges = self._browser_challenges_for_timeout(plugin, "runtime")
            diagnostics.append(self._diag(
                plugin_id,
                "runtime",
                "BROWSER_REQUIRED" if browser_challenges else "timeout",
                "书源调用超时，可能需要浏览器验证" if browser_challenges else "书源调用超时",
                extra={"browserChallenge": browser_challenges[0]} if browser_challenges else {},
            ))
            result = self._result(
                plugin_id, keyword, "timeout", search_items, selected, detail, toc_items, chapter, started, diagnostics,
                explore_groups=explore_groups, explore_items=explore_items, explore_selected=explore_selected,
                explore_detail=explore_detail, explore_toc_items=explore_toc_items, explore_chapter=explore_chapter,
                browser_challenges=browser_challenges,
            )
            return self.repository.record(result) if persist else result
        except Exception as exc:
            browser_challenges = self._browser_challenges_for_exception(plugin, "runtime", exc)
            diagnostics.append(self._diag(
                plugin_id,
                "runtime",
                getattr(exc, "code", "plugin_exception"),
                str(exc),
                extra={"browserChallenge": browser_challenges[0]} if browser_challenges else {},
            ))
            result = self._result(
                plugin_id, keyword, "failed", search_items, selected, detail, toc_items, chapter, started, diagnostics,
                explore_groups=explore_groups, explore_items=explore_items, explore_selected=explore_selected,
                explore_detail=explore_detail, explore_toc_items=explore_toc_items, explore_chapter=explore_chapter,
                browser_challenges=browser_challenges,
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
    ) -> dict[str, Any]:
        plugin_id = candidate.get("sourceId", "")
        plugin = self.scheduler._plugins.get(plugin_id)
        diagnostics: list[dict[str, Any]] = []
        started = time.perf_counter()
        if not plugin:
            return self._failed(plugin_id, keyword, "plugin_not_found", "插件不存在", started, diagnostics)
        ctx = self.scheduler._make_ctx(plugin_id)
        timeout = self._timeout_for_plugin(plugin)
        detail: dict[str, Any] = {}
        toc_items: list[dict[str, Any]] = []
        chapter: dict[str, Any] = {}
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
            else:
                diagnostics.append(self._diag(plugin_id, "toc", "toc_empty", "目录为空"))
            status = "passed" if len(chapter.get("content", "") or "") > 500 else "failed"
            return self._result(plugin_id, keyword, status, [candidate], candidate, detail, toc_items, chapter, started, diagnostics)
        except asyncio.TimeoutError:
            diagnostics.append(self._diag(plugin_id, "runtime", "timeout", "候选验证超时"))
            return self._result(plugin_id, keyword, "timeout", [candidate], candidate, detail, toc_items, chapter, started, diagnostics)
        except Exception as exc:
            browser_challenges = self._browser_challenges_for_exception(plugin, "runtime", exc)
            diagnostics.append(self._diag(
                plugin_id,
                "runtime",
                getattr(exc, "code", "plugin_exception"),
                str(exc),
                extra={"browserChallenge": browser_challenges[0]} if browser_challenges else {},
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
                browser_challenges=browser_challenges,
            )
        finally:
            await ctx._fetcher.close()

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
        explore_groups: list[dict[str, Any]] | None = None,
        explore_items: list[dict[str, Any]] | None = None,
        explore_selected: dict[str, Any] | None = None,
        explore_detail: dict[str, Any] | None = None,
        explore_toc_items: list[dict[str, Any]] | None = None,
        explore_chapter: dict[str, Any] | None = None,
        browser_challenges: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        content = chapter.get("content", "") or ""
        explore_groups = explore_groups or []
        explore_items = explore_items or []
        explore_selected = explore_selected or {}
        explore_detail = explore_detail or {}
        explore_toc_items = explore_toc_items or []
        explore_chapter = explore_chapter or {}
        browser_challenges = browser_challenges or []
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
            "diagnostics": diagnostics,
            "browserChallenges": browser_challenges,
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

    def _browser_challenges_for_exception(self, plugin, stage: str, exc: Exception) -> list[dict[str, Any]]:
        code = getattr(exc, "code", "")
        if code not in {"CLOUDFLARE_REQUIRED", "BROWSER_REQUIRED"}:
            return []
        challenge = BrowserChallengeService().create_for_plugin(
            plugin,
            stage=stage,
            url=getattr(exc, "url", "") or "",
            reason=code,
            message=str(exc),
        )
        return [challenge]

    def _browser_challenges_for_timeout(self, plugin, stage: str) -> list[dict[str, Any]]:
        browser_mode = (plugin.metadata.browser or {}).get("mode", "")
        if browser_mode not in {"required", "optional"}:
            return []
        challenge = BrowserChallengeService().create_for_plugin(
            plugin,
            stage=stage,
            reason="BROWSER_REQUIRED",
            message="书源调用超时，可能停在浏览器验证或需要重新完成浏览器态访问。",
        )
        return [challenge]
