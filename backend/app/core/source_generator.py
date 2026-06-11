"""Generate the aggregate source JSON for LegadoHub.

Reads metadata from backend/config/aggregate_source.json instead of hard-coding.
"""

import json
from pathlib import Path

from app.config import GENERATED_DIR, HOST, PORT
from app.core.aggregate_config import load_aggregate_config, update_progress
from app.services.plugin_health_repository import PluginHealthRepository
from app.source_plugins.loader import PluginLoader

BASE_API = f"http://{HOST}:{PORT}"


def _build_source(base_api: str = BASE_API) -> dict:
    config = load_aggregate_config()
    version = config.get("version", "0.0.1")
    name = config.get("name", "LegadoHub 聚合")
    group = config.get("group", "聚合,LegadoHub")

    explore_url = _build_explore_url(base_api)
    return {
        "bookSourceName": f"{name}({version})",
        "bookSourceGroup": group,
        "bookSourceUrl": "LegadoHub",
        "bookSourceType": 0,
        "enabled": True,
        "enabledCookieJar": True,
        "enabledExplore": bool(explore_url),
        "header": "",
        "loginUrl": f"{base_api}/console",
        "bookSourceComment": "聚合搜索会先返回当前已完成书源的快照，并在后台继续搜索；排行榜、分类、聚合书籍章节元信息后续仅从正版书源获取，普通书源不再暴露排行榜/分类；遇到 Cloudflare 或浏览器挑战的书源会被标记为需要绕过并跳过，不再提供手动验证、验证页或 Cookie 回传链路。",
        "searchUrl": f"{base_api}/api/legado/search?keyword={{{{key}}}}&page={{{{page}}}}&waitMs=180000",
        "exploreUrl": explore_url,
        "ruleSearch": {
            "bookList": "$.items",
            "name": "$.name",
            "author": "$.author",
            "coverUrl": "$.coverUrl",
            "intro": "$.intro",
            "kind": "$.kind",
            "lastChapter": "$.readingLastChapter",
            "wordCount": "$.wordCount",
            "bookUrl": "$.bookUrl",
            "checkKeyWord": "",
        },
        "ruleExplore": {
            "bookList": "$.items",
            "name": "$.name",
            "author": "$.author",
            "coverUrl": "$.coverUrl",
            "intro": "$.intro",
            "kind": "$.kind",
            "lastChapter": "$.lastChapter",
            "wordCount": "$.wordCount",
            "bookUrl": "$.bookUrl",
        },
        "ruleBookInfo": {
            "init": "$.data",
            "name": "$.name",
            "author": "$.author",
            "coverUrl": "$.coverUrl",
            "intro": "$.intro",
            "kind": "$.kind",
            "lastChapter": "$.lastChapter",
            "wordCount": "$.wordCount",
            "updateTime": "$.updateTime",
            "tocUrl": "$.tocUrl",
            "canReName": "1",
        },
        "ruleToc": {
            "chapterList": "$.chapters",
            "chapterName": "$.title",
            "chapterUrl": "$.chapterUrl",
            "updateTime": "$.updateTime",
        },
        "ruleContent": {
            "content": '@js:\n'
            'var text = result;\n'
            'try {\n'
            '  var obj = JSON.parse(result);\n'
            '  text = obj.content || "";\n'
            '} catch (e) {}\n'
            'text = String(text || "").replace(/\\r\\n/g, "\\n").replace(/\\r/g, "\\n");\n'
            'result = text.replace(/\\n\\n+/g, "<br><br>").replace(/\\n/g, "<br>");',
            "title": "$.title",
        },
        "jsLib": f"function baseUrl() {{ return '{base_api}'; }}",
    }


def _build_explore_url(base_api: str) -> str:
    lines = []
    try:
        plugins = PluginLoader().load_all()
    except Exception:
        plugins = {}
    for plugin in plugins.values():
        if not plugin.metadata.enabled or "explore" not in plugin.capabilities:
            continue
        if not plugin.metadata.is_official_source():
            continue
        lines.append(
            f"{plugin.metadata.name}::{base_api}/api/legado/explore?sourceId={plugin.metadata.id}&page={{{{page}}}}"
        )
    return "\n".join(lines)


def generate_aggregate_source(base_api: str = BASE_API) -> list[dict]:
    return [_build_source(base_api)]


def write_aggregate_source() -> str:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / "legadohub-source.json"
    _sync_progress()
    data = generate_aggregate_source()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _sync_progress() -> None:
    repo = PluginHealthRepository()
    stats = repo.get_stats()
    update_progress(
        {
            "configured_sources": stats.get("total", 0),
            "enabled_sources": stats.get("enabled", 0),
            "healthy_sources": stats.get("healthy", 0),
            "proxy_sources": stats.get("proxyNeeded", 0),
            "unsupported_sources": stats.get("unsupported", 0),
        }
    )

