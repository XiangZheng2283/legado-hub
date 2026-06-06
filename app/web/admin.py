"""Full Chinese Web backend console for LegadoHub."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

import json
import re
from pathlib import Path

from app.services.source_repository import SourceRepository
from app.services.rule_engine_audit import RuleEngineAuditService
from app.services.source_subscriptions import SourceSubscriptionService
from app.services.catalog import Catalog
from app.services.book_catalog import BookCatalog
from app.services.update_scheduler import UpdateScheduler
from app.services.verification_harness import VerificationHarness
from app.core.aggregate_config import load_aggregate_config
from app.core.source_generator import write_aggregate_source
from app.legado_engine.capabilities import default_engine_report

router = APIRouter()


def _clean_text(text: str) -> str:
    """Normalize whitespace without changing source-provided names."""
    return re.sub(r"\s+", " ", text or "").strip()


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCE_POOL_CONFIG_PATH = PROJECT_ROOT / "config" / "source_pool.json"
RULE_ENGINES_CONFIG_PATH = PROJECT_ROOT / "config" / "rule_engines.json"
SOURCE_SUBSCRIPTIONS_CONFIG_PATH = PROJECT_ROOT / "config" / "source_subscriptions.json"


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


# ---- Shared layout ----

LAYOUT_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | LegadoHub 管理后台</title>
<style>
:root {
  --bg: #f5f6f8;
  --card: #ffffff;
  --border: #e0e2e6;
  --text: #1a1a2e;
  --text-secondary: #5a5a6e;
  --accent: #2563eb;
  --accent-hover: #1d4ed8;
  --success: #16a34a;
  --warning: #ca8a04;
  --error: #dc2626;
  --muted: #f1f2f4;
}
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  margin: 0; padding: 0;
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
  line-height: 1.6;
}
.container { max-width: 1400px; margin: 0 auto; padding: 0 24px; }
header {
  background: var(--card);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
  position: sticky; top: 0; z-index: 100;
}
header .inner {
  max-width: 1400px; margin: 0 auto;
  display: flex; align-items: center; justify-content: space-between;
  height: 56px;
}
header .brand {
  font-size: 18px; font-weight: 600; color: var(--text);
  text-decoration: none;
}
header nav a {
  color: var(--text-secondary);
  text-decoration: none;
  margin-left: 20px;
  font-size: 14px;
  padding: 6px 0;
  border-bottom: 2px solid transparent;
}
header nav a:hover, header nav a.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}
.page-title {
  font-size: 22px; font-weight: 600;
  margin: 24px 0 16px;
}
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 16px;
}
.card-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  font-weight: 600;
  font-size: 15px;
}
.card-body { padding: 16px 20px; }
.table-wrap { overflow-x: auto; }
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th, td {
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
}
th {
  background: var(--muted);
  font-weight: 600;
  color: var(--text-secondary);
  border-top: 1px solid var(--border);
}
tr:hover td { background: #fafbfc; }
.tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}
.tag-success { background: #dcfce7; color: #166534; }
.tag-warning { background: #fef9c3; color: #854d0e; }
.tag-error { background: #fee2e2; color: #991b1b; }
.tag-muted { background: var(--muted); color: var(--text-secondary); }
.tag-info { background: #dbeafe; color: #1e40af; }
.btn {
  display: inline-block;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid var(--border);
  background: var(--card);
  color: var(--text);
  text-decoration: none;
}
.btn-primary {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}
.btn-primary:hover { background: var(--accent-hover); }
.btn-sm { padding: 4px 10px; font-size: 12px; }
.btn-danger {
  background: #fee2e2;
  color: #991b1b;
  border-color: #fecaca;
}
.form-input {
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 14px;
  width: 100%;
  max-width: 400px;
}
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}
.stat-box {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
}
.stat-value {
  font-size: 24px; font-weight: 700;
  margin-bottom: 4px;
}
.stat-label {
  font-size: 12px; color: var(--text-secondary);
}
.empty-state {
  padding: 48px 20px;
  text-align: center;
  color: var(--text-secondary);
}
.error-state {
  padding: 24px 20px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 8px;
  color: var(--error);
}
.loading-state {
  padding: 48px 20px;
  text-align: center;
  color: var(--text-secondary);
}
.partial-state {
  padding: 12px 16px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 6px;
  color: var(--warning);
  margin-bottom: 16px;
}
.section-divider {
  border: none;
  border-top: 1px solid var(--border);
  margin: 24px 0;
}
.panel-group {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.panel-group + .panel-group { margin-top: 16px; }
.panel-header {
  background: var(--muted);
  padding: 12px 16px;
  font-weight: 600;
  border-bottom: 1px solid var(--border);
}
.panel-body { padding: 16px; }
pre {
  background: var(--muted);
  padding: 12px;
  border-radius: 6px;
  overflow-x: auto;
  font-size: 12px;
}
.pagination {
  display: flex; gap: 8px; align-items: center; margin-top: 12px;
}
.trace-line {
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  color: var(--text-secondary);
}
.reader-content {
  font-size: 16px;
  line-height: 1.8;
  max-width: 720px;
  margin: 0 auto;
  padding: 24px;
  background: var(--card);
  border-radius: 8px;
  min-height: 400px;
}
.reader-nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  max-width: 720px;
  margin: 16px auto;
}
@media (max-width: 768px) {
  .container { padding: 0 12px; }
  header nav a { margin-left: 12px; font-size: 13px; }
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
</head>
<body>
<header>
  <div class="inner">
    <a href="/admin" class="brand">LegadoHub 管理后台</a>
    <nav>
      <a href="/admin" class="{nav_dashboard}">仪表盘</a>
      <a href="/admin/sources" class="{nav_sources}">书源</a>
      <a href="/admin/source-subscriptions" class="{nav_subscriptions}">订阅源</a>
      <a href="/admin/search" class="{nav_search}">搜索工作台</a>
      <a href="/admin/explore" class="{nav_explore}">发现</a>
      <a href="/admin/books" class="{nav_books}">书籍</a>
      <a href="/admin/update-tasks" class="{nav_update}">更新任务</a>
      <a href="/admin/cache" class="{nav_cache}">缓存</a>
      <a href="/admin/settings" class="{nav_settings}">设置</a>
      <a href="/admin/verification" class="{nav_verification}">验证中心</a>
    </nav>
  </div>
</header>
<div class="container">
{content}
</div>
</body>
</html>"""


def _render(title: str, content: str, active_nav: str = "") -> str:
    nav = {
        "nav_dashboard": "", "nav_sources": "", "nav_search": "",
        "nav_subscriptions": "", "nav_books": "", "nav_update": "",
        "nav_explore": "", "nav_cache": "", "nav_settings": "", "nav_verification": "",
    }
    nav[f"nav_{active_nav}"] = "active"
    html = LAYOUT_HEAD.replace("{title}", title).replace("{content}", content)
    for k, v in nav.items():
        html = html.replace(f"{{{k}}}", v)
    return html


# ---- Pages ----

