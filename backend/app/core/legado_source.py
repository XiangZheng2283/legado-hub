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


# Reading identifies this source by bookSourceUrl and only offers updates when
# lastUpdateTime increases. Keep this release pair code-owned so persisted
# aggregate configuration cannot pin an older generated rule revision.
_READER_RULE_VERSION = "0.0.5"
_READER_RULE_LAST_UPDATE_TIME = 1_784_644_161_854


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

function legadoHubReviewCount(item) {
    if (!item) return 0;
    var count = Number(item.commentCount || item.totalCommentCount || item.hotCommentCount || 0);
    return isFinite(count) && count > 0 ? Math.floor(count) : 0;
}

function legadoHubReviewLabel(count, compact) {
    count = Math.max(0, Math.floor(Number(count) || 0));
    return compact && count > 99 ? "99+" : String(count);
}

function legadoHubNormalizeReviewText(value) {
    return String(value || "")
        .replace(/<[^>]+>/g, "")
        .replace(/^\s*[#>*+-]+\s*/, "")
        .replace(/\s+/g, "")
        .replace(/[^0-9A-Za-z\u3400-\u9fff]/g, "");
}

function legadoHubReviewMatchScore(candidate, needle) {
    if (!candidate || !needle) return 0;
    if (candidate === needle) return 1;
    var shorter = Math.min(candidate.length, needle.length);
    var longer = Math.max(candidate.length, needle.length);
    if (shorter < 12) return 0;
    if (candidate.indexOf(needle) >= 0 || needle.indexOf(candidate) >= 0) {
        var coverage = shorter / longer;
        return coverage >= 0.45 ? 0.82 + coverage * 0.18 : 0;
    }
    function grams(value) {
        var counts = {};
        for (var index = 0; index < value.length - 1; index += 1) {
            var gram = value.slice(index, index + 2);
            counts[gram] = (counts[gram] || 0) + 1;
        }
        return counts;
    }
    var left = grams(candidate);
    var right = grams(needle);
    var overlap = 0;
    Object.keys(left).forEach(function (gram) {
        overlap += Math.min(left[gram], right[gram] || 0);
    });
    return (2 * overlap) / Math.max(1, candidate.length + needle.length - 2);
}

function legadoHubFindReviewParagraph(paragraphs, matchedText) {
    var needle = legadoHubNormalizeReviewText(matchedText);
    if (!needle) return -1;
    var ranked = paragraphs.map(function (paragraph, index) {
        return {
            index: index,
            score: legadoHubReviewMatchScore(legadoHubNormalizeReviewText(paragraph), needle)
        };
    }).sort(function (left, right) { return right.score - left.score; });
    var exact = ranked.filter(function (item) { return item.score === 1; });
    if (exact.length === 1) return exact[0].index;
    if (exact.length > 1 || !ranked.length || ranked[0].score < 0.72) return -1;
    if (ranked.length > 1 && ranked[0].score - ranked[1].score < 0.08) return -1;
    return ranked[0].index;
}

function legadoHubReviewImage(java, svg, options) {
    var encoded = String(java.base64Encode(svg) || "");
    if (!encoded) return "";
    return '<img src="data:image/svg+xml;base64,' + encoded + ',' + JSON.stringify(options) + '">';
}

function legadoHubMapValue(config, key) {
    if (!config) return null;
    try {
        var direct = config[key];
        if (direct !== null && direct !== undefined) return direct;
    } catch (e) {}
    try {
        var mapped = config.get(key);
        if (mapped !== null && mapped !== undefined) return mapped;
    } catch (e) {}
    return null;
}

function legadoHubSvgColor(value, fallback) {
    var color = String(value || "").trim();
    return /^#[0-9a-f]{6}$/i.test(color) ? color : fallback;
}

function legadoHubReviewTheme(java) {
    var mode = "";
    var themeConfig = null;
    var readConfig = null;
    try { mode = String(java.getThemeMode() || ""); } catch (e) {}
    try { themeConfig = java.getThemeConfigMap(); } catch (e) {}
    try { readConfig = java.getReadBookConfigMap(); } catch (e) {}
    var isEInk = mode === "3";
    var themeNight = String(legadoHubMapValue(themeConfig, "isNightTheme") || "").toLowerCase() === "true";
    var isNight = !isEInk && (mode === "2" || themeNight);
    var textKey = isEInk ? "textColorEInk" : (isNight ? "textColorNight" : "textColor");
    return {
        text: legadoHubSvgColor(
            legadoHubMapValue(readConfig, textKey),
            isNight ? "#b8b8b8" : "#4b5563"
        )
    };
}

function legadoHubPageHotReviewEntry(java, reviewUrl, count) {
    var label = legadoHubReviewLabel(count, true);
    var colors = legadoHubReviewTheme(java);
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="280" height="72" viewBox="0 0 280 72">'
        + '<rect x="2" y="4" width="276" height="64" rx="12" fill="' + colors.text + '" fill-opacity="0.10" stroke="' + colors.text + '" stroke-opacity="0.18" stroke-width="2"/>'
        + '<text x="140" y="46" text-anchor="middle" fill="' + colors.text + '" fill-opacity="0.72" font-size="27" font-family="sans-serif" font-weight="500">热评 ' + label + '</text></svg>';
    return legadoHubReviewImage(java, svg, {
        style: "RIGHT",
        width: "28%",
        click: "legadoHubOpenReviews(java, " + JSON.stringify(reviewUrl) + ")"
    });
}

function legadoHubChapterReviewEntry(java, reviewUrl, totalCount) {
    var label = legadoHubReviewLabel(totalCount, false);
    var colors = legadoHubReviewTheme(java);
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="94" viewBox="0 0 720 94">'
        + '<rect x="2" y="2" width="716" height="90" rx="16" fill="' + colors.text + '" fill-opacity="0.08" stroke="' + colors.text + '" stroke-opacity="0.12" stroke-width="2"/>'
        + '<text x="38" y="59" fill="' + colors.text + '" fill-opacity="0.76" font-size="28" font-family="sans-serif" font-weight="500">本章说</text>'
        + '<text x="642" y="59" text-anchor="end" fill="' + colors.text + '" fill-opacity="0.58" font-size="24" font-family="sans-serif">' + label + ' 条评论</text>'
        + '<path d="m675 39 12 8-12 8" fill="none" stroke="' + colors.text + '" stroke-opacity="0.52" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    return legadoHubReviewImage(java, svg, {
        style: "FULL",
        width: "100%",
        click: "legadoHubOpenReviews(java, " + JSON.stringify(reviewUrl) + ")"
    });
}

