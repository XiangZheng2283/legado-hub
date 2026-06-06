"""Generate the aggregate source JSON for LegadoHub.

Reads metadata from config/aggregate_source.json instead of hard-coding.
"""

import json
from pathlib import Path

from app.config import GENERATED_DIR, HOST, PORT
from app.core.aggregate_config import load_aggregate_config, update_progress
from app.services.source_repository import SourceRepository

BASE_API = f"http://{HOST}:{PORT}"


def _build_source(base_api: str = BASE_API) -> dict:
    config = load_aggregate_config()
    version = config.get("version", "0.0.1")
    name = config.get("name", "LegadoHub 聚合")
    group = config.get("group", "聚合,LegadoHub")

    return {
        "bookSourceName": f"{name}({version})",
        "bookSourceGroup": group,
        "bookSourceUrl": "LegadoHub",
        "bookSourceType": 0,
        "enabled": True,
        "enabledCookieJar": True,
        "enabledExplore": True,
        "header": "",
        "searchUrl": f"{base_api}/api/legado/search?keyword={{{{key}}}}&page={{{{page}}}}",
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
    repo = SourceRepository()
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