@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard() -> str:
    repo = SourceRepository()
    stats = repo.get_stats()

    content = f"""
<div class="page-title">仪表盘</div>
<div class="stats-grid">
  <div class="stat-box">
    <div class="stat-value">{stats['total']}</div>
    <div class="stat-label">书源总数</div>
  </div>
  <div class="stat-box">
    <div class="stat-value" style="color:var(--success)">{stats['enabled']}</div>
    <div class="stat-label">已启用</div>
  </div>
  <div class="stat-box">
    <div class="stat-value" style="color:var(--accent)">{stats['healthy']}</div>
    <div class="stat-label">健康</div>
  </div>
  <div class="stat-box">
    <div class="stat-value" style="color:var(--warning)">{stats['proxyNeeded']}</div>
    <div class="stat-label">代理成功</div>
  </div>
  <div class="stat-box">
    <div class="stat-value" style="color:var(--error)">{stats['disabled']}</div>
    <div class="stat-label">已禁用</div>
  </div>
  <div class="stat-box">
    <div class="stat-value">{stats['unsupported']}</div>
    <div class="stat-label">不支持</div>
  </div>
</div>
<hr class="section-divider">
<div class="card">
  <div class="card-header">快速操作</div>
  <div class="card-body">
    <a href="/admin/sources" class="btn btn-primary">管理书源</a>
    <a href="/admin/source-subscriptions" class="btn" style="margin-left:8px">同步订阅源</a>
    <a href="/admin/search" class="btn" style="margin-left:8px">搜索工作台</a>
    <a href="/admin/explore" class="btn" style="margin-left:8px">发现/排行榜</a>
    <a href="/admin/verification" class="btn" style="margin-left:8px">验证中心</a>
  </div>
</div>
"""
    return _render("仪表盘", content, "dashboard")


@router.get("/admin/sources", response_class=HTMLResponse)
def admin_sources() -> str:
    repo = SourceRepository()
    items = repo.get_sources(limit=100)

    if not items:
        rows = '<tr><td colspan="7" class="empty-state">暂无书源数据。请先扫描书源仓库。</td></tr>'
    else:
        rows = ""
        for src in items:
            enabled_tag = '<span class="tag tag-success">启用</span>' if src["enabled"] else '<span class="tag tag-error">禁用</span>'
            health = src.get("healthStatus", "unknown")
            health_tag = f'<span class="tag">{health}</span>'
            if health == "healthy":
                health_tag = '<span class="tag tag-success">健康</span>'
            elif health in ("disabled", "missing_fields"):
                health_tag = '<span class="tag tag-error">不健康</span>'
            proxy_tag = f'<span class="tag tag-muted">{src.get("proxyMode","auto")}</span>'
            rows += f"""<tr>
<td><a href="/admin/sources/{src['sourceId']}">{_clean_text(src['bookSourceName']) or src['sourceId']}</a></td>
<td>{src['sourceId']}</td>
<td>{enabled_tag}</td>
<td>{health_tag}</td>
<td>{proxy_tag}</td>
<td>{src.get('failureReason','') or '-'}</td>
<td>
  <a href="/admin/sources/{src['sourceId']}" class="btn btn-sm">详情</a>
</td>
</tr>"""

    content = f"""
<div class="page-title">书源管理</div>
<div class="card">
  <div class="card-header">书源列表</div>
  <div class="card-body">
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>书源名称</th><th>ID</th><th>状态</th><th>健康</th><th>代理模式</th><th>失败原因</th><th>操作</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </div>
</div>
"""
    return _render("书源管理", content, "sources")


@router.get("/admin/source-subscriptions", response_class=HTMLResponse)
def admin_source_subscriptions() -> str:
    service = SourceSubscriptionService()
    data = service.list_subscriptions()
    rows = ""
    for item in data.get("items", []):
        enabled_tag = '<span class="tag tag-success">启用</span>' if item.get("enabled", True) else '<span class="tag tag-muted">停用</span>'
        built_in_tag = '<span class="tag tag-info">内置</span>' if item.get("built_in") else '<span class="tag tag-muted">用户添加</span>'
        status = item.get("last_sync_status") or "未同步"
        if status == "success":
            status_tag = '<span class="tag tag-success">同步成功</span>'
        elif status == "failed":
            status_tag = '<span class="tag tag-error">同步失败</span>'
        else:
            status_tag = '<span class="tag tag-muted">未同步</span>'
        rows += f"""<tr>
<td>{_clean_text(item.get('name', ''))}</td>
<td>{item.get('id', '')}</td>
<td>{item.get('engine', '')}</td>
<td>{item.get('kind', '')}</td>
<td>{enabled_tag} {built_in_tag}</td>
<td><a href="{item.get('url', '')}" target="_blank">{item.get('url', '')}</a></td>
<td>{status_tag}<br><span style="color:var(--text-secondary)">{item.get('last_sync_at','-')}</span></td>
<td>{item.get('last_sync_count', 0)}</td>
<td>{_clean_text(item.get('last_sync_error','')) or '-'}</td>
<td>
  <button class="btn btn-sm" onclick="syncSubscription('{item.get('id', '')}')">同步</button>
  <button class="btn btn-sm" onclick="toggleSubscription('{item.get('id', '')}', {str(not item.get('enabled', True)).lower()})">{'停用' if item.get('enabled', True) else '启用'}</button>
</td>
</tr>"""
    if not rows:
        rows = '<tr><td colspan="10" class="empty-state">暂无订阅连接。可以在下方添加新的阅读书源订阅。</td></tr>'

    content = f"""
<div class="page-title">订阅源管理</div>
<div class="card">
  <div class="card-header">项目内订阅连接</div>
  <div class="card-body">
    <p style="color:var(--text-secondary);max-width:900px">这里管理项目内置和用户添加的书源订阅连接。同步成功后会写入 {data.get('targetDir','')}，并重新扫描书源索引，聚合书源进度会随之更新。</p>
    <button class="btn btn-primary" onclick="syncAllSubscriptions()">同步全部启用订阅</button>
    <pre id="subscription-result" style="display:none;margin-top:16px"></pre>
    <hr class="section-divider">
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>名称</th><th>ID</th><th>引擎</th><th>类型</th><th>状态</th><th>订阅连接</th><th>最近同步</th><th>数量</th><th>失败原因</th><th>操作</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </div>
</div>
<div class="card">
  <div class="card-header">添加新的订阅连接</div>
  <div class="card-body">
    <form id="subscription-form" onsubmit="event.preventDefault(); addSubscription();">
      <p><label>名称</label><br><input class="form-input" name="name" placeholder="例如：个人维护书源合集"></p>
      <p><label>订阅连接</label><br><input class="form-input" name="url" placeholder="https://example.com/source.json" required style="max-width:720px"></p>
      <p><label>规则引擎</label><br>
        <select class="form-input" name="engine">
          <option value="legado">阅读/Legado</option>
          <option value="so_novel">So Novel</option>
        </select>
      </p>
      <p><label>订阅类型</label><br>
        <select class="form-input" name="kind">
          <option value="direct_json">直接 JSON 订阅</option>
          <option value="yiove_collections">Yiove 合集索引</option>
          <option value="github_tree_reference">仓库目录引用</option>
        </select>
      </p>
      <p><label>备注</label><br><input class="form-input" name="notes" style="max-width:720px"></p>
      <button class="btn btn-primary" type="submit">添加订阅</button>
    </form>
  </div>
</div>
<script>
function showSubscriptionResult(value) {{
  const pre = document.getElementById('subscription-result');
  pre.style.display = 'block';
  pre.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}}
async function syncSubscription(id) {{
  showSubscriptionResult('正在同步 ' + id + ' ...');
  const res = await fetch('/api/admin/source-subscriptions/' + encodeURIComponent(id) + '/sync', {{method:'POST'}});
  showSubscriptionResult(await res.json());
}}
async function syncAllSubscriptions() {{
  showSubscriptionResult('正在同步全部启用订阅...');
  const res = await fetch('/api/admin/source-subscriptions/sync-all', {{
    method:'POST',
    headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{includeDisabled:false}})
  }});
  showSubscriptionResult(await res.json());
}}
async function toggleSubscription(id, enabled) {{
  const res = await fetch('/api/admin/source-subscriptions/' + encodeURIComponent(id), {{
    method:'POST',
    headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{enabled}})
  }});
  showSubscriptionResult(await res.json());
  location.reload();
}}
async function addSubscription() {{
  const form = document.getElementById('subscription-form');
  const payload = {{
    name: form.name.value,
    url: form.url.value,
    engine: form.engine.value,
    kind: form.kind.value,
    notes: form.notes.value,
    enabled: true
  }};
  const res = await fetch('/api/admin/source-subscriptions', {{
    method:'POST',
    headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify(payload)
  }});
  showSubscriptionResult(await res.json());
  location.reload();
}}
</script>
"""
    return _render("订阅源管理", content, "subscriptions")


