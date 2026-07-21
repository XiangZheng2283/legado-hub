"""Generate the Legado virtual source JSON for the shared subscription library.

The virtual source used to live under ``/api/legado/*``; after the shared
subscription refactor it is exposed at ``/api/subscribe/legado/*``.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import GENERATED_DIR
from app.core.aggregate_config import load_aggregate_config
from app.core.public_security import get_public_base_url, normalize_public_base_url

def _login_ui() -> str:
    return json.dumps(
        [
            {"name": "授权码", "type": "password"},
            {
                "name": "登录",
                "type": "button",
                "action": "legadoHubLogin()",
                "style": {"layout_flexGrow": 1, "layout_flexBasisPercent": 0.48},
            },
            {
                "name": "登录状态",
                "type": "button",
                "action": "legadoHubStatus(true)",
                "style": {"layout_flexGrow": 1, "layout_flexBasisPercent": 0.48},
            },
            {
                "name": "订阅管理",
                "type": "button",
                "action": "legadoHubOpenSubscriptions()",
                "style": {"layout_flexGrow": 1, "layout_flexBasisPercent": 0.48},
            },
            {
                "name": "退出",
                "type": "button",
                "action": "legadoHubLogout()",
                "style": {"layout_flexGrow": 1, "layout_flexBasisPercent": 0.48},
            },
        ],
        ensure_ascii=False,
    )


def _login_script(base_api: str) -> str:
    base_literal = json.dumps(base_api.rstrip("/"), ensure_ascii=False)
    return f"""var LEGADOHUB_BASE = {base_literal};

function legadoHubLoginInfoValue(name) {{
    function readValue(info) {{
        if (!info) return null;
        try {{
            if (typeof info.containsKey === "function" && info.containsKey(name)) {{
                return String(info.get(name) || "");
            }}
        }} catch (e) {{}}
        try {{
            if (typeof info.has === "function" && info.has(name)) {{
                return String(info.get(name) || "");
            }}
        }} catch (e) {{}}
        try {{
            if (typeof info.get === "function") {{
                var mapped = info.get(name);
                if (mapped !== null && mapped !== undefined) return String(mapped);
            }}
        }} catch (e) {{}}
        try {{
            if (Object.prototype.hasOwnProperty.call(info, name)) return String(info[name] || "");
        }} catch (e) {{}}
        return null;
    }}

    var current = null;
    try {{
        if (typeof result !== "undefined") current = readValue(result);
    }} catch (e) {{}}
    if (current !== null) return current;

    var stored = null;
    try {{ stored = readValue(source.getLoginInfoMap()); }} catch (e) {{}}
    return stored === null ? "" : stored;
}}

function legadoHubHeaders() {{
    var headers = {{"Accept": "application/json", "Content-Type": "application/json"}};
    try {{
        var raw = source.getLoginHeader();
        var stored = typeof raw === "string" ? JSON.parse(raw || "{{}}") : raw;
        var authorization = stored && (stored.Authorization || stored.authorization);
        if (authorization) headers.Authorization = String(authorization);
    }} catch (e) {{}}
    return headers;
}}

function legadoHubRequest(path, method, body) {{
    var response;
    var headers = legadoHubHeaders();
    if (method === "GET") {{
        response = java.get(LEGADOHUB_BASE + path, headers);
    }} else {{
        response = java.post(
            LEGADOHUB_BASE + path,
            body === undefined || body === null ? "" : JSON.stringify(body),
            headers
        );
    }}
    var text = String(response.body() || "");
    var payload = text ? JSON.parse(text) : {{}};
    return {{status: Number(response.code()), payload: payload}};
}}

function legadoHubUsername(payload) {{
    var username = payload && payload.user && payload.user.username;
    return typeof username === "string" ? username.trim() : "";
}}

function legadoHubLogin() {{
    var code = legadoHubLoginInfoValue("授权码").trim();
    if (!code) {{
        java.toast("请输入授权码");
        return false;
    }}
    try {{
        var response = legadoHubRequest("/api/auth/access/redeem", "POST", {{accessCode: code}});
        var payload = response.payload;
        var username = legadoHubUsername(payload);
        if (response.status !== 200 || !username || !payload.token) throw new Error("invalid identity");
        source.putLoginHeader(JSON.stringify({{Authorization: "Bearer " + String(payload.token)}}));
        source.putLoginInfo("{{}}");
        java.toast("登录成功：" + username);
        return true;
    }} catch (e) {{
        java.toast("登录失败，请检查授权码或服务状态");
        return false;
    }}
}}

