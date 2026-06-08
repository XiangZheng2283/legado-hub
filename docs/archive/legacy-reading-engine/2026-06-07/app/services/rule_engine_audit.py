"""Static audit for source rule usability and engine gaps."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.rules.legado_loader import get_required_fields
from app.services.source_repository import SourceRepository


ENGINE_GAP_MARKERS = {
    "<js>": "JavaScript block",
    "@js:": "JavaScript inline rule",
    "{{": "runtime variable",
    "xpath:": "explicit XPath selector",
    "$.": "JsonPath selector",
}


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for nested in value.values():
            result.extend(_walk_strings(nested))
        return result
    if isinstance(value, list):
        result: list[str] = []
        for nested in value:
            result.extend(_walk_strings(nested))
        return result
    return []


class RuleEngineAuditService:
    """Classifies source failures into source defects, engine gaps, and runtime risks."""

    def __init__(self, repo: SourceRepository | None = None):
        self.repo = repo or SourceRepository()

    def audit_source(self, source_id: str) -> dict:
        source_info = self.repo.get_source(source_id)
        if not source_info:
            return {"sourceId": source_id, "ok": False, "error": "书源不存在"}
        raw = self.repo.load_raw_source(source_id)
        if raw and "raw" in raw:
            raw_source = raw["raw"]
        else:
            raw_source = self._load_raw_without_adapt(source_info) or {}
        result = self.audit_raw_source(raw_source, source_id=source_id)
        result["source"] = source_info
        return result

    def audit_all(self, limit: int = 200, offset: int = 0) -> dict:
        items = self.repo.get_sources(limit=limit, offset=offset)
        audits = []
        counts = Counter()
        for item in items:
            audit = self.audit_source(item["sourceId"])
            audits.append(audit)
            counts[audit.get("classification", "unknown")] += 1
        return {
            "items": audits,
            "stats": dict(counts),
            "limit": limit,
            "offset": offset,
        }

    def audit_raw_source(self, raw: dict, source_id: str = "") -> dict:
        source_defects: list[str] = []
        engine_gaps: list[str] = []
        runtime_risks: list[str] = []

        missing = [field for field in get_required_fields() if not raw.get(field)]
        if missing:
            source_defects.append("缺少必要字段: " + ", ".join(missing))

        source_url = raw.get("bookSourceUrl", "")
        if source_url and not str(source_url).startswith(("http://", "https://")):
            source_defects.append("bookSourceUrl 不是标准 HTTP 地址")

        search_url = raw.get("searchUrl", "")
        if isinstance(search_url, str) and search_url.startswith("{"):
            try:
                request_spec = json.loads(search_url)
                if request_spec.get("method", "GET").upper() not in ("GET", "POST"):
                    engine_gaps.append("请求方法暂不支持: " + str(request_spec.get("method")))
            except json.JSONDecodeError:
                source_defects.append("searchUrl JSON 请求配置无法解析")

        rules_text = "\n".join(_walk_strings(raw))
        if "<js>" in rules_text or "@js:" in rules_text:
            engine_gaps.append("包含 JavaScript 规则，当前执行主路径尚未执行 JS")
        if "xpath:" in rules_text or rules_text.strip().startswith("//"):
            engine_gaps.append("包含 XPath 规则，当前执行主路径未完整接入 XPath 分支")
        if "$." in rules_text:
            engine_gaps.append("包含 JsonPath 规则，当前执行主路径未完整接入 JSON 响应分支")
        if "{{cookie" in rules_text or raw.get("enabledCookieJar"):
            runtime_risks.append("依赖 Cookie/CookieJar，可能需要会话保持")
        if raw.get("header"):
            runtime_risks.append("依赖自定义请求头")
        if "captcha" in rules_text.lower() or "verify" in rules_text.lower():
            runtime_risks.append("可能存在验证码或访问校验")

        unsupported_markers = []
        for marker, label in ENGINE_GAP_MARKERS.items():
            if marker in rules_text:
                unsupported_markers.append(label)

        if source_defects:
            classification = "source_defect"
        elif engine_gaps:
            classification = "engine_gap"
        elif runtime_risks:
            classification = "runtime_risk"
        else:
            classification = "supported_static"

        return {
            "sourceId": source_id,
            "ok": True,
            "classification": classification,
            "sourceDefects": source_defects,
            "engineGaps": sorted(set(engine_gaps)),
            "runtimeRisks": sorted(set(runtime_risks)),
            "detectedMarkers": sorted(set(unsupported_markers)),
        }

    def _load_raw_without_adapt(self, source_info: dict) -> dict | None:
        file_path = Path(source_info["sourceFilePath"])
        if not file_path.is_absolute():
            file_path = Path(__file__).resolve().parent.parent.parent / file_path
        if not file_path.exists():
            return None
        try:
            data = json.loads(file_path.read_text(encoding="utf-8-sig"))
            objects = data if isinstance(data, list) else [data]
            index = source_info.get("sourceIndex", 0)
            if 0 <= index < len(objects) and isinstance(objects[index], dict):
                return objects[index]
        except Exception:
            return None
        return None