@router.get("/admin/sources/{source_id}", response_class=HTMLResponse)
def admin_source_detail(source_id: str) -> str:
    repo = SourceRepository()
    src = repo.get_source(source_id)
    if not src:
        content = '<div class="error-state">书源不存在</div>'
        return _render("书源详情", content, "sources")

    attempts = repo.get_attempts(source_id, limit=10)
    audit = RuleEngineAuditService(repo).audit_source(source_id)
    caps = src.get("parserCapabilities", {})
    caps_html = "<ul>" + "".join(f"<li>{k}: {v}</li>" for k, v in caps.items()) + "</ul>" if caps else "<p>-</p>"
    classification_names = {
        "source_defect": "书源缺陷",
        "engine_gap": "引擎缺口",
        "runtime_risk": "运行风险",
        "supported_static": "静态可支持",
    }
    audit_items = []
    for label, values in [
        ("书源缺陷", audit.get("sourceDefects", [])),
        ("引擎缺口", audit.get("engineGaps", [])),
        ("运行风险", audit.get("runtimeRisks", [])),
    ]:
        if values:
            audit_items.append(f"<p><strong>{label}:</strong> {'；'.join(_clean_text(v) for v in values)}</p>")
    if not audit_items:
        audit_items.append("<p>未发现明显静态缺陷。仍需通过单源测试验证站点可访问性和解析结果。</p>")
    audit_html = f"""
<div class="panel-group">
  <div class="panel-header">规则引擎静态审查</div>
  <div class="panel-body">
    <p><strong>分类:</strong> {classification_names.get(audit.get('classification'), audit.get('classification','unknown'))}</p>
    {''.join(audit_items)}
  </div>
</div>
"""

    if not attempts:
        attempts_html = '<p class="empty-state">暂无调用记录</p>'
    else:
        attempts_html = '<table><thead><tr><th>阶段</th><th>状态</th><th>代理</th><th>耗时</th><th>错误</th><th>时间</th></tr></thead><tbody>'
        for a in attempts:
            status_tag = '<span class="tag tag-success">成功</span>' if a.get("directStatus") == "success" or a.get("proxyStatus") == "success" else '<span class="tag tag-error">失败</span>'
            attempts_html += f"""<tr>
<td>{a['stage']}</td>
<td>{status_tag}</td>
<td>{'是' if a['proxyUsed'] else '否'}</td>
<td>{a['latencyMs']}ms</td>
<td>{a['error'] or '-'}</td>
<td>{a['createdAt']}</td>
</tr>"""
        attempts_html += "</tbody></table>"

    test_result = src.get("lastTestResult")
    test_html = ""
    if test_result:
        test_pass = "通过" if test_result.get("pass") else "失败"
        test_color = "var(--success)" if test_result.get("pass") else "var(--error)"
        test_html = f"""
<div class="panel-group">
  <div class="panel-header">最后测试结果</div>
  <div class="panel-body">
    <p><strong>结果:</strong> <span style="color:{test_color}">{test_pass}</span></p>
    <p><strong>阶段:</strong> {test_result.get('stage','-')}</p>
    <p><strong>代理:</strong> {'是' if test_result.get('proxyUsed') else '否'}</p>
    <p><strong>耗时:</strong> {test_result.get('latencyMs','-')}ms</p>
    <p><strong>错误:</strong> {test_result.get('error','-')}</p>
  </div>
</div>
"""

    content = f"""
<div class="page-title">书源详情: {_clean_text(src['bookSourceName']) or source_id}</div>
<div class="card">
  <div class="card-header">基本信息</div>
  <div class="card-body">
    <p><strong>ID:</strong> {src['sourceId']}</p>
    <p><strong>名称:</strong> {_clean_text(src['bookSourceName'])}</p>
    <p><strong>URL:</strong> {src['bookSourceUrl']}</p>
    <p><strong>文件:</strong> {src['sourceFilePath']} [索引: {src['sourceIndex']}]</p>
    <p><strong>状态:</strong> {'启用' if src['enabled'] else '禁用'}</p>
    <p><strong>健康:</strong> {src['healthStatus']}</p>
    <p><strong>代理模式:</strong> {src['proxyMode']}</p>
    <p><strong>代理状态:</strong> {src['proxyStatus']}</p>
    <p><strong>失败原因:</strong> {src['failureReason'] or '-'}</p>
    <p><strong>成功/失败次数:</strong> {src['successCount']} / {src['failureCount']}</p>
  </div>
</div>
{test_html}
{audit_html}
<div class="card">
  <div class="card-header">解析能力</div>
  <div class="card-body">{caps_html}</div>
</div>
<div class="card">
  <div class="card-header">调用历史</div>
  <div class="card-body">{attempts_html}</div>
</div>
<div class="card">
  <div class="card-header">测试书源</div>
  <div class="card-body">
    <form action="/api/admin/sources/{source_id}/test" method="post" onsubmit="event.preventDefault(); testSource();">
      <p>
        <label>关键词:</label><br>
        <input type="text" name="keyword" value="凡人修仙传" class="form-input">
      </p>
      <p>
        <label>测试阶段:</label><br>
        <select name="stage" class="form-input">
          <option value="search">搜索</option>
          <option value="detail">详情</option>
          <option value="toc">目录</option>
          <option value="content">正文</option>
        </select>
      </p>
      <p>
        <label>代理模式覆盖:</label><br>
        <select name="proxyMode" class="form-input">
          <option value="">默认</option>
          <option value="auto">自动</option>
          <option value="always">始终代理</option>
          <option value="never">永不代理</option>
        </select>
      </p>
      <button type="submit" class="btn btn-primary">开始测试</button>
    </form>
    <pre id="test-result" style="margin-top:16px;display:none"></pre>
    <script>
    async function testSource() {{
      const form = document.querySelector('form');
      const data = {{
        keyword: form.keyword.value,
        stage: form.stage.value,
        proxyMode: form.proxyMode.value || null
      }};
      const pre = document.getElementById('test-result');
      pre.style.display = 'block';
      pre.textContent = '测试中...';
      try {{
        const res = await fetch('/api/admin/sources/{source_id}/test', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify(data)
        }});
        const json = await res.json();
        pre.textContent = JSON.stringify(json, null, 2);
      }} catch(e) {{
        pre.textContent = '错误: ' + e.message;
      }}
    }}
    </script>
  </div>
</div>
"""
    return _render("书源详情", content, "sources")