function login() {{
    return legadoHubLogin();
}}

function legadoHubStatus(showMessage) {{
    try {{
        var response = legadoHubRequest("/api/auth/access/me", "GET", null);
        if (response.status === 401 || response.status === 403) {{
            source.removeLoginHeader();
            if (showMessage) java.toast("未登录或授权已失效");
            return false;
        }}
        if (response.status !== 200) throw new Error("status unavailable");
        var payload = response.payload;
        var username = legadoHubUsername(payload);
        if (username) {{
            if (showMessage) java.toast("已登录：" + username);
            return true;
        }}
        source.removeLoginHeader();
        if (showMessage) java.toast("未登录或授权已失效");
        return false;
    }} catch (e) {{
        if (showMessage) java.toast("暂时无法检查登录状态");
        return false;
    }}
}}

function legadoHubOpenSubscriptions() {{
    java.startBrowser(LEGADOHUB_BASE + "/console/subscription", "订阅管理");
}}

function legadoHubLogout() {{
    try {{ legadoHubRequest("/api/auth/access/logout", "POST", null); }} catch (e) {{}}
    try {{ source.removeLoginHeader(); }} catch (e) {{}}
    try {{ source.putLoginInfo("{{}}"); }} catch (e) {{}}
    try {{ cookie.removeCookie(LEGADOHUB_BASE); }} catch (e) {{}}
    java.toast("已退出登录");
    return true;
}}
"""


def _login_check_script() -> str:
    return """var legadoHubOriginalResponse = result;
try {
    eval(String(source.loginUrl));
    legadoHubStatus(false);
} catch (e) {}
legadoHubOriginalResponse;"""


def _build_source(base_api: str | None = None) -> dict:
    base_api = normalize_public_base_url(base_api or get_public_base_url())
    config = load_aggregate_config()
    version = config.get("version", "0.0.2")
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
        "loginUi": _login_ui(),
        "loginUrl": _login_script(base_api),
        "loginCheckJs": _login_check_script(),
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
            "chapterUrl": (
                "<js>\n"
                "var contentUrl = String(result.chapterUrl || '');\n"
                "var reviewUrl = contentUrl.replace(/\\/api\\/legado\\/chapter\\/([^?]+)/, '/api/legado/chapter/$1/reviews/view');\n"
                "var metadata = {type: 'qingci', js: `book ? result : '${reviewUrl}'`};\n"
                "`data:contentUrl;base64,${java.base64Encode(contentUrl)},${JSON.stringify(metadata)}`;\n"
                "</js>"
            ),
            "isVip": "$.isVip",
            "isPay": "$.isPay",
            "updateTime": "$.updateTime",
        },
        "ruleContent": {
            "content": '@js:\n'
            'var payload = String(result || "");\n'
            'try {\n'
            '  var contentUrl = String(java.hexDecodeToString(payload) || "").trim();\n'
            '  if (/^https?:\\/\\//i.test(contentUrl)) payload = String(java.ajax(contentUrl) || "");\n'
            '} catch (e) {}\n'
            'var text = payload;\n'
            'try {\n'
            '  var obj = JSON.parse(payload);\n'
            '  text = obj.content || "";\n'
            '} catch (e) {}\n'
            'text = String(text || "").replace(/\\r\\n/g, "\\n").replace(/\\r/g, "\\n");\n'
            'result = /<(?:p|div)\\b/i.test(text) ? text : text.replace(/\\n\\n+/g, "<br><br>").replace(/\\n/g, "<br>");',
            "title": "$.title",
        },
        "jsLib": f"function baseUrl() {{ return '{base_api}'; }}",
    }
def generate_legado_source(base_api: str | None = None) -> list[dict]:
    return [_build_source(base_api)]


def write_legado_source() -> str:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / "legadohub-source.json"
    data = generate_legado_source()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
