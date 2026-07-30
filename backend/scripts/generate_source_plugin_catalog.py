"""Generate the source-plugin catalog from plugin metadata."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCES_ROOT = REPO_ROOT / "plugins" / "sources"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "reference" / "source-plugin-catalog.zh-CN.md"


def _inline(value: Any, default: str = "未声明") -> str:
    if value in (None, "", [], {}):
        return default
    if isinstance(value, list):
        return "、".join(f"`{item}`" for item in value)
    if isinstance(value, dict):
        return "；".join(f"`{key}`={_inline(item, '空')}" for key, item in value.items())
    return f"`{value}`"


def _mapping_lines(title: str, value: dict[str, Any]) -> list[str]:
    if not value:
        return [f"- {title}：未声明"]
    return [f"- {title}：{_inline(value)}"]


def _profile_lines(data: dict[str, Any]) -> list[str]:
    lines = [
        f"## {data['name']} (`{data['id']}`)",
        "",
        f"- 目录：`{data['path']}`；展示名称：{_inline(data.get('displayName'), data['name'])}",
        f"- 实现：[`source.py`](../../{data['path']}/source.py)；说明：[`README.md`](../../{data['path']}/README.md)",
        f"- 分类：`{data['group']}`；版本：`{data.get('version', '未声明')}`；作者：{_inline(data.get('author'))}",
        f"- 语言：`{data.get('language', 'zh-CN')}`；默认启用：`{data.get('enabled', True)}`；优先级：`{data.get('priority', 50)}`",
        f"- 主地址：{_inline(data.get('baseUrls'))}",
        f"- 域名：{_inline(data.get('domains'))}",
        f"- 能力：{_inline(data.get('capabilities'))}",
        f"- 标签：{_inline(data.get('tags'))}",
    ]
    auth = data.get("auth") or {}
    content = data.get("content") or {}
    lines.extend([
        f"- 登录：模式 `{auth.get('mode', 'none')}`；Cookie 域名：{_inline(auth.get('cookieDomains'))}",
        f"- 内容：访问权限 `{content.get('access', 'unknown')}`；来源角色 `{content.get('sourceRole', '未声明')}`",
    ])
    lines.extend(_mapping_lines("访问策略", data.get("accessStrategy") or {}))
    browser = data.get("browser") or {}
    lines.append(
        f"- 浏览器：模式 `{browser.get('mode', 'none')}`；原因 `{browser.get('reason') or '未声明'}`"
    )
    proxy = data.get("proxy") or {}
    lines.append(
        f"- 代理：模式 `{proxy.get('mode', 'auto')}`；必需 `{proxy.get('required', False)}`"
    )
    rate_limit = data.get("rateLimit") or {}
    lines.append(
        "- 限流：每主机并发 "
        f"`{rate_limit.get('perHostConcurrency', '未声明')}`；最小间隔 "
        f"`{rate_limit.get('minIntervalMs', '未声明')}` ms"
    )
    lines.extend(_mapping_lines("搜索提供器", data.get("searchProvider") or {}))
    lines.extend(_mapping_lines("Access Bridge", data.get("accessBridge") or {}))
    profiles = data.get("domainProfiles") or []
    if profiles:
        lines.append("- 域名配置：")
        for profile in profiles:
            lines.append(
                f"  - `{profile.get('id', '未命名')}`：{_inline(profile)}"
            )
    else:
        lines.append("- 域名配置：未声明")
    seed = data.get("sourceSeed") or {}
    lines.append(f"- 来源追溯：{_inline(seed)}")
    patterns = data.get("adPatterns") or []
    lines.append(f"- 正文净化规则：`{len(patterns)}` 条")
    for pattern in patterns:
        lines.append(f"  - `{pattern}`")
    lines.append("")
    return lines


def _load_plugins() -> list[dict[str, Any]]:
    plugins: list[dict[str, Any]] = []
    for metadata_path in SOURCES_ROOT.glob("*/*/metadata.yaml"):
        raw = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"metadata must be a mapping: {metadata_path}")
        raw["group"] = metadata_path.parent.parent.name
        raw["path"] = metadata_path.parent.relative_to(REPO_ROOT).as_posix()
        plugins.append(raw)
    return sorted(plugins, key=lambda item: (item["group"], item["id"]))


def render_catalog(plugins: list[dict[str, Any]]) -> str:
    lines = [
        "# 书源插件档案",
        "",
        "本文件由全部 `plugins/sources/*/*/metadata.yaml` 生成，是书源运行声明的可读索引。",
        "字段显示“未声明”代表插件没有在元数据中承诺该能力或限制，不能据此推断运行时行为。",
        "修改元数据后执行 `python backend/scripts/generate_source_plugin_catalog.py` 更新本文件。",
        "",
        "## 总览",
        "",
        f"- 已收录：`{len(plugins)}` 个插件。",
        "- 运行时契约：[`source-plugin-contract.zh-CN.md`](../architecture/source-plugin-contract.zh-CN.md)。",
        "- 浏览器仅由宿主 Access Bridge 管理；本档案的浏览器字段不表示挑战绕过或令牌缓存。",
        "",
        "| 分类 | 插件 | 版本 | 语言 | 浏览器 | 代理 | 限流 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in plugins:
        browser = (item.get("browser") or {}).get("mode", "none")
        proxy = item.get("proxy") or {}
        proxy_text = proxy.get("mode", "auto")
        if proxy.get("required"):
            proxy_text += " (required)"
        rate = item.get("rateLimit") or {}
        rate_text = f"{rate.get('perHostConcurrency', '-')}/{rate.get('minIntervalMs', '-')}ms"
        lines.append(
            f"| {item['group']} | {item['name']} (`{item['id']}`) | "
            f"{item.get('version', '-')} | {item.get('language', 'zh-CN')} | {browser} | {proxy_text} | {rate_text} |"
        )
    for group in sorted({item["group"] for item in plugins}):
        lines.extend(["", f"# {group}", ""])
        for item in (item for item in plugins if item["group"] == group):
            lines.extend(_profile_lines(item))
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the source-plugin catalog")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    plugins = _load_plugins()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_catalog(plugins), encoding="utf-8")
    print(f"wrote {args.output} ({len(plugins)} plugins)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