@router.get("/admin/search", response_class=HTMLResponse)
def admin_search() -> str:
    content = """
<div class="page-title">搜索工作台</div>
<div class="card">
  <div class="card-body">
    <form action="/admin/search" method="get">
      <input type="text" name="keyword" placeholder="输入书名或关键词" class="form-input" required style="display:inline-block;width:auto;min-width:300px;">
      <button type="submit" class="btn btn-primary" style="margin-left:8px">搜索</button>
    </form>
  </div>
</div>
<div class="stats-grid" id="search-stats" style="display:none">
  <div class="stat-box"><div class="stat-value" id="stat-source-count">0</div><div class="stat-label">计划调用书源</div></div>
  <div class="stat-box"><div class="stat-value" id="stat-completed-count">0</div><div class="stat-label">已完成调用</div></div>
  <div class="stat-box"><div class="stat-value" id="stat-result-count">0</div><div class="stat-label">实时结果</div></div>
  <div class="stat-box"><div class="stat-value" id="stat-error-count">0</div><div class="stat-label">失败书源</div></div>
  <div class="stat-box"><div class="stat-value" id="stat-elapsed">0ms</div><div class="stat-label">耗时</div></div>
</div>
<hr class="section-divider" id="search-divider" style="display:none">
<div style="display:grid;grid-template-columns:minmax(360px, 0.9fr) minmax(520px, 1.3fr);gap:16px;align-items:start">
  <div class="card" id="source-calls-card" style="display:none">
    <div class="card-header">书源调用进度</div>
    <div class="card-body">
      <div class="table-wrap">
        <table>
          <thead><tr><th>书源</th><th>状态</th><th>结果</th><th>耗时</th><th>代理</th><th>失败原因</th></tr></thead>
          <tbody id="source-calls-body"></tbody>
        </table>
      </div>
    </div>
  </div>
  <div class="card" id="search-results-card" style="display:none">
    <div class="card-header">实时搜索结果</div>
    <div class="card-body">
      <div class="table-wrap">
        <table>
          <thead><tr><th>书名</th><th>作者</th><th>最新章节</th><th>来源</th><th>操作</th></tr></thead>
          <tbody id="search-results-body"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>
<div id="search-state"></div>
<script>
const params = new URLSearchParams(location.search);
const keyword = params.get('keyword');
let eventSource = null;
let startedAt = 0;
let resultCount = 0;
let errorCount = 0;
const sourceRows = new Map();

function htmlEscape(value) {
  return String(value || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function setSearchVisible() {
  document.getElementById('search-stats').style.display = 'grid';
  document.getElementById('search-divider').style.display = 'block';
  document.getElementById('source-calls-card').style.display = 'block';
  document.getElementById('search-results-card').style.display = 'block';
}

function tag(label, cls) {
  return '<span class="tag ' + cls + '">' + htmlEscape(label) + '</span>';
}

function ensureSourceRow(sourceId, sourceName) {
  const body = document.getElementById('source-calls-body');
  if (sourceRows.has(sourceId)) return sourceRows.get(sourceId);
  const row = document.createElement('tr');
  row.dataset.sourceId = sourceId;
  row.innerHTML =
    '<td><a href="/admin/sources/' + encodeURIComponent(sourceId) + '">' + htmlEscape(sourceName || sourceId) + '</a><br><span style="color:var(--text-secondary)">' + htmlEscape(sourceId) + '</span></td>' +
    '<td>' + tag('等待中', 'tag-muted') + '</td>' +
    '<td>0</td><td>-</td><td>-</td><td>-</td>';
  body.appendChild(row);
  sourceRows.set(sourceId, row);
  return row;
}

function updateSourceRow(event) {
  const row = ensureSourceRow(event.sourceId, event.sourceName);
  if (event.type === 'source_start') {
    row.children[1].innerHTML = tag('调用中', 'tag-info');
    row.children[4].textContent = event.proxyMode || 'auto';
    return;
  }
  if (event.status === 'success') {
    row.children[1].innerHTML = tag('完成', 'tag-success');
  } else {
    row.children[1].innerHTML = tag('失败', 'tag-error');
  }
  row.children[2].textContent = event.resultCount || 0;
  row.children[3].textContent = (event.latencyMs || 0) + 'ms';
  row.children[4].textContent = event.proxyUsed ? '是' : '否';
  row.children[5].textContent = event.error ? (event.error.error || '-') : '-';
}

function addResult(item, sourceName) {
  resultCount += 1;
  document.getElementById('stat-result-count').textContent = resultCount;
  const body = document.getElementById('search-results-body');
  const row = document.createElement('tr');
  row.innerHTML =
    '<td><a href="/admin/books/' + encodeURIComponent(item.bookId) + '">' + htmlEscape(item.name || '-') + '</a></td>' +
    '<td>' + htmlEscape(item.author || '-') + '</td>' +
    '<td>' + htmlEscape(item.lastChapter || '-') + '</td>' +
    '<td>' + htmlEscape(sourceName || item.sourceName || item.sourceId || '-') + '</td>' +
    '<td><a href="/admin/books/' + encodeURIComponent(item.bookId) + '" class="btn btn-sm">详情</a></td>';
  body.appendChild(row);
}

function startRealtimeSearch(searchKeyword) {
  if (eventSource) eventSource.close();
  startedAt = Date.now();
  resultCount = 0;
  errorCount = 0;
  sourceRows.clear();
  setSearchVisible();
  document.getElementById('source-calls-body').innerHTML = '';
  document.getElementById('search-results-body').innerHTML = '';
  document.getElementById('search-state').innerHTML = '<div class="loading-state">正在建立搜索流...</div>';
  const timer = setInterval(() => {
    if (startedAt) document.getElementById('stat-elapsed').textContent = (Date.now() - startedAt) + 'ms';
  }, 250);

  eventSource = new EventSource('/api/admin/search/stream?keyword=' + encodeURIComponent(searchKeyword) + '&page=1');
  eventSource.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.type === 'summary') {
      document.getElementById('stat-source-count').textContent = event.sourceCount;
      document.getElementById('stat-completed-count').textContent = '0';
      document.getElementById('stat-error-count').textContent = '0';
      document.getElementById('search-state').innerHTML = '<div class="partial-state">开始调用 ' + event.sourceCount + ' 个书源，每批 ' + event.batchSize + ' 个，最大并发 ' + event.maxConcurrency + '</div>';
    } else if (event.type === 'source_start') {
      updateSourceRow(event);
    } else if (event.type === 'source_done') {
      updateSourceRow(event);
      document.getElementById('stat-completed-count').textContent = event.completedCount;
      if (event.status === 'error') {
        errorCount += 1;
        document.getElementById('stat-error-count').textContent = errorCount;
      }
    } else if (event.type === 'result') {
      addResult(event.item, event.sourceName);
    } else if (event.type === 'batch_done') {
      document.getElementById('search-state').innerHTML = '<div class="partial-state">第 ' + event.batchIndex + ' 批完成，已完成 ' + event.completedCount + ' / ' + event.sourceCount + '</div>';
    } else if (event.type === 'overall_timeout') {
      document.getElementById('search-state').innerHTML = '<div class="partial-state">整体搜索超时，正在收尾已返回结果。</div>';
    } else if (event.type === 'done') {
      clearInterval(timer);
      eventSource.close();
      const debug = event.debug || {};
      document.getElementById('stat-elapsed').textContent = (debug.elapsedMs || (Date.now() - startedAt)) + 'ms';
      document.getElementById('stat-error-count').textContent = debug.errorCount || errorCount;
      if (resultCount === 0) {
        document.getElementById('search-state').innerHTML = '<div class="empty-state">搜索完成，没有实时结果。请查看左侧书源失败原因。</div>';
      } else {
        document.getElementById('search-state').innerHTML = '<div class="partial-state">搜索完成，合并后结果 ' + (event.items ? event.items.length : resultCount) + ' 条。</div>';
      }
      startedAt = 0;
    }
  };
  eventSource.onerror = () => {
    clearInterval(timer);
    if (eventSource) eventSource.close();
    document.getElementById('search-state').innerHTML = '<div class="error-state">搜索流连接中断。</div>';
    startedAt = 0;
  };
}

if (keyword) {
  document.querySelector('input[name=keyword]').value = keyword;
  startRealtimeSearch(keyword);
}
</script>
"""
    return _render("搜索工作台", content, "search")