function legadoHubReviewPageBudget(java) {
    var textSize = 20;
    try {
        var config = java.getReadBookConfigMap();
        var configured = Number(legadoHubMapValue(config, "textSize"));
        if (isFinite(configured) && configured > 0) textSize = configured;
    } catch (e) {}
    return Math.max(520, Math.min(1200, Math.round(900 * 20 / textSize)));
}

function legadoHubPageHotCount(items) {
    return items.reduce(function (sum, item) {
        return sum + legadoHubReviewCount(item);
    }, 0);
}

function legadoHubEstimatedPageStart(paragraphOffsets, pageBudget, pageIndex, fallbackIndex) {
    var target = Math.max(0, Math.floor(Number(fallbackIndex) || 0));
    while (target > 0) {
        var previousPage = Math.floor((paragraphOffsets[target - 1] || 0) / pageBudget);
        if (previousPage !== pageIndex) break;
        target -= 1;
    }
    return target;
}

function legadoHubTotalReviewCount(reviews) {
    var summary = reviews && reviews.summary && typeof reviews.summary === "object" ? reviews.summary : {};
    var total = Number(summary.totalReviews || 0);
    if (isFinite(total) && total > 0) return Math.floor(total);
    var chapter = Number(summary.chapterEndCount || 0);
    if (!chapter) chapter = Math.max((reviews.chapterEnd || []).length, (reviews.chapterEndHot || []).length);
    var author = (reviews.authorReviews || []).length;
    var paragraph = (reviews.hotParagraphReviews || []).reduce(function (sum, item) {
        return sum + legadoHubReviewCount(item);
    }, 0);
    return chapter + author + paragraph;
}

