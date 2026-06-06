"""Native-like Legado rule execution across HTML, JSON, XPath, Regex, and safe JS."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin

import lxml.html

from app.legado_engine.js_runtime import apply_safe_js_transform, classify_js_rule
from app.legado_engine.jsonpath import extract_jsonpath
from app.legado_engine.models import RuleContext
from app.legado_engine.regex import extract_regex
from app.legado_engine.selectors import apply_selector_chain
from app.legado_engine.xpath import extract_xpath


JsonValue = dict[str, Any] | list[Any]


class UnsupportedRuleError(ValueError):
    """Raised when a rule requires a runtime LegadoHub intentionally cannot emulate."""


def parse_document(value: str | JsonValue | lxml.html.HtmlElement) -> Any:
    if isinstance(value, (dict, list)) or hasattr(value, "xpath"):
        return value
    text = value or ""
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    return lxml.html.fromstring(text or "<html></html>")


def extract_list(
    document: str | JsonValue | lxml.html.HtmlElement,
    rule: str,
    base_url: str = "",
    context: RuleContext | None = None,
) -> list[Any]:
    parsed = parse_document(document)
    for branch in _split_top_level(rule, "||"):
        branch = _replace_context(branch.strip(), context)
        if not branch:
            continue
        result = _extract_list_branch(parsed, branch, base_url, context)
        if result:
            return result
    return []


def extract_field(
    document: str | JsonValue | lxml.html.HtmlElement | Any,
    rule: str,
    base_url: str = "",
    context: RuleContext | None = None,
) -> str:
    for branch in _split_top_level(rule or "", "||"):
        value = _extract_field_branch(document, branch.strip(), base_url, context)
        if value:
            return value
    return ""


def extract_fields_from_element(
    element: Any,
    field_rules: dict[str, str],
    base_url: str = "",
    context: RuleContext | None = None,
) -> tuple[dict[str, str], list[str]]:
    result: dict[str, str] = {}
    unsupported: list[str] = []
    for key, rule in field_rules.items():
        if key in {"bookList", "chapterList", "nextTocUrl", "nextContentUrl", "init", "preUpdateJs"}:
            continue
        if not isinstance(rule, str) or not rule:
            continue
        try:
            result[key] = extract_field(element, rule, base_url, context)
        except UnsupportedRuleError as exc:
            unsupported.append(str(exc))
            result[key] = ""
        except Exception:
            result[key] = ""
    return result, sorted(set(unsupported))


def _extract_list_branch(parsed: Any, rule: str, base_url: str, context: RuleContext | None) -> list[Any]:
    if _is_jsonpath(rule):
        return extract_jsonpath(_ensure_json(parsed), rule)
    if _is_xpath(rule):
        return _normalize_xpath_items(extract_xpath(_ensure_html(parsed), rule))
    if rule.startswith("regex:"):
        pattern = rule[len("regex:") :]
        matches = re.findall(pattern, _document_text(parsed), re.DOTALL)
        return list(matches)
    if hasattr(parsed, "cssselect"):
        selector = _selector_part(rule)
        return apply_selector_chain(parsed, _split_selector_segments(selector))
    return []


def _extract_field_branch(document: Any, rule: str, base_url: str, context: RuleContext | None) -> str:
    if not rule:
        return ""
    rule, replace_spec = _split_replace(rule)
    rule = _replace_context(rule, context)

    if rule.startswith("@put:"):
        key, value = _split_key_value(rule[len("@put:") :])
        value = _replace_context(value, context)
        if context:
            context.put(key, value)
        return value
    if rule.startswith("@get:"):
        return str(context.get(rule[len("@get:") :], "")) if context else ""

    js_code = ""
    if "@js:" in rule:
        rule, js_code = rule.split("@js:", 1)

    parsed = parse_document(document)
    value = _extract_without_js(parsed, rule, base_url, context)
    if replace_spec:
        value = _apply_replace(value, replace_spec)
    if js_code:
        can_emulate, reason = classify_js_rule(js_code)
        if not can_emulate:
            raise UnsupportedRuleError(f"@js: {reason}")
        value = apply_safe_js_transform(value, js_code)
    return value


def _extract_without_js(parsed: Any, rule: str, base_url: str, context: RuleContext | None) -> str:
    rule = rule.strip()
    if not rule:
        return _coerce_text(parsed)
    if _is_jsonpath(rule):
        values = extract_jsonpath(_ensure_json(parsed), rule)
        return _coerce_text(values[0], base_url=base_url) if values else ""
    if _is_xpath(rule):
        values = extract_xpath(_ensure_html(parsed), rule)
        return _coerce_text(values[0], base_url=base_url) if values else ""
    if rule.startswith("regex:"):
        return extract_regex(_document_text(parsed), rule[len("regex:") :])

    segments = _split_selector_segments(rule)
    if not segments:
        return ""
    method = segments[-1].strip()
    selector_segments = segments[:-1]
    if not selector_segments:
        return _coerce_text(parsed, method=method, base_url=base_url)
    if not hasattr(parsed, "cssselect"):
        return ""
    elements = apply_selector_chain(parsed, selector_segments)
    if not elements:
        return ""
    return _coerce_text(elements[0], method=method, base_url=base_url)


def _coerce_text(value: Any, method: str = "text", base_url: str = "") -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        if method and isinstance(value, dict) and method not in ("text", "html"):
            return _coerce_text(value.get(method), base_url=base_url)
        return json.dumps(value, ensure_ascii=False)
    if not hasattr(value, "text_content"):
        return str(value).strip()
    if method in ("", "text", "textNodes"):
        return value.text_content().strip() if value.text_content() else ""
    if method == "html":
        return lxml.html.tostring(value, encoding="unicode").strip()
    attr = value.get(method, "")
    if method in ("href", "src") and attr:
        return urljoin(base_url, attr)
    return attr or ""


def _document_text(parsed: Any) -> str:
    if isinstance(parsed, str):
        return parsed
    if isinstance(parsed, (dict, list)):
        return json.dumps(parsed, ensure_ascii=False)
    if hasattr(parsed, "text_content"):
        return lxml.html.tostring(parsed, encoding="unicode")
    return str(parsed)


def _ensure_json(parsed: Any) -> JsonValue:
    if isinstance(parsed, (dict, list)):
        return parsed
    try:
        return json.loads(_document_text(parsed))
    except Exception:
        return {}


def _ensure_html(parsed: Any) -> lxml.html.HtmlElement:
    if hasattr(parsed, "xpath"):
        return parsed
    return lxml.html.fromstring(_document_text(parsed) or "<html></html>")


def _is_jsonpath(rule: str) -> bool:
    return rule.strip().startswith("$")


def _is_xpath(rule: str) -> bool:
    stripped = rule.strip()
    return stripped.startswith("/") or stripped.startswith("xpath:")


def _selector_part(rule: str) -> str:
    return rule.split("@js:", 1)[0].split("##", 1)[0].strip()


def _split_selector_segments(rule: str) -> list[str]:
    return [seg.strip() for seg in _split_top_level(rule, "@") if seg.strip()]


def _split_top_level(text: str, sep: str) -> list[str]:
    if not text:
        return []
    result: list[str] = []
    buf: list[str] = []
    depth = 0
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == quote and (i == 0 or text[i - 1] != "\\"):
                quote = ""
            i += 1
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}" and depth > 0:
            depth -= 1
        if depth == 0 and text.startswith(sep, i):
            result.append("".join(buf).strip())
            buf = []
            i += len(sep)
            continue
        buf.append(ch)
        i += 1
    result.append("".join(buf).strip())
    return result


def _split_replace(rule: str) -> tuple[str, tuple[str, str] | None]:
    parts = _split_top_level(rule, "##")
    if len(parts) >= 2:
        replacement = parts[2] if len(parts) >= 3 else ""
        return parts[0], (parts[1], replacement)
    return rule, None


def _apply_replace(text: str, replace_spec: tuple[str, str]) -> str:
    pattern, replacement = replace_spec
    try:
        return re.sub(pattern, replacement, text, flags=re.DOTALL)
    except re.error:
        return text


def _split_key_value(text: str) -> tuple[str, str]:
    if "=" not in text:
        return text.strip(), ""
    key, value = text.split("=", 1)
    return key.strip(), value.strip()


def _replace_context(text: str, context: RuleContext | None) -> str:
    return context.replace_vars(text) if context else text


def _normalize_xpath_items(items: list[Any]) -> list[Any]:
    return [item for item in items if item is not None]