@router.get("/admin/explore", response_class=HTMLResponse)
def admin_explore() -> str:
    content = """
<div class="page-title">发现 / 排行榜</div>
<div class="card">
  <div class="card-body">
    <p style="color:var(--text-secondary)">选择书源和分类，加载发现或排行榜结果。</p>
    <div id="explore-controls">
      <select id="explore-source" class="form-input" style="display:inline-block;width:auto;min-width:280px;" onchange="loadGroups()">
        <option value="">-- 选择书源 --</option>
      </select>
      <select id="explore-group" class="form-input" style="display:inline-block;width:auto;min-width:280px;margin-left:8px;display:none" onchange="loadItems()">
        <option value="">-- 选择分类 --</option>
      </select>
      <button class="btn btn-primary" style="margin-left:8px" onclick="loadItems()" id="explore-load-btn" style="display:none">加载</button>
    </div>
    <pre id="explore-result" style="display:none;margin-top:16px"></pre>
  </div>
</div>
<div class="card" id="explore-items-card" style="display:none">
  <div class="card-header">分类结果</div>
  <div class="card-body">
    <div class="table-wrap">
      <table>
        <thead><tr><th>书名</th><th>作者</th><th>最新章节</th><th>来源</th><th>操作</th></tr></thead>
        <tbody id="explore-items-body"></tbody>
      </table>
    </div>
  </div>
</div>
<script>
let currentGroups = [];

async function loadSources() {
  const res = await fetch('/api/admin/explore/sources');
  const data = await res.json();
  const sel = document.getElementById('explore-source');
  sel.innerHTML = '<option value="">-- 选择书源 --</option>';
  for (const src of data.items || []) {
    const opt = document.createElement('option');
    opt.value = src.sourceId;
    opt.textContent = (src.bookSourceName || src.sourceId);
    sel.appendChild(opt);
  }
}

async function loadGroups() {
  const sourceId = document.getElementById('explore-source').value;
  const groupSel = document.getElementById('explore-group');
  const btn = document.getElementById('explore-load-btn');
  document.getElementById('explore-items-card').style.display = 'none';
  if (!sourceId) {
    groupSel.style.display = 'none';
    btn.style.display = 'none';
    return;
  }
  const res = await fetch('/api/admin/explore/sources/' + encodeURIComponent(sourceId) + '/groups');
  const data = await res.json();
  currentGroups = data.groups || [];
  groupSel.innerHTML = '<option value="">-- 选择分类 --</option>';
  currentGroups.forEach((g, i) => {
    const opt = document.createElement('option');
    opt.value = i;
    opt.textContent = g.title || '未命名';
    groupSel.appendChild(opt);
  });
  groupSel.style.display = 'inline-block';
  btn.style.display = 'inline-block';
}

async function loadItems() {
  const sourceId = document.getElementById('explore-source').value;
  const idx = document.getElementById('explore-group').value;
  if (!sourceId || idx === '') return;
  const group = currentGroups[idx];
  const pre = document.getElementById('explore-result');
  pre.style.display = 'block';
  pre.textContent = '加载中...';
  const res = await fetch('/api/admin/explore/sources/' + encodeURIComponent(sourceId) + '/items', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({exploreUrl: group.url, page: 1})
  });
  const data = await res.json();
  pre.textContent = JSON.stringify(data, null, 2);

  const tbody = document.getElementById('explore-items-body');
  tbody.innerHTML = '';
  const items = data.items || [];
  for (const item of items) {
    const row = document.createElement('tr');
    row.innerHTML =
      '<td><a href="/admin/books/' + encodeURIComponent(item.bookId) + '">' + (item.name || '-') + '</a></td>' +
      '<td>' + (item.author || '-') + '</td>' +
      '<td>' + (item.lastChapter || '-') + '</td>' +
      '<td>' + (item.sourceName || '-') + '</td>' +
      '<td><a href="/admin/books/' + encodeURIComponent(item.bookId) + '" class="btn btn-sm">详情</a></td>';
    tbody.appendChild(row);
  }
  document.getElementById('explore-items-card').style.display = items.length ? 'block' : 'none';
}

loadSources();
</script>
"""
    return _render("发现 / 排行榜", content, "explore")


@router.get("/admin/books", response_class=HTMLResponse)
def admin_books() -> str:
    import sqlite3
    from app.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT book_id, name, author, last_chapter, last_seen_at FROM book_records ORDER BY last_seen_at DESC LIMIT 100"
        ).fetchall()

    if not rows:
        rows_html = '<tr><td colspan="5" class="empty-state">暂无书籍记录</td></tr>'
    else:
        rows_html = ""
        for r in rows:
            rows_html += f"""<tr>
<td><a href="/admin/books/{r[0]}">{r[1] or '-'}</a></td>
<td>{r[2] or '-'}</td>
<td>{r[3] or '-'}</td>
<td>{r[4] or '-'}</td>
<td><a href="/admin/books/{r[0]}" class="btn btn-sm">详情</a></td>
</tr>"""

    content = f"""
<div class="page-title">书籍记录</div>
<div class="card">
  <div class="card-header">已访问书籍</div>
  <div class="card-body">
    <div class="table-wrap">
      <table>
        <thead><tr><th>书名</th><th>作者</th><th>最新章节</th><th>最后访问</th><th>操作</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
  </div>
</div>
"""
    return _render("书籍记录", content, "books")


@router.get("/admin/books/{book_id}", response_class=HTMLResponse)
def admin_book_detail(book_id: str) -> str:
    import sqlite3
    from app.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT book_id, name, author, last_chapter, last_seen_at FROM book_records WHERE book_id = ?",
            (book_id,),
        ).fetchone()
    if not row:
        content = '<div class="error-state">书籍不存在</div>'
        return _render("书籍详情", content, "books")

    content = f"""
<div class="page-title">书籍详情</div>
<div class="card">
  <div class="card-header">{row[1] or '未知书名'}</div>
  <div class="card-body">
    <p><strong>ID:</strong> {row[0]}</p>
    <p><strong>作者:</strong> {row[2] or '-'}</p>
    <p><strong>最新章节:</strong> {row[3] or '-'}</p>
    <p><strong>最后访问:</strong> {row[4] or '-'}</p>
    <hr class="section-divider">
    <a href="/api/legado/book/{row[0]}/toc" target="_blank" class="btn btn-primary">查看目录</a>
    <a href="/admin/reader?book_id={row[0]}" class="btn" style="margin-left:8px">进入阅读</a>
    <button class="btn" style="margin-left:8px" onclick="enableTracking('{row[0]}')">开启追更</button>
    <pre id="track-result" style="display:none;margin-top:16px"></pre>
    <script>
    async function enableTracking(bookId) {{
      const res = await fetch('/api/admin/update-tasks/' + encodeURIComponent(bookId) + '/enable', {{method:'POST'}});
      const pre = document.getElementById('track-result');
      pre.style.display = 'block';
      pre.textContent = JSON.stringify(await res.json(), null, 2);
    }}
    </script>
  </div>
</div>
"""
    return _render("书籍详情", content, "books")


