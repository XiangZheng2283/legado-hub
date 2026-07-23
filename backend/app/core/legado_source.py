"""Generate the Legado virtual source JSON for the shared subscription library.

The virtual source used to live under ``/api/legado/*``; after the shared
subscription refactor it is exposed at ``/api/subscribe/legado/*``.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import GENERATED_DIR
from app.core.aggregate_config import load_aggregate_config
from app.core.app_config import AppConfig
from app.core.public_security import get_public_base_url, normalize_public_base_url


# Reading identifies this source by bookSourceUrl and only offers updates when
# lastUpdateTime increases. Keep this release pair code-owned so persisted
# aggregate configuration cannot pin an older generated rule revision.
_READER_RULE_VERSION = "0.0.15"
# Reading only refreshes a book source when lastUpdateTime increases.
_READER_RULE_LAST_UPDATE_TIME = 1_784_770_000_000


def _reader_rule_last_update_time(config: AppConfig) -> int:
    """Advance Reading's source marker when runtime source settings change."""
    try:
        config_modified_at = config.path.stat().st_mtime_ns // 1_000_000
    except OSError:
        return _READER_RULE_LAST_UPDATE_TIME
    return max(_READER_RULE_LAST_UPDATE_TIME, config_modified_at)


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
            if (typeof info === "string") info = JSON.parse(info);
        }} catch (e) {{}}
        try {{
            var mapped = info.get(name);
            if (mapped !== null && mapped !== undefined) return String(mapped);
        }} catch (e) {{}}
        try {{
            var direct = info[name];
            if (direct !== null && direct !== undefined) return String(direct);
        }} catch (e) {{}}
        try {{
            if (info.containsKey(name)) return String(info.get(name) || "");
        }} catch (e) {{}}
        try {{
            if (info.has(name)) return String(info.get(name) || "");
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
    var options = {{
        method: String(method || "GET").toUpperCase(),
        headers: legadoHubHeaders()
    }};
    if (body !== undefined && body !== null) options.body = JSON.stringify(body);
    var text = String(java.ajax(LEGADOHUB_BASE + path + "," + JSON.stringify(options)) || "").trim();
    return text ? JSON.parse(text) : {{}};
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
        var payload = legadoHubRequest("/api/auth/access/redeem", "POST", {{accessCode: code}});
        var username = legadoHubUsername(payload);
        if (!username || !payload.token) throw new Error("invalid identity");
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
        var payload = legadoHubRequest("/api/auth/access/me", "GET", null);
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


_LEGADO_E_READER_JS = r"""
function legadoHubReviewRoot(contentUrl) {
    return String(contentUrl || "").split("?")[0].replace(/\/+$/, "");
}

// Rewrite absolute Hub API URLs to the origin baked into this book source.
// Chapter/toc snapshots may still carry a LAN host from an earlier request;
// comments and content should follow the source entry (CF/public or LAN).
// Do NOT call baseUrl() here: AnalyzeRule often binds baseUrl to the chapter
// data: URL and that string shadows the jsLib helper.
function legadoHubRewriteApiUrl(absoluteUrl) {
    var value = String(absoluteUrl || "").trim();
    if (!/^https?:\/\//i.test(value)) return value;
    var configured = "";
    try {
        configured = String(legadoHubSourceBase() || "").trim().replace(/\/+$/, "");
    } catch (e) {
        configured = "";
    }
    if (!/^https?:\/\//i.test(configured)) return value.replace(/\/+$/, "");
    var pathWithQuery = value.replace(/^https?:\/\/[^\/?#]+/i, "");
    if (!pathWithQuery) pathWithQuery = "/";
    return configured + pathWithQuery;
}

function legadoHubReviewCount(item) {
    if (!item) return 0;
    var count = Number(item.commentCount || item.totalCommentCount || item.hotCommentCount || 0);
    return isFinite(count) && count > 0 ? Math.floor(count) : 0;
}

function legadoHubChapterEndReviewCount(reviews) {
    var summary = reviews && reviews.summary && typeof reviews.summary === "object" ? reviews.summary : {};
    var total = Number(summary.chapterEndCount || 0);
    if (isFinite(total) && total > 0) return Math.floor(total);
    return Math.max((reviews.chapterEnd || []).length, (reviews.chapterEndHot || []).length);
}

"""


def _reader_js_lib(base_api: str) -> str:
    base_literal = json.dumps(base_api.rstrip("/"), ensure_ascii=False)
    # baseUrl() is the historical helper; legadoHubSourceBase() is collision-safe
    # when AnalyzeRule binds the name baseUrl to a chapter data: URL.
    return (
        "function baseUrl() { return "
        + base_literal
        + "; }\n"
        + "function legadoHubSourceBase() { return "
        + base_literal
        + "; }\n"
        + _LEGADO_E_READER_JS
    )


def _chapter_comment_url_rule() -> str:
    return (
        "@js:\n"
        "var location = String(baseUrl || '');\n"
        "var matched = /^data:contentUrl;base64,([^,]+)/i.exec(location);\n"
        "if (!matched) throw new Error('chapter comment content URL missing');\n"
        "var contentUrl = String(java.base64Decode(matched[1]) || '').trim();\n"
        "if (!/^https?:\\/\\//i.test(contentUrl)) throw new Error('invalid chapter comment content URL');\n"
        "legadoHubReviewRoot(legadoHubRewriteApiUrl(contentUrl)) + '/reviews';"
    )


def _chapter_comment_data_rule() -> str:
    return (
        "@js:\n"
        "var reviews = JSON.parse(String(result || '{}'));\n"
        "var segments = [];\n"
        "(reviews.hotParagraphReviews || []).forEach(function (item) {\n"
        "  if (!item || typeof item !== 'object') return;\n"
        "  var paragraphId = Number(item.paragraphId);\n"
        "  var paragraphIndex = Number(item.matchedParagraphIndex);\n"
        "  if (!isFinite(paragraphId) || paragraphId < 0 || !isFinite(paragraphIndex) || paragraphIndex < 0) return;\n"
        "  var total = legadoHubReviewCount(item);\n"
        "  if (total <= 0) return;\n"
        "  var hot = Array.isArray(item.topReviews) ? item.topReviews.length : Number(item.hotCommentCount || 0);\n"
        "  segments.push({\n"
        "    id: String(Math.floor(paragraphId)),\n"
        "    paragraphIndex: Math.floor(paragraphIndex),\n"
        "    paragraphCount: Math.max(1, Math.floor(Number(item.matchedParagraphCount) || 1)),\n"
        "    excerpt: String(item.matchedText || item.paragraphText || ''),\n"
        "    counts: {total: total, hot: Math.max(0, Math.floor(hot || 0))},\n"
        "    pageEligible: true,\n"
        "    actionData: {paragraphId: String(Math.floor(paragraphId))}\n"
        "  });\n"
        "});\n"
        "var chapterHot = Array.isArray(reviews.chapterEndHot) ? reviews.chapterEndHot : [];\n"
        "var chapterEnd = Array.isArray(reviews.chapterEnd) ? reviews.chapterEnd : [];\n"
        "var chapterItems = chapterHot.concat(chapterEnd);\n"
        "function cleanReviewPreview(item) {\n"
        "  return String(item && (item.content || item.Content) || '')\n"
        "    .replace(/<[^>]*>/g, ' ')\n"
        "    .replace(/\\[fn=\\d+\\]/g, '')\n"
        "    .replace(/\\s+/g, ' ')\n"
        "    .trim();\n"
        "}\n"
        "function cleanReviewUser(item) {\n"
        "  return String(item && (item.userName || item.UserName || item.nickName) || '')\n"
        "    .replace(/<[^>]*>/g, ' ')\n"
        "    .replace(/\\s+/g, ' ')\n"
        "    .trim();\n"
        "}\n"
        "var chapterPreviews = [];\n"
        "var seenChapterPreviews = {};\n"
        "chapterItems.some(function (item) {\n"
        "  var content = cleanReviewPreview(item);\n"
        "  if (!content) return false;\n"
        "  var user = cleanReviewUser(item);\n"
        "  var value = (user ? user + '：' : '') + content;\n"
        "  var key = '$' + String(item && (item.id || item.reviewId) || value);\n"
        "  if (seenChapterPreviews[key]) return false;\n"
        "  seenChapterPreviews[key] = true;\n"
        "  chapterPreviews.push(value.slice(0, 512));\n"
        "  return chapterPreviews.length >= 3;\n"
        "});\n"
        "var authorItems = Array.isArray(reviews.authorReviews) ? reviews.authorReviews : [];\n"
        "var author = null;\n"
        "authorItems.some(function (item) {\n"
        "  var content = cleanReviewPreview(item);\n"
        "  if (!content) return false;\n"
        "  var authorPreview = content.slice(0, 512);\n"
        "  author = {\n"
        "    label: cleanReviewUser(item) || '作者',\n"
        "    badge: '作家说',\n"
        "    counts: {total: 0, hot: 0},\n"
        "    actionData: null,\n"
        "    previews: [authorPreview]\n"
        "  };\n"
        "  return true;\n"
        "});\n"
        "var chapterTotal = legadoHubChapterEndReviewCount(reviews);\n"
        "JSON.stringify({\n"
        "  version: 2,\n"
        "  segments: segments,\n"
        "  author: author,\n"
        "  chapter: chapterTotal > 0 ? {\n"
        "    label: '本章说',\n"
        "    counts: {total: chapterTotal, hot: chapterHot.length},\n"
        "    actionData: {},\n"
        "    previews: chapterPreviews\n"
        "  } : null\n"
        "});"
    )


def _chapter_comment_action_rule() -> str:
    # Client executes this via source.evalJS (not AnalyzeUrl). Bindings include
    # chapter/event/result/baseUrl, but jsLib also defines function baseUrl(), so
    # prefer chapter.getAbsoluteURL() and only treat baseUrl as a string location.
    return (
        "@js:\n"
        "var rawEvent = event;\n"
        "if (rawEvent == null || rawEvent === undefined || rawEvent === '') rawEvent = result;\n"
        "if (rawEvent == null || rawEvent === undefined || rawEvent === '') rawEvent = '{}';\n"
        "var actionEvent = JSON.parse(String(rawEvent));\n"
        "var location = '';\n"
        "try {\n"
        "  if (chapter != null && chapter.getAbsoluteURL) location = String(chapter.getAbsoluteURL() || '');\n"
        "} catch (e1) {}\n"
        "if (!location) {\n"
        "  try {\n"
        "    if (chapter != null && chapter.url) location = String(chapter.url || '');\n"
        "  } catch (e2) {}\n"
        "}\n"
        "if (!location) {\n"
        "  try {\n"
        "    var baseCandidate = baseUrl;\n"
        "    if (typeof baseCandidate !== 'function') location = String(baseCandidate || '');\n"
        "  } catch (e3) {}\n"
        "}\n"
        "var contentUrl = '';\n"
        "var matched = /^data:contentUrl;base64,([^,]+)/i.exec(location);\n"
        "if (matched) {\n"
        "  contentUrl = String(java.base64Decode(matched[1]) || '').trim();\n"
        "} else {\n"
        "  var bare = String(location || '').split(/\\s*,\\s*(?=\\{)/)[0].trim();\n"
        "  if (/^https?:\\/\\//i.test(bare)) contentUrl = bare;\n"
        "}\n"
        "if (!/^https?:\\/\\//i.test(contentUrl)) throw new Error('chapter comment content URL missing');\n"
        "contentUrl = legadoHubRewriteApiUrl(contentUrl).replace(/\\/+$/, '');\n"
        "var viewRoot = contentUrl + '/reviews/view';\n"
        "var commentScope = String(actionEvent.scope || '');\n"
        "var viewUrl = '';\n"
        "var sheetTitle = '';\n"
        "if (commentScope === 'chapter') {\n"
        "  viewUrl = viewRoot + '?tab=chapter';\n"
        "  sheetTitle = '本章说';\n"
        "} else if (commentScope === 'page') {\n"
        "  var ids = [];\n"
        "  var segmentIds = actionEvent.segmentIds || [];\n"
        "  for (var i = 0; i < segmentIds.length && ids.length < 50; i++) {\n"
        "    var sid = String(segmentIds[i] || '');\n"
        "    if (/^\\d+$/.test(sid)) ids.push(sid);\n"
        "  }\n"
        "  if (!ids.length) throw new Error('page comment segment missing');\n"
        "  viewUrl = viewRoot + '?tab=paragraph&paragraphIds=' + encodeURIComponent(ids.join(','));\n"
        "  sheetTitle = '页热评';\n"
        "} else if (commentScope === 'segment') {\n"
        "  var id = String(actionEvent.segmentId || (actionEvent.segmentIds || [])[0] || '');\n"
        "  if (!/^\\d+$/.test(id)) throw new Error('segment comment id missing');\n"
        "  viewUrl = viewRoot + '?tab=paragraph&paragraphId=' + encodeURIComponent(id);\n"
        "  sheetTitle = '段评说';\n"
        "} else {\n"
        "  throw new Error('unsupported chapter comment scope');\n"
        "}\n"
        "JSON.stringify({type: 'sourceWebView', url: viewUrl, title: sheetTitle, presentation: 'bottomSheet', heightRatio: 0.78});"
    )


def _build_source(base_api: str | None = None) -> dict:
    base_api = normalize_public_base_url(base_api or get_public_base_url())
    config = load_aggregate_config()
    name = config.get("name", "LegadoHub 聚合")
    group = config.get("group", "聚合,LegadoHub")
    app_config = AppConfig.get()
    chapter_comment = app_config.chapter_comment

    explore_url = f"已发布书库::{base_api}/api/subscribe/legado/explore?page={{{{page}}}}"
    return {
        "bookSourceName": f"{name}({_READER_RULE_VERSION})",
        "bookSourceGroup": group,
        "bookSourceUrl": "LegadoHub",
        "lastUpdateTime": _reader_rule_last_update_time(app_config),
        "bookSourceType": 0,
        "enabled": True,
        "enabledCookieJar": True,
        "enabledExplore": bool(explore_url),
        "header": "",
        "loginUi": _login_ui(),
        "loginUrl": _login_script(base_api),
        "loginCheckJs": _login_check_script(),
        "bookSourceComment": "搜索同时显示已发布共享书和启用的第三方书源；官方源仍只用于后台聚合，新增订阅及运维操作统一在 Web Console 完成。",
        # Progressive: page1 library + short third-party batch; page2+ continue
        # the same server job for new remotes (see subscribe._legado_search_response).
        "searchUrl": (
            f"{base_api}/api/subscribe/legado/search"
            f"?keyword={{{{key}}}}&page={{{{page}}}}"
        ),
        # Slightly above page2 short-wait (20s) so follow-up search pages can finish.
        "respondTime": 25000,
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
                "try { contentUrl = legadoHubRewriteApiUrl(contentUrl); } catch (e) {}\n"
                "var metadata = {type: 'legadoHub'};\n"
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
            'var contentUrl = "";\n'
            'try {\n'
            '  contentUrl = String(java.hexDecodeToString(payload) || "").trim();\n'
            '  try { contentUrl = legadoHubRewriteApiUrl(contentUrl); } catch (e0) {}\n'
            '  if (/^https?:\\/\\//i.test(contentUrl)) payload = String(java.ajax(contentUrl) || "");\n'
            '} catch (e) {}\n'
            'var text = payload;\n'
            'var chapterPayload = null;\n'
            'try {\n'
            '  chapterPayload = JSON.parse(payload);\n'
            '  if (typeof chapterPayload.content === "string") text = chapterPayload.content;\n'
            '  else if (typeof chapterPayload.detail === "string") text = chapterPayload.detail;\n'
            '  else if (chapterPayload.detail && chapterPayload.detail.message) text = chapterPayload.detail.message;\n'
            '} catch (e) {}\n'
            'text = String(text || "").replace(/\\r\\n/g, "\\n").replace(/\\r/g, "\\n");\n'
            'result = /<(?:p|div)\\b/i.test(text) ? text : text.replace(/\\n\\n+/g, "<br><br>").replace(/\\n/g, "<br>");',
            "title": "$.title",
            "chapterComment": {
                "protocolVersion": 2,
                "url": _chapter_comment_url_rule(),
                "data": _chapter_comment_data_rule(),
                "action": _chapter_comment_action_rule(),
                "display": {
                    "segment": {
                        "enabled": chapter_comment.segment_enabled,
                        "preset": "count" if chapter_comment.segment_enabled else "none",
                        "countField": "total",
                        "label": "",
                    },
                    "page": {
                        "enabled": chapter_comment.page_enabled,
                        "preset": "pull" if chapter_comment.page_enabled else "none",
                        "countField": "total",
                        "label": "热评",
                    },
                    "chapter": {
                        "enabled": chapter_comment.chapter_enabled,
                        "preset": "summaryRow" if chapter_comment.chapter_enabled else "none",
                        "countField": "total",
                        "label": "本章说",
                    },
                },
                "cacheTtlSeconds": 300,
            },
        },
        "jsLib": _reader_js_lib(base_api),
    }


def generate_legado_source(base_api: str | None = None) -> list[dict]:
    return [_build_source(base_api)]


def write_legado_source() -> str:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / "legadohub-source.json"
    data = generate_legado_source()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
