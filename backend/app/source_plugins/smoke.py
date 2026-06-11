"""Smoke runners for validating plugins without using the Reading app."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import yaml

from app.source_plugins.context import PluginContext
from app.source_plugins.models import LoadedPlugin
from app.source_plugins.errors import normalize_failure


async def run_smoke(
    plugin: LoadedPlugin,
    ctx: PluginContext,
    keyword: str = "凡人修仙传",
) -> dict:
    result: dict = {
        "pluginId": plugin.metadata.id,
        "pass": False,
        "stages": {},
        "errors": [],
    }

    # Stage 1: Search
    search_items = []
    if "search" in plugin.capabilities:
        try:
            raw = await asyncio.wait_for(
                plugin.source.search(ctx, keyword, 1),
                timeout=15.0,
            )
            search_items = raw or []
            result["stages"]["search"] = {"count": len(search_items), "status": "ok"}
        except Exception as exc:
            result["stages"]["search"] = {"status": "error", "message": str(exc)}
            result["errors"].append({"stage": "search", "message": str(exc)})
    else:
        result["stages"]["search"] = {"status": "skipped", "reason": "no search capability"}

    if not search_items:
        result["pass"] = False
        if not result["errors"]:
            result["errors"].append({"stage": "search", "message": "no results"})
        return result

    # Pick first result
    first = search_items[0]
    book_url = first.get("bookUrl", "") if isinstance(first, dict) else ""
    if not book_url and hasattr(first, "book_url"):
        book_url = first.book_url

    # Stage 2: Detail
    detail_data = None
    if "detail" in plugin.capabilities and book_url:
        try:
            detail_data = await asyncio.wait_for(
                plugin.source.detail(ctx, book_url),
                timeout=15.0,
            )
            result["stages"]["detail"] = {"status": "ok"}
        except Exception as exc:
            result["stages"]["detail"] = {"status": "error", "message": str(exc)}
            result["errors"].append({"stage": "detail", "message": str(exc)})
    else:
        result["stages"]["detail"] = {"status": "skipped"}

    # Stage 3: TOC
    toc_url = book_url
    if detail_data and isinstance(detail_data, dict) and detail_data.get("tocUrl"):
        toc_url = detail_data["tocUrl"]
    chapters = []
    if "toc" in plugin.capabilities and toc_url:
        try:
            chapters = await asyncio.wait_for(
                plugin.source.toc(ctx, toc_url),
                timeout=15.0,
            )
            result["stages"]["toc"] = {"count": len(chapters), "status": "ok"}
        except Exception as exc:
            result["stages"]["toc"] = {"status": "error", "message": str(exc)}
            result["errors"].append({"stage": "toc", "message": str(exc)})
    else:
        result["stages"]["toc"] = {"status": "skipped"}

    # Stage 4: Chapter
    chapter_url = ""
    if chapters and len(chapters) > 0:
        first_ch = chapters[0]
        if isinstance(first_ch, dict):
            chapter_url = first_ch.get("chapterUrl", "")
        elif hasattr(first_ch, "chapter_url"):
            chapter_url = first_ch.chapter_url

    if "chapter" in plugin.capabilities and chapter_url:
        try:
            content = await asyncio.wait_for(
                plugin.source.chapter(ctx, chapter_url),
                timeout=15.0,
            )
            content_text = ""
            if isinstance(content, dict):
                content_text = content.get("content", "")
            elif hasattr(content, "content"):
                content_text = content.content
            result["stages"]["chapter"] = {
                "status": "ok",
                "contentLength": len(content_text),
            }
        except Exception as exc:
            result["stages"]["chapter"] = {"status": "error", "message": str(exc)}
            result["errors"].append({"stage": "chapter", "message": str(exc)})
    else:
        result["stages"]["chapter"] = {"status": "skipped"}

    # Assertions
    passes = True
    if "search" in plugin.capabilities and not search_items:
        passes = False
    if "detail" in plugin.capabilities and detail_data is None:
        passes = False
    if "toc" in plugin.capabilities and not chapters:
        passes = False
    if "chapter" in plugin.capabilities:
        content_len = result["stages"].get("chapter", {}).get("contentLength", 0)
        if content_len < 200:
            passes = False
            result["errors"].append({"stage": "chapter", "message": f"content too short: {content_len} chars"})

    result["pass"] = passes and len(result["errors"]) == 0
    return result


class FixtureFetcher:
    """Fetcher-compatible object backed by plugin smoke fixture files."""

    def __init__(self, url_to_text: dict[str, str]):
        self._url_to_text = url_to_text
        self._traces: list[dict] = []
        self._cookies: dict[str, dict[str, str]] = {}

    async def fetch_text(self, url: str, **kwargs) -> str:
        if url not in self._url_to_text:
            from app.source_plugins.errors import FetchNetworkError

            raise FetchNetworkError(f"no smoke fixture for url: {url}")
        text = self._url_to_text[url]
        self._traces.append({"url": url, "status": 200, "method": kwargs.get("method", "GET"), "mode": "fixture"})
        return text

    async def fetch_json(self, url: str, **kwargs) -> Any:
        import json

        return json.loads(await self.fetch_text(url, **kwargs))

    async def fetch_bytes(self, url: str, **kwargs) -> bytes:
        return (await self.fetch_text(url, **kwargs)).encode("utf-8")

    async def fetch_many(self, urls: list[str], **kwargs) -> list[str]:
        return [await self.fetch_text(url, **kwargs) for url in urls]

    def cookies_for_domain(self, domain: str) -> dict[str, str]:
        return dict(self._cookies.get(domain, {}))

    def set_cookie(self, domain: str, name: str, value: str) -> None:
        self._cookies.setdefault(domain, {})[name] = value

    def clear_cookies(self, domain: str | None = None) -> None:
        if domain is None:
            self._cookies.clear()
        else:
            self._cookies.pop(domain, None)

    def get_traces(self) -> list[dict]:
        return list(self._traces)

    async def close(self) -> None:
        return None


def load_smoke_spec(plugin_dir: Path) -> dict:
    """Load and validate `tests/smoke.yaml` for a plugin."""
    spec_path = plugin_dir / "tests" / "smoke.yaml"
    if not spec_path.exists():
        raise FileNotFoundError(f"missing smoke spec: {spec_path}")
    raw = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("smoke.yaml must be a mapping")
    if "keyword" not in raw:
        raw["keyword"] = "凡人修仙传"
    if not isinstance(raw.get("fixtures"), dict):
        raise ValueError("smoke.yaml must define fixtures mapping")
    return raw


def _fixture_map(plugin_dir: Path, spec: dict, capabilities: list[str] | None = None) -> dict[str, str]:
    fixtures = spec.get("fixtures") or {}
    url_to_text: dict[str, str] = {}
    for stage in ("search", "detail", "toc", "chapter"):
        fixture = fixtures.get(stage)
        if not isinstance(fixture, dict):
            if capabilities and stage not in capabilities:
                continue
            raise ValueError(f"missing fixture for stage: {stage}")
        url = fixture.get("url")
        file_name = fixture.get("file")
        if not url or not file_name:
            raise ValueError(f"fixture {stage} must include url and file")
        fixture_path = plugin_dir / "tests" / "fixtures" / file_name
        if not fixture_path.exists():
            raise FileNotFoundError(f"missing smoke fixture file: {fixture_path}")
        url_to_text[url] = fixture_path.read_text(encoding="utf-8")
    return url_to_text


def _dict_value(item: Any, key: str, attr: str = "") -> Any:
    if isinstance(item, dict):
        return item.get(key)
    if attr and hasattr(item, attr):
        return getattr(item, attr)
    return None


def _expect(spec: dict, path: str, default: Any = None) -> Any:
    current: Any = spec.get("expect", {})
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _legacy_expect(spec: dict, key: str, default: Any = None) -> Any:
    value = (spec.get("expect") or {}).get(key, default)
    return value


def _error(plugin_id: str, stage: str, code: str, message: str) -> dict:
    return normalize_failure(source_id=plugin_id, stage=stage, code=code, message=message)


async def run_fixture_smoke(
    plugin: LoadedPlugin,
    plugin_dir: Path,
    keyword: str | None = None,
    stage_timeout: float = 15.0,
) -> dict:
    """Run search/detail/toc/chapter smoke against local fixtures."""
    spec = load_smoke_spec(plugin_dir)
    result: dict = {
        "pluginId": plugin.metadata.id,
        "mode": "fixture",
        "pass": False,
        "stages": {},
        "errors": [],
        "diagnostics": [],
    }

    try:
        fetcher = FixtureFetcher(_fixture_map(plugin_dir, spec, plugin.capabilities))
    except Exception as exc:
        result["errors"].append(_error(plugin.metadata.id, "setup", "SMOKE_FIXTURE_MISSING", str(exc)))
        return result

    ctx = PluginContext(fetcher=fetcher, plugin_id=plugin.metadata.id)
    smoke_keyword = keyword or spec.get("keyword", "凡人修仙传")

    async def run_stage(stage: str, func, *args) -> Any:
        started = time.perf_counter()
        try:
            data = await asyncio.wait_for(func(*args), timeout=stage_timeout)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            return data, {"status": "ok", "elapsedMs": elapsed_ms}, None
        except asyncio.TimeoutError:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            err = _error(plugin.metadata.id, stage, "PLUGIN_TIMEOUT", "timeout")
            return None, {"status": "error", "elapsedMs": elapsed_ms, "code": err["code"], "message": err["message"]}, err
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            code = getattr(exc, "code", "PLUGIN_RUNTIME_ERROR")
            err = _error(plugin.metadata.id, stage, code, str(exc))
            return None, {"status": "error", "elapsedMs": elapsed_ms, "code": code, "message": str(exc)}, err

    if "search" in plugin.capabilities:
        search_items, stage_data, err = await run_stage("search", plugin.source.search, ctx, smoke_keyword, 1)
        search_items = search_items or []
    else:
        search_items = []
        stage_data = {"status": "skipped", "count": 0}
        err = None
    stage_data["count"] = len(search_items)
    result["stages"]["search"] = stage_data
    if err:
        result["errors"].append(err)
    min_results = _expect(spec, "search.minResults", _legacy_expect(spec, "search_min_items", 1))
    first_name = _expect(spec, "search.firstName")
    if "search" in plugin.capabilities and len(search_items) < min_results:
        result["errors"].append(_error(plugin.metadata.id, "search", "PARSE_EMPTY", f"expected at least {min_results} results"))
    if first_name and search_items and _dict_value(search_items[0], "name", "name") != first_name:
        result["errors"].append(_error(plugin.metadata.id, "search", "SMOKE_CONTRACT_ERROR", f"first result name mismatch: {first_name}"))
    if not search_items:
        book_url = spec.get("bookUrl", "")
        if not book_url:
            result["diagnostics"] = ctx.get_traces() + fetcher.get_traces()
            return result
    else:
        book_url = _dict_value(search_items[0], "bookUrl", "book_url") or ""
    detail_data, stage_data, err = await run_stage("detail", plugin.source.detail, ctx, book_url)
    result["stages"]["detail"] = stage_data
    if err:
        result["errors"].append(err)
    else:
        expected_name = _expect(spec, "detail.name")
        expected_author = _expect(spec, "detail.author")
        if expected_name and _dict_value(detail_data, "name", "name") != expected_name:
            result["errors"].append(_error(plugin.metadata.id, "detail", "SMOKE_CONTRACT_ERROR", f"detail name mismatch: {expected_name}"))
        if expected_author and _dict_value(detail_data, "author", "author") != expected_author:
            result["errors"].append(_error(plugin.metadata.id, "detail", "SMOKE_CONTRACT_ERROR", f"detail author mismatch: {expected_author}"))
        if _expect(spec, "detail.hasTocUrl", False) and not _dict_value(detail_data, "tocUrl", "toc_url"):
            result["errors"].append(_error(plugin.metadata.id, "detail", "PARSE_EMPTY", "tocUrl is required"))

    toc_url = (_dict_value(detail_data, "tocUrl", "toc_url") if detail_data else "") or book_url
    chapters, stage_data, err = await run_stage("toc", plugin.source.toc, ctx, toc_url)
    chapters = chapters or []
    stage_data["count"] = len(chapters)
    result["stages"]["toc"] = stage_data
    if err:
        result["errors"].append(err)
    min_chapters = _expect(spec, "toc.minChapters", _legacy_expect(spec, "toc_min_chapters", 1))
    first_title_contains = _expect(spec, "toc.firstTitleContains")
    if len(chapters) < min_chapters:
        result["errors"].append(_error(plugin.metadata.id, "toc", "PARSE_EMPTY", f"expected at least {min_chapters} chapters"))
    if first_title_contains and chapters and first_title_contains not in (_dict_value(chapters[0], "title", "title") or ""):
        result["errors"].append(_error(plugin.metadata.id, "toc", "SMOKE_CONTRACT_ERROR", f"first chapter title must contain {first_title_contains}"))
    if not chapters:
        result["diagnostics"] = ctx.get_traces() + fetcher.get_traces()
        return result

    chapter_url = _dict_value(chapters[0], "chapterUrl", "chapter_url") or ""
    content, stage_data, err = await run_stage("chapter", plugin.source.chapter, ctx, chapter_url)
    content_text = _dict_value(content, "content", "content") or ""
    stage_data["contentLength"] = len(content_text)
    result["stages"]["chapter"] = stage_data
    if err:
        result["errors"].append(err)
    min_content = _expect(spec, "chapter.minContentLength", _legacy_expect(spec, "chapter_min_chars", 200))
    title_contains = _expect(spec, "chapter.titleContains")
    if len(content_text) < min_content:
        result["errors"].append(_error(plugin.metadata.id, "chapter", "PARSE_EMPTY", f"content too short: {len(content_text)} chars"))
    if title_contains and content and title_contains not in (_dict_value(content, "title", "title") or ""):
        result["errors"].append(_error(plugin.metadata.id, "chapter", "SMOKE_CONTRACT_ERROR", f"chapter title must contain {title_contains}"))

    result["diagnostics"] = ctx.get_traces() + fetcher.get_traces()
    result["pass"] = len(result["errors"]) == 0
    return result


async def main() -> None:
    import argparse
    import sys
    from pathlib import Path
    from app.source_plugins.loader import PluginLoader

    parser = argparse.ArgumentParser(description="Smoke test a LegadoHub source plugin")
    parser.add_argument("plugin_dir", help="Path to plugin directory")
    parser.add_argument("--keyword", default="凡人修仙传", help="Search keyword")
    args = parser.parse_args()

    plugin_dir = Path(args.plugin_dir)
    loader = PluginLoader(plugins_dir=plugin_dir.parent)
    plugins = loader.load_all()
    plugin = plugins.get(plugin_dir.name)
    if not plugin:
        print(f"Plugin not found: {plugin_dir.name}")
        sys.exit(1)

    from app.source_plugins.fetcher import Fetcher
    ctx = PluginContext(fetcher=Fetcher(), plugin_id=plugin.metadata.id)
    if (plugin_dir / "tests" / "smoke.yaml").exists():
        result = await run_fixture_smoke(plugin, plugin_dir, args.keyword)
    else:
        result = await run_smoke(plugin, ctx, args.keyword)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["pass"] else 1)


if __name__ == "__main__":
    asyncio.run(main())