@router.get("/admin/reader", response_class=HTMLResponse)
def admin_reader() -> str:
    content = """
<div class="page-title">阅读器</div>
<div class="card">
  <div class="card-body">
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <input type="text" id="reader-book-id" class="form-input" placeholder="书籍ID" style="width:auto;min-width:200px">
      <input type="text" id="reader-chapter-id" class="form-input" placeholder="章节ID" style="width:auto;min-width:200px">
      <button class="btn btn-primary" onclick="loadChapter()">加载章节</button>
      <button class="btn" onclick="loadToc()">加载目录</button>
    </div>
    <pre id="reader-state" style="display:none;margin-top:16px"></pre>
  </div>
</div>
<div class="card" id="reader-card" style="display:none">
  <div class="card-header" id="reader-title">章节标题</div>
  <div class="card-body">
    <div class="reader-content" id="reader-content">正文内容</div>
    <div class="reader-nav">
      <button class="btn" id="reader-prev" onclick="navChapter('prev')">上一章</button>
      <span id="reader-source-trace" style="color:var(--text-secondary);font-size:12px"></span>
      <button class="btn btn-primary" id="reader-next" onclick="navChapter('next')">下一章</button>
    </div>
    <div style="margin-top:12px">
      <button class="btn btn-sm btn-danger" onclick="tryFallback()">尝试换源</button>
      <span id="fallback-status" style="margin-left:8px;color:var(--text-secondary);font-size:12px"></span>
    </div>
  </div>
</div>
<div class="card" id="toc-card" style="display:none">
  <div class="card-header">目录</div>
  <div class="card-body">
    <div class="table-wrap">
      <table>
        <thead><tr><th>章节</th><th>操作</th></tr></thead>
        <tbody id="toc-body"></tbody>
      </table>
    </div>
  </div>
</div>
<script>
let currentBookId = '';
let currentChapterId = '';
let currentToc = [];

function getQuery(name) {
  return new URLSearchParams(location.search).get(name);
}

async function loadChapter(chapterIdOverride) {
  const chapterId = chapterIdOverride || document.getElementById('reader-chapter-id').value;
  if (!chapterId) return;
  currentChapterId = chapterId;
  const state = document.getElementById('reader-state');
  state.style.display = 'block';
  state.textContent = '加载中...';
  const res = await fetch('/api/admin/chapter/' + encodeURIComponent(chapterId));
  const data = await res.json();
  state.textContent = '';
  document.getElementById('reader-card').style.display = 'block';
  document.getElementById('reader-title').textContent = data.title || '无标题';
  document.getElementById('reader-content').textContent = data.content || '无内容';
  document.getElementById('reader-source-trace').textContent = '';
  document.getElementById('fallback-status').textContent = '';
  updateNav();
}

async function loadToc() {
  const bookId = document.getElementById('reader-book-id').value || getQuery('book_id');
  if (!bookId) return;
  currentBookId = bookId;
  const res = await fetch('/api/admin/books/' + encodeURIComponent(bookId) + '/toc');
  const data = await res.json();
  currentToc = data.chapters || [];
  const tbody = document.getElementById('toc-body');
  tbody.innerHTML = '';
  for (const ch of currentToc) {
    const row = document.createElement('tr');
    row.innerHTML = '<td>' + (ch.title || '-') + '</td>' +
      '<td><button class="btn btn-sm" onclick="loadChapter(\\'' + (ch.chapterId || '') + '\\')">阅读</button></td>';
    tbody.appendChild(row);
  }
  document.getElementById('toc-card').style.display = currentToc.length ? 'block' : 'none';
}

async function updateNav() {
  if (!currentBookId || !currentChapterId) return;
  const res = await fetch('/api/admin/books/' + encodeURIComponent(currentBookId) + '/chapters/' + encodeURIComponent(currentChapterId) + '/navigation');
  const nav = await res.json();
  const prevBtn = document.getElementById('reader-prev');
  const nextBtn = document.getElementById('reader-next');
  prevBtn.disabled = !nav.prev;
  nextBtn.disabled = !nav.next;
  prevBtn.textContent = nav.prev ? '上一章: ' + (nav.prevTitle || '') : '已是第一章';
  nextBtn.textContent = nav.next ? '下一章: ' + (nav.nextTitle || '') : '已是最后一章';
}

async function navChapter(direction) {
  if (!currentBookId || !currentChapterId) return;
  const res = await fetch('/api/admin/books/' + encodeURIComponent(currentBookId) + '/chapters/' + encodeURIComponent(currentChapterId) + '/navigation');
  const nav = await res.json();
  const target = direction === 'prev' ? nav.prev : nav.next;
  if (target) {
    document.getElementById('reader-chapter-id').value = target;
    await loadChapter(target);
  }
}

async function tryFallback() {
  if (!currentChapterId) return;
  const status = document.getElementById('fallback-status');
  status.textContent = '尝试换源中...';
  const res = await fetch('/api/admin/chapter/' + encodeURIComponent(currentChapterId) + '/fallback');
  const data = await res.json();
  if (data.fallbackUsed) {
    document.getElementById('reader-title').textContent = data.title || '无标题';
    document.getElementById('reader-content').textContent = data.content || '无内容';
    status.textContent = '换源成功: ' + (data.fallbackSourceId || '');
  } else {
    status.textContent = '换源失败: ' + JSON.stringify(data.fallbackTrace || []);
  }
}

const initBookId = getQuery('book_id');
if (initBookId) {
  document.getElementById('reader-book-id').value = initBookId;
  currentBookId = initBookId;
  loadToc();
}
</script>
"""
    return _render("阅读器", content, "books")


