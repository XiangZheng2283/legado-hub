"""Engine capability classification."""

from __future__ import annotations

import json

from app.legado_engine.models import EngineCapability


def engine_capability_matrix() -> list[dict]:
    """Return the current Legado engine capability matrix."""
    return [
        {"id": "css_selector", "name": "CSS / JSoup 选择器", "status": "supported", "notes": "支持 class/id/tag、链式 @、索引与排除"},
        {"id": "xpath", "name": "XPath", "status": "supported", "notes": "主规则路径支持 XPath 列表与字段"},
        {"id": "jsonpath", "name": "JsonPath", "status": "supported", "notes": "支持 $.key、嵌套字段、数组索引、[*] 展开"},
        {"id": "regex", "name": "Regex", "status": "supported", "notes": "支持 regex: 前缀字段与列表提取"},
        {"id": "fallback", "name": "规则回退 ||", "status": "supported", "notes": "列表与字段按分支返回第一个非空结果"},
        {"id": "replace", "name": "## 正则替换", "status": "supported", "notes": "字段提取后执行正则替换"},
        {"id": "safe_js_transform", "name": "安全 @js: 变换", "status": "limited", "notes": "支持 replace/trim/split.join，网络与 DOM JS 标记为不支持"},
        {"id": "context_storage", "name": "@put / @get 上下文", "status": "supported", "notes": "支持规则执行中的临时变量写入与读取"},
        {"id": "headers", "name": "请求头", "status": "supported", "notes": "支持 source header 与请求 header 合并"},
        {"id": "cookie_jar", "name": "CookieJar", "status": "limited", "notes": "支持同一运行器内基础 Cookie 持久化"},
        {"id": "pagination", "name": "目录/正文分页", "status": "supported", "notes": "支持 nextTocUrl 与 nextContentUrl，最多跟随 10 页"},
        {"id": "webview", "name": "WebView", "status": "unsupported", "notes": "需要浏览器渲染的源会标记为引擎缺口"},
        {"id": "login_workflow", "name": "登录工作流", "status": "unsupported", "notes": "检测 loginUrl，但不模拟用户登录"},
    ]


def default_engine_report() -> dict:
    """Return the visible backend rule-engine report."""
    items = [
        {
            "id": "legado",
            "type": "legado",
            "name": "阅读/Legado 规则引擎",
            "enabled": True,
            "default": True,
            "capabilities": engine_capability_matrix(),
        }
    ]
    return {"items": items, "engines": items}


def classify_capabilities(raw: dict) -> list[EngineCapability]:
    """Classify engine capabilities for a raw Legado source."""
    caps = []
    rules_text = json.dumps(raw, ensure_ascii=False)

    caps.append(EngineCapability("search", bool(raw.get("searchUrl")), "搜索URL存在"))
    caps.append(EngineCapability("book_info", bool(raw.get("ruleBookInfo")), "详情规则存在"))
    caps.append(EngineCapability("toc", bool(raw.get("ruleToc")), "目录规则存在"))
    caps.append(EngineCapability("content", bool(raw.get("ruleContent")), "正文规则存在"))
    caps.append(EngineCapability("explore", bool(raw.get("exploreUrl")), "发现URL存在"))
    caps.append(EngineCapability("headers", bool(raw.get("header")), "Headers存在"))
    caps.append(EngineCapability("cookie_jar", raw.get("enabledCookieJar", False), "CookieJar启用"))

    js_issues = []
    if "<js>" in rules_text:
        js_issues.append("<js> block")
    if "@js:" in rules_text:
        js_issues.append("@js: limited")
    caps.append(EngineCapability("js_transform", not js_issues, "; ".join(js_issues) if js_issues else "无JS变换"))

    caps.append(EngineCapability("xpath_fallback", "||" in rules_text, "|| fallback存在"))

    return caps


def detect_unsupported_syntax(raw: dict) -> list[str]:
    """Detect unsupported syntax markers in a source."""
    rules_text = json.dumps(raw, ensure_ascii=False)
    issues = []
    if "<js>" in rules_text:
        issues.append("<js> block")
    if raw.get("loginUrl"):
        issues.append("loginUrl required")
    if raw.get("webView"):
        issues.append("webView required")
    return issues
