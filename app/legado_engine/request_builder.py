"""Build RequestSpec from Legado request templates."""

from __future__ import annotations

import json
from urllib.parse import urljoin, quote

from app.legado_engine.models import RequestSpec, RuleContext


def parse_header_config(header: str | dict | None) -> dict[str, str]:
    """Parse Legado source/request header config."""
    if not header:
        return {}
    if isinstance(header, dict):
        return {str(k): str(v) for k, v in header.items()}
    text = str(header).strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except json.JSONDecodeError:
            pass
    headers: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        headers[key.strip()] = value.strip()
    return headers


def merge_headers(
    source_headers: dict | str | None,
    request_headers: dict | str | None,
    context: RuleContext | None = None,
) -> dict[str, str]:
    """Merge source-level and request-level headers, request headers winning."""
    merged = parse_header_config(source_headers)
    merged.update(parse_header_config(request_headers))
    if context:
        for key, value in list(merged.items()):
            merged[key] = context.replace_vars(value)
    return merged


def parse_request_spec(spec_str: str, base_url: str = "") -> RequestSpec:
    """Parse Legado request spec like 'url,{\"method\":\"POST\",\"body\":\"...\"}'"""
    url = spec_str
    method = "GET"
    body = None
    headers = {}
    charset = "utf-8"

    if spec_str.startswith("{"):
        try:
            opts = json.loads(spec_str)
            url = opts.get("url", "")
            method = opts.get("method", "GET")
            body = opts.get("body")
            headers = opts.get("headers", {})
            charset = opts.get("charset", "utf-8")
        except json.JSONDecodeError:
            pass
    elif "," in spec_str:
        parts = spec_str.split(",", 1)
        url = parts[0].strip()
        try:
            opts = json.loads(parts[1])
            method = opts.get("method", "GET")
            body = opts.get("body")
            headers = opts.get("headers", {})
            charset = opts.get("charset", "utf-8")
        except json.JSONDecodeError:
            pass

    if base_url and url and not url.startswith(("http://", "https://")):
        url = urljoin(base_url, url)

    return RequestSpec(
        url=url,
        method=method.upper(),
        body=body,
        headers=headers,
        charset=charset,
    )


def build_search_request(
    search_url_template: str,
    keyword: str,
    page: int,
    base_url: str = "",
    context: RuleContext | None = None,
) -> RequestSpec:
    """Build a search request spec with variable replacement."""
    spec = parse_request_spec(search_url_template, base_url)
    charset = spec.charset
    url = spec.url.replace("{{key}}", quote(keyword, encoding=charset, safe=""))
    url = url.replace("{{page}}", str(page))
    if spec.body:
        spec.body = spec.body.replace("{{key}}", quote(keyword, encoding=charset, safe=""))
        spec.body = spec.body.replace("{{page}}", str(page))
    if context:
        url = context.replace_vars(url)
        if spec.body:
            spec.body = context.replace_vars(spec.body)
    spec.url = url
    return spec


def apply_context_to_spec(spec: RequestSpec, context: RuleContext) -> RequestSpec:
    """Replace variables in a RequestSpec using a RuleContext."""
    spec.url = context.replace_vars(spec.url)
    if spec.body:
        spec.body = context.replace_vars(spec.body)
    for key in list(spec.headers.keys()):
        spec.headers[key] = context.replace_vars(spec.headers[key])
    return spec