@router.get("/admin/update-tasks", response_class=HTMLResponse)
def admin_update_tasks() -> str:
    import sqlite3
    from app.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT book_id, last_check_time, next_check_time, status, error_count, last_error FROM update_tasks ORDER BY next_check_time LIMIT 100"
        ).fetchall()

    if not rows:
        rows_html = '<tr><td colspan="7" class="empty-state">暂无更新任务</td></tr>'
    else:
        rows_html = ""
        for r in rows:
            status_tag = '<span class="tag tag-success">活跃</span>' if r[3] == 'active' else '<span class="tag tag-muted">' + (r[3] or '-') + '</span>'
            rows_html += f"""<tr>
<td>{r[0]}</td>
<td>{r[1] or '-'}</td>
<td>{r[2] or '-'}</td>
<td>{status_tag}</td>
<td>{r[4]}</td>
<td>{r[5] or '-'}</td>
<td>
  <button class="btn btn-sm" onclick="runUpdate('{r[0]}')">立即检查</button>
  <button class="btn btn-sm" onclick="toggleUpdate('{r[0]}', false)">停用</button>
</td>
</tr>"""

    content = f"""
<div class="page-title">更新任务</div>
<div class="card">
  <div class="card-header">追更任务列表</div>
  <div class="card-body">
    <div class="table-wrap">
      <table>
        <thead><tr><th>书籍ID</th><th>最后检查</th><th>下次检查</th><th>状态</th><th>错误次数</th><th>最后错误</th><th>操作</th></tr></thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
  </div>
</div>
<pre id="update-result" style="display:none"></pre>
<script>
async function runUpdate(bookId) {{
  const pre = document.getElementById('update-result');
  pre.style.display = 'block';
  pre.textContent = '检查 ' + bookId + ' ...';
  const res = await fetch('/api/admin/update-tasks/' + encodeURIComponent(bookId) + '/run', {{method:'POST'}});
  pre.textContent = JSON.stringify(await res.json(), null, 2);
}}
async function toggleUpdate(bookId, enabled) {{
  const endpoint = enabled ? '/enable' : '/disable';
  await fetch('/api/admin/update-tasks/' + encodeURIComponent(bookId) + endpoint, {{method:'POST'}});
  location.reload();
}}
</script>
"""
    return _render("更新任务", content, "update")


@router.get("/admin/cache", response_class=HTMLResponse)
def admin_cache() -> str:
    import sqlite3
    from app.config import DB_PATH
    with sqlite3.connect(DB_PATH) as conn:
        search_count = conn.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0]
        book_count = conn.execute("SELECT COUNT(*) FROM book_cache").fetchone()[0]
        toc_count = conn.execute("SELECT COUNT(*) FROM toc_cache").fetchone()[0]
        chapter_count = conn.execute("SELECT COUNT(*) FROM chapter_cache").fetchone()[0]

    content = f"""
<div class="page-title">缓存管理</div>
<div class="stats-grid">
  <div class="stat-box">
    <div class="stat-value">{search_count}</div>
    <div class="stat-label">搜索缓存</div>
  </div>
  <div class="stat-box">
    <div class="stat-value">{book_count}</div>
    <div class="stat-label">书籍缓存</div>
  </div>
  <div class="stat-box">
    <div class="stat-value">{toc_count}</div>
    <div class="stat-label">目录缓存</div>
  </div>
  <div class="stat-box">
    <div class="stat-value">{chapter_count}</div>
    <div class="stat-label">章节缓存</div>
  </div>
</div>
<hr class="section-divider">
<div class="card">
  <div class="card-header">清理缓存</div>
  <div class="card-body">
    <button class="btn btn-danger" onclick="clearCache('all')">清理全部缓存</button>
    <button class="btn" style="margin-left:8px" onclick="clearCache('search')">仅搜索缓存</button>
    <button class="btn" style="margin-left:8px" onclick="clearCache('book')">仅书籍缓存</button>
    <button class="btn" style="margin-left:8px" onclick="clearCache('toc')">仅目录缓存</button>
    <button class="btn" style="margin-left:8px" onclick="clearCache('chapter')">仅章节缓存</button>
    <pre id="cache-result" style="display:none;margin-top:16px"></pre>
  </div>
</div>
<script>
async function clearCache(type) {{
  const pre = document.getElementById('cache-result');
  pre.style.display = 'block';
  pre.textContent = '清理中...';
  const res = await fetch('/api/admin/cache/clear', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{type}})
  }});
  pre.textContent = JSON.stringify(await res.json(), null, 2);
  location.reload();
}}
</script>
"""
    return _render("缓存管理", content, "cache")


@router.get("/admin/settings", response_class=HTMLResponse)
def admin_settings() -> str:
    pool = _read_json(SOURCE_POOL_CONFIG_PATH, {})
    proxy_url = pool.get("proxy", {}).get("url", "http://192.168.31.233:7890")
    batch_size = pool.get("source_batch_size", 20)
    max_concurrency = pool.get("max_concurrency", 6)
    source_timeout = pool.get("source_timeout_seconds", 8)
    overall_timeout = pool.get("overall_search_timeout_seconds", 30)
    max_sources = pool.get("max_sources_per_search", 200)

    content = f"""
<div class="page-title">设置</div>
<div class="card">
  <div class="card-header">运行设置</div>
  <div class="card-body">
    <form id="settings-form" onsubmit="event.preventDefault(); saveSettings();">
      <p>
        <label>默认代理地址</label><br>
        <input class="form-input" name="proxyUrl" value="{proxy_url}">
      </p>
      <p>
        <label>每批书源数量</label><br>
        <input class="form-input" name="sourceBatchSize" type="number" min="1" max="500" value="{batch_size}">
      </p>
      <p>
        <label>最大并发</label><br>
        <input class="form-input" name="maxConcurrency" type="number" min="1" max="100" value="{max_concurrency}">
      </p>
      <p>
        <label>单源超时秒数</label><br>
        <input class="form-input" name="sourceTimeout" type="number" min="1" max="120" value="{source_timeout}">
      </p>
      <p>
        <label>整体超时秒数</label><br>
        <input class="form-input" name="overallTimeout" type="number" min="1" max="600" value="{overall_timeout}">
      </p>
      <p>
        <label>单次搜索最多书源</label><br>
        <input class="form-input" name="maxSources" type="number" min="1" max="5000" value="{max_sources}">
      </p>
      <button class="btn btn-primary" type="submit">保存设置</button>
    </form>
    <pre id="settings-result" style="display:none;margin-top:16px"></pre>
  </div>
</div>
<script>
async function saveSettings() {{
  const form = document.getElementById('settings-form');
  const payload = {{
    sourcePool: {{
      source_batch_size: Number(form.sourceBatchSize.value),
      max_concurrency: Number(form.maxConcurrency.value),
      source_timeout_seconds: Number(form.sourceTimeout.value),
      overall_search_timeout_seconds: Number(form.overallTimeout.value),
      max_sources_per_search: Number(form.maxSources.value),
      proxy: {{
        enabled: true,
        url: form.proxyUrl.value,
        retry_on_failure: true,
        failure_status_codes: [403, 429, 451, 502, 503, 504],
        failure_error_keywords: ["timeout", "connection", "reset", "forbidden", "captcha", "blocked"]
      }}
    }}
  }};
  const pre = document.getElementById('settings-result');
  pre.style.display = 'block';
  pre.textContent = '保存中...';
  const res = await fetch('/api/admin/settings', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload)
  }});
  pre.textContent = JSON.stringify(await res.json(), null, 2);
}}
</script>
"""
    return _render("设置", content, "settings")


