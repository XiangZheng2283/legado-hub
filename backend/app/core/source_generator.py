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
        "enabledExplore": True,
        "header": "",
        "loginUrl": f"{base_api}/console",
        "bookSourceComment": "聚合搜索会先返回当前已完成书源的快照，并在后台继续搜索；搜索、排行、详情、目录或正文响应的 debug.browserChallenges 里会返回需要浏览器验证的书源；可打开 LegadoHub 控制台完成验证，也可调用 /api/legado/browser-challenges/{session_id}/browser/open 启动浏览器助手，或用 /api/legado/browser-challenges/{session_id}/cookies 提交 Cookie，再调用 /api/legado/browser-challenges/{session_id}/retry-live-check 重试排行榜阅读闭环。",
        "searchUrl": f"{base_api}/api/legado/search?keyword={{{{key}}}}&page={{{{page}}}}&waitMs=1200",
        "exploreUrl": explore_url,
        "ruleSearch": {
            "bookList": "$.items",
            "name": "$.name",
            "author": "$.author",
            "coverUrl": "$.coverUrl",
            "intro": "$.intro",
            "kind": "$.kind",
            "lastChapter": "$.lastChapter",
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
            "init": f"<js>\njava.ajax(result);\n</js>$.data",
            "name": "$.name",
            "author": "$.author",
            "coverUrl": "$.coverUrl",
            "intro": "$.intro",
            "kind": "$.kind",
            "lastChapter": "$.lastChapter",
            "wordCount": "$.wordCount",
            "tocUrl": "$.tocUrl",
        },
        "ruleToc": {
            "chapterList": "$.chapters",
            "chapterName": "$.title",
            "chapterUrl": "$.chapterUrl",
            "updateTime": "$.updateTime",
        },
        "ruleContent": {
            "content": "$.content",
            "title": "$.title",
        },
        "jsLib": f"function baseUrl() {{ return '{base_api}'; }}",
    }


def _build_explore_url(base_api: str) -> str:
    lines = [f"聚合推荐::{base_api}/api/legado/explore?page={{{{page}}}}"]
    try:
        plugins = PluginLoader().load_all()
    except Exception:
        plugins = {}
    for plugin in plugins.values():
        if not plugin.metadata.enabled or "explore" not in plugin.capabilities:
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