function legadoHubDecorateReviews(java, text, reviews, contentUrl) {
    if (!reviews || typeof reviews !== "object") return text;
    var normalized = String(text || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    var lines = normalized.split("\n");
    var paragraphs = [];
    var lineIndexes = [];
    lines.forEach(function (line, lineIndex) {
        if (String(line).trim()) {
            paragraphs.push(line);
            lineIndexes.push(lineIndex);
        }
    });
    var paragraphOffsets = [];
    var offset = 0;
    paragraphs.forEach(function (paragraph) {
        paragraphOffsets.push(offset);
        offset += Math.max(1, legadoHubNormalizeReviewText(paragraph).length) + 8;
    });
    var pageBudget = legadoHubReviewPageBudget(java);
    var pageGroups = {};
    (reviews.hotParagraphReviews || []).forEach(function (item) {
        if (!item || typeof item !== "object") return;
        var paragraphId = Number(item.paragraphId);
        var count = legadoHubReviewCount(item);
        if (!isFinite(paragraphId) || paragraphId < 0 || count <= 0) return;
        var start = Number(item.matchedParagraphIndex);
        if (!isFinite(start) || Math.floor(start) !== start || start < 0 || start >= paragraphs.length) {
            start = legadoHubFindReviewParagraph(paragraphs, item.matchedText || item.paragraphText || "");
        }
        if (start < 0) return;
        var span = Math.max(1, Math.floor(Number(item.matchedParagraphCount) || 1));
        var last = Math.min(paragraphs.length - 1, start + span - 1);
        var itemPages = {};
        for (var paragraphIndex = start; paragraphIndex <= last; paragraphIndex += 1) {
            var pageIndex = Math.floor((paragraphOffsets[paragraphIndex] || 0) / pageBudget);
            if (itemPages[pageIndex]) continue;
            itemPages[pageIndex] = true;
            if (!pageGroups[pageIndex]) {
                pageGroups[pageIndex] = {items: [], paragraphIds: [], target: paragraphIndex};
            }
            var group = pageGroups[pageIndex];
            group.items.push(item);
            if (group.paragraphIds.indexOf(Math.floor(paragraphId)) < 0) {
                group.paragraphIds.push(Math.floor(paragraphId));
            }
            group.target = Math.min(group.target, paragraphIndex);
        }
    });
    Object.keys(pageGroups).sort(function (left, right) { return Number(left) - Number(right); }).forEach(function (key) {
        var group = pageGroups[key];
        var viewUrl = legadoHubReviewRoot(contentUrl) + "/reviews/view?tab=paragraph&paragraphIds="
            + encodeURIComponent(group.paragraphIds.join(","));
        var entry = legadoHubPageHotReviewEntry(java, viewUrl, legadoHubPageHotCount(group.items));
        var pageStart = legadoHubEstimatedPageStart(paragraphOffsets, pageBudget, Number(key), group.target);
        var lineIndex = lineIndexes[pageStart];
        if (entry && lineIndex !== undefined) lines[lineIndex] = entry + "\n" + lines[lineIndex];
    });
    var total = legadoHubTotalReviewCount(reviews);
    if (total > 0) {
        lines.push(legadoHubChapterReviewEntry(
            java,
            legadoHubReviewRoot(contentUrl) + "/reviews/view?tab=chapter",
            total
        ));
    }
    return lines.join("\n");
}

function legadoHubReviewPreload() {
    return [
        'function installLegadoHubReviewBridge() {',
        '  if (window.__legadoHubReviewBridgeInstalled) return;',
        '  window.__legadoHubReviewBridgeInstalled = true;',
        '  if (!window.__legadoHubNativeFetch) window.__legadoHubNativeFetch = window.fetch.bind(window);',
        '  function authorization() {',
        '    try {',
        '      var raw = String(source.getLoginHeader() || "{}");',
        '      var stored = JSON.parse(raw);',
        '      return String(stored.Authorization || stored.authorization || "");',
        '    } catch (e) { return ""; }',
        '  }',
        '  window.fetch = function (input, init) {',
        '    var requestInit = Object.assign({}, init || {});',
        '    var inherited = (typeof Request !== "undefined" && input instanceof Request) ? input.headers : undefined;',
        '    var headers = new Headers(requestInit.headers || inherited);',
        '    var requestUrl = null;',
        '    try { requestUrl = new URL((typeof Request !== "undefined" && input instanceof Request) ? input.url : String(input), location.href); } catch (e) {}',
        '    if (requestUrl && requestUrl.origin === location.origin && requestUrl.pathname.indexOf("/api/legado/chapter/") === 0) {',
        '      var value = authorization();',
        '      if (value) headers.set("Authorization", value);',
        '    } else { headers.delete("Authorization"); }',
        '    requestInit.headers = headers;',
        '    requestInit.credentials = "same-origin";',
        '    return window.__legadoHubNativeFetch(input, requestInit);',
        '  };',
        '  document.addEventListener("click", function (event) {',
        '    var target = event.target && event.target.closest ? event.target.closest("a[href]") : null;',
        '    if (!target) return;',
        '    var nextUrl;',
        '    try { nextUrl = new URL(target.href, location.href); } catch (e) { return; }',
        '    if (nextUrl.origin !== location.origin || nextUrl.pathname.indexOf("/reviews/view") < 0) return;',
        '    event.preventDefault();',
        '    window.fetch(nextUrl.href).then(function (response) {',
        '      if (!response.ok) throw new Error("HTTP " + response.status);',
        '      return response.text();',
        '    }).then(function (html) {',
        '      var bootstrap = "<scr" + "ipt>(" + installLegadoHubReviewBridge.toString() + ")();</scr" + "ipt>";',
        '      var nextHtml = /<head[^>]*>/i.test(html) ? html.replace(/<head[^>]*>/i, "$&" + bootstrap) : bootstrap + html;',
        '      window.__legadoHubReviewBridgeInstalled = false;',
        '      try { history.pushState({}, "", nextUrl.href); } catch (e) {}',
        '      document.open();',
        '      document.write(nextHtml);',
        '      document.close();',
        '    }).catch(function () { try { java.toast("评论加载失败，请稍后重试"); } catch (e) {} });',
        '  }, true);',
        '}',
        'installLegadoHubReviewBridge();'
    ].join("\n");
}

function legadoHubOpenReviews(java, reviewUrl) {
    try {
        var page = String(java.ajax(reviewUrl) || "");
        if (!/<html[\s>]/i.test(page)) {
            var message = "评论加载失败，请检查授权状态";
            try {
                var payload = JSON.parse(page);
                if (typeof payload.detail === "string" && payload.detail) message = payload.detail;
            } catch (e) {}
            java.toast(message);
            return false;
        }
        java.showBrowser(
            reviewUrl,
            page,
            legadoHubReviewPreload(),
            JSON.stringify({
                state: 3,
                heightPercentage: 0.78,
                setFitToContents: false,
                skipCollapsed: true,
                isHideable: true,
                expandedCornersRadius: 18,
                backgroundDimAmount: 0.45,
                dismissOnTouchOutside: true,
                scrollNoDraggable: true
            })
        );
        return true;
    } catch (e) {
        java.toast("评论加载失败，请稍后重试");
        return false;
    }
}
"""


def _reader_js_lib(base_api: str) -> str:
    base_literal = json.dumps(base_api.rstrip("/"), ensure_ascii=False)
    return "function baseUrl() { return " + base_literal + "; }\n" + _LEGADO_E_READER_JS


def _build_source(base_api: str | None = None) -> dict:
    base_api = normalize_public_base_url(base_api or get_public_base_url())
    config = load_aggregate_config()
    name = config.get("name", "LegadoHub 聚合")
    group = config.get("group", "聚合,LegadoHub")

    explore_url = f"已发布书库::{base_api}/api/subscribe/legado/explore?page={{{{page}}}}"
    return {
        "bookSourceName": f"{name}({_READER_RULE_VERSION})",
        "bookSourceGroup": group,
        "bookSourceUrl": "LegadoHub",
        "lastUpdateTime": _READER_RULE_LAST_UPDATE_TIME,
        "bookSourceType": 0,
        "enabled": True,
        "enabledCookieJar": True,
        "enabledExplore": bool(explore_url),
        "header": "",
        "loginUi": _login_ui(),
        "loginUrl": _login_script(base_api),
        "loginCheckJs": _login_check_script(),
        "bookSourceComment": "搜索同时显示已发布共享书和启用的第三方书源；官方源仍只用于后台聚合，新增订阅及运维操作统一在 Web Console 完成。",
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
            'if (contentUrl && chapterPayload && typeof chapterPayload.content === "string") {\n'
            '  try {\n'
            '    var reviewPayload = JSON.parse(String(java.ajax(legadoHubReviewRoot(contentUrl) + "/reviews") || "{}"));\n'
            '    text = legadoHubDecorateReviews(java, text, reviewPayload, contentUrl);\n'
            '  } catch (e) {}\n'
            '}\n'
            'result = /<(?:p|div)\\b/i.test(text) ? text : text.replace(/\\n\\n+/g, "<br><br>").replace(/\\n/g, "<br>");',
            "title": "$.title",
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
