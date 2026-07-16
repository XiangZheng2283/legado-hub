"""Generate the Legado virtual source JSON for the shared subscription library.

The virtual source used to live under ``/api/legado/*``; after the shared
subscription refactor it is exposed at ``/api/subscribe/legado/*``.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import GENERATED_DIR, HOST, PORT
from app.core.aggregate_config import load_aggregate_config

BASE_API = f"http://{HOST}:{PORT}"


def _build_source(base_api: str = BASE_API) -> dict:
    config = load_aggregate_config()
    version = config.get("version", "0.0.1")
    name = config.get("name", "LegadoHub 聚合")
    group = config.get("group", "聚合,LegadoHub")

    explore_url = f"已发布书库::{base_api}/api/subscribe/legado/explore?page={{{{page}}}}"
    return {
        "bookSourceName": f"{name}({version})",
        "bookSourceGroup": group,
        "bookSourceUrl": "LegadoHub",
        "bookSourceType": 0,
        "enabled": True,
        "enabledCookieJar": True,
        "enabledExplore": bool(explore_url),
        "header": "",
        "loginUrl": "",
        "bookSourceComment": "此书源只读取已由 LegadoHub 订阅并发布的共享书、目录和正文；新增订阅、暂停、恢复、归档及运维操作统一在 Web Console 完成。",
        "searchUrl": f"{base_api}/api/subscribe/legado/search?keyword={{{{key}}}}&page={{{{page}}}}",
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
def generate_legado_source(base_api: str = BASE_API) -> list[dict]:
    return [_build_source(base_api)]


def write_legado_source() -> str:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / "legadohub-source.json"
    data = generate_legado_source()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