@router.get("/admin/rule-engines", response_class=HTMLResponse)
def admin_rule_engines() -> str:
    config = _read_json(RULE_ENGINES_CONFIG_PATH, {"engines": []})
    rows = ""
    for engine in config.get("engines", []):
        enabled_tag = '<span class="tag tag-success">启用</span>' if engine.get("enabled", True) else '<span class="tag tag-error">禁用</span>'
        default_tag = '<span class="tag tag-info">默认</span>' if engine.get("default") else '<span class="tag tag-muted">扩展</span>'
        rows += f"""<tr>
<td>{_clean_text(engine.get('name', ''))}</td>
<td>{engine.get('id', '')}</td>
<td>{engine.get('type', '')}</td>
<td>{enabled_tag}</td>
<td>{default_tag}</td>
<td>{_clean_text(engine.get('description', ''))}</td>
</tr>"""
    if not rows:
        rows = '<tr><td colspan="6" class="empty-state">暂无规则引擎配置</td></tr>'
    capability_rows = ""
    status_names = {"supported": "已支持", "limited": "受限支持", "unsupported": "暂不支持"}
    for cap in default_engine_report()["items"][0]["capabilities"]:
        status = cap.get("status", "")
        tag_class = "tag-success" if status == "supported" else ("tag-info" if status == "limited" else "tag-error")
        capability_rows += f"""<tr>
<td>{_clean_text(cap.get('name', ''))}</td>
<td>{cap.get('id', '')}</td>
<td><span class="tag {tag_class}">{status_names.get(status, status)}</span></td>
<td>{_clean_text(cap.get('notes', ''))}</td>
</tr>"""
    content = f"""
<div class="page-title">规则引擎</div>
<div class="card">
  <div class="card-header">书源规则引擎</div>
  <div class="card-body">
    <div class="table-wrap">
      <table>
        <thead><tr><th>名称</th><th>ID</th><th>类型</th><th>状态</th><th>角色</th><th>说明</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </div>
</div>
<hr class="section-divider">
<div class="card">
  <div class="card-header">能力矩阵</div>
  <div class="card-body">
    <div class="table-wrap">
      <table>
        <thead><tr><th>能力</th><th>ID</th><th>状态</th><th>说明</th></tr></thead>
        <tbody>{capability_rows}</tbody>
      </table>
    </div>
  </div>
</div>
"""
    return _render("规则引擎", content, "settings")


@router.get("/admin/rule-audit", response_class=HTMLResponse)
def admin_rule_audit() -> str:
    service = RuleEngineAuditService()
    data = service.audit_all(limit=100)
    stats = data.get("stats", {})
    names = {
        "source_defect": "书源缺陷",
        "engine_gap": "引擎缺口",
        "runtime_risk": "运行风险",
        "supported_static": "静态可支持",
        "unknown": "未知",
    }
    rows = ""
    for audit in data.get("items", []):
        source = audit.get("source", {})
        cls = audit.get("classification", "unknown")
        if cls == "source_defect":
            cls_tag = '<span class="tag tag-error">书源缺陷</span>'
        elif cls == "engine_gap":
            cls_tag = '<span class="tag tag-warning">引擎缺口</span>'
        elif cls == "runtime_risk":
            cls_tag = '<span class="tag tag-info">运行风险</span>'
        else:
            cls_tag = '<span class="tag tag-success">静态可支持</span>'
        reasons = []
        reasons.extend(audit.get("sourceDefects", []))
        reasons.extend(audit.get("engineGaps", []))
        reasons.extend(audit.get("runtimeRisks", []))
        reason_text = "；".join(_clean_text(item) for item in reasons) or "-"
        rows += f"""<tr>
<td><a href="/admin/sources/{source.get('sourceId', audit.get('sourceId',''))}">{_clean_text(source.get('bookSourceName','')) or audit.get('sourceId','')}</a></td>
<td>{source.get('sourceId', audit.get('sourceId',''))}</td>
<td>{cls_tag}</td>
<td>{reason_text}</td>
<td>{_clean_text(source.get('failureReason','')) or '-'}</td>
</tr>"""
    if not rows:
        rows = '<tr><td colspan="5" class="empty-state">暂无可审查的书源索引。请先同步或扫描书源。</td></tr>'

    stat_boxes = ""
    for key in ["supported_static", "runtime_risk", "engine_gap", "source_defect"]:
        stat_boxes += f"""<div class="stat-box">
  <div class="stat-value">{stats.get(key, 0)}</div>
  <div class="stat-label">{names.get(key, key)}</div>
</div>"""

    content = f"""
<div class="page-title">规则引擎审查</div>
<div class="stats-grid">{stat_boxes}</div>
<hr class="section-divider">
<div class="card">
  <div class="card-header">静态审查结果</div>
  <div class="card-body">
    <p style="color:var(--text-secondary);max-width:920px">这里用于区分书源自身缺陷、当前阅读规则引擎能力缺口和需要运行时验证的访问风险。静态可支持不代表站点一定可访问，仍需要单书源测试确认搜索、详情、目录和正文链路。</p>
    <div class="table-wrap">
      <table>
        <thead><tr><th>书源</th><th>ID</th><th>分类</th><th>审查原因</th><th>运行失败原因</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </div>
</div>
"""
    return _render("规则引擎审查", content, "settings")


@router.get("/admin/aggregate-source", response_class=HTMLResponse)
def admin_aggregate_source() -> str:
    config = load_aggregate_config()
    progress = config.get("parser_progress", {})

    content = f"""
<div class="page-title">聚合书源</div>
<div class="card">
  <div class="card-header">配置信息</div>
  <div class="card-body">
    <p><strong>名称:</strong> {config.get('name','')}</p>
    <p><strong>版本:</strong> {config.get('version','')}</p>
    <p><strong>分组:</strong> {config.get('group','')}</p>
    <p><strong>生成路径:</strong> {config.get('generated_path','')}</p>
    <p><strong>最后生成:</strong> {config.get('last_generated_at','-')}</p>
  </div>
</div>
<div class="card">
  <div class="card-header">解析进度</div>
  <div class="card-body">
    <p><strong>已配置书源:</strong> {progress.get('configured_sources',0)}</p>
    <p><strong>已启用书源:</strong> {progress.get('enabled_sources',0)}</p>
    <p><strong>健康书源:</strong> {progress.get('healthy_sources',0)}</p>
    <p><strong>代理书源:</strong> {progress.get('proxy_sources',0)}</p>
    <p><strong>不支持书源:</strong> {progress.get('unsupported_sources',0)}</p>
  </div>
</div>
<div class="card">
  <div class="card-header">操作</div>
  <div class="card-body">
    <a href="/api/admin/aggregate-source/regenerate" class="btn btn-primary">重新生成聚合书源</a>
  </div>
</div>
"""
    return _render("聚合书源", content, "settings")


@router.get("/admin/verification", response_class=HTMLResponse)
def admin_verification() -> str:
    content = """
<div class="page-title">验证中心</div>
<div class="card">
  <div class="card-header">模拟测试</div>
  <div class="card-body">
    <p style="color:var(--text-secondary)">运行 API 和 UI 模拟测试，验证核心功能在无真实网络环境下的表现。</p>
    <button class="btn btn-primary" onclick="runVerification('all')">运行全部模拟</button>
    <button class="btn" style="margin-left:8px" onclick="runVerification('api')">仅 API 模拟</button>
    <button class="btn" style="margin-left:8px" onclick="runVerification('ui')">仅 UI 模拟</button>
    <pre id="verification-result" style="display:none;margin-top:16px"></pre>
  </div>
</div>
<div class="card">
  <div class="card-header">最近报告</div>
  <div class="card-body">
    <pre id="verification-report">加载中...</pre>
  </div>
</div>
<script>
async function runVerification(category) {
  const pre = document.getElementById('verification-result');
  pre.style.display = 'block';
  pre.textContent = '运行中...';
  const res = await fetch('/api/admin/verification/run', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({category})
  });
  const data = await res.json();
  pre.textContent = JSON.stringify(data, null, 2);
  loadReport();
}
async function loadReport() {
  const res = await fetch('/api/admin/verification');
  const data = await res.json();
  document.getElementById('verification-report').textContent = JSON.stringify(data, null, 2);
}
loadReport();
</script>
"""
    return _render("验证中心", content, "verification")
