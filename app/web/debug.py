"""Server-rendered HTML debug UI for LegadoHub."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.services.catalog import Catalog
from app.services.cache import Cache
from app.services.source_pool import SourcePool

router = APIRouter()


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LegadoHub Debug</title>
<style>
body { font-family: system-ui, -apple-system, sans-serif; margin: 20px; background: #f5f5f5; }
.card { background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
h1 { margin-top: 0; }
input[type="text"] { padding: 8px 12px; font-size: 16px; border: 1px solid #ddd; border-radius: 4px; width: 300px; }
button { padding: 8px 16px; font-size: 16px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }
button:hover { background: #0056b3; }
table { width: 100%; border-collapse: collapse; margin-top: 10px; }
th, td { text-align: left; padding: 10px; border-bottom: 1px solid #eee; }
th { background: #f8f9fa; }
.error { color: #dc3545; background: #f8d7da; padding: 10px; border-radius: 4px; }
.debug { background: #e9ecef; padding: 10px; border-radius: 4px; font-family: monospace; font-size: 12px; }
a { color: #007bff; text-decoration: none; }
a:hover { text-decoration: underline; }
pre { white-space: pre-wrap; word-break: break-all; background: #f8f9fa; padding: 10px; border-radius: 4px; overflow-x: auto; }
.tag { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 12px; margin-left: 4px; }
.tag-direct { background: #d4edda; color: #155724; }
.tag-proxy { background: #fff3cd; color: #856404; }
.tag-failed { background: #f8d7da; color: #721c24; }
.tag-forced { background: #d1ecf1; color: #0c5460; }
</style>
</head>
<body>
{content}
</body>
</html>"""


def _proxy_badge(status: str) -> str:
    mapping = {
        "direct_ok": ('<span class="tag tag-direct">direct_ok</span>', "直连成功"),
        "proxy_succeeded": ('<span class="tag tag-proxy">proxy_succeeded</span>', "代理成功"),
        "forced_proxy": ('<span class="tag tag-forced">forced_proxy</span>', "强制代理"),
        "direct_failed": ('<span class="tag tag-failed">direct_failed</span>', "直连失败"),
        "proxy_failed": ('<span class="tag tag-failed">proxy_failed</span>', "代理失败"),
    }
    return mapping.get(status, (f'<span class="tag">{status}</span>', status))[0]


@router.get("/debug", response_class=HTMLResponse)
def debug_index() -> str:
    content = """
<div class="card">
<h1>LegadoHub Debug UI</h1>
<form action="/debug/search" method="get">
<input type="text" name="keyword" placeholder="输入书名或关键词" required>
<button type="submit">搜索</button>
</form>
</div>
"""
    return HTML_TEMPLATE.replace("{content}", content)


@router.get("/debug/search", response_class=HTMLResponse)
async def debug_search(keyword: str = "") -> str:
    catalog = Catalog()
    cache = Cache()
    result = await catalog.search(keyword)

    items = result.get("items", [])
    debug = result.get("debug", {})

    rows = ""
    for item in items:
        book_url = f"/debug/book/{item['bookId']}"
        state = cache.get_source_runtime_state(item['sourceId']) or {}
        proxy_badge = _proxy_badge(state.get('proxyStatus', 'unknown'))
        rows += f"""<tr>
<td><a href="{book_url}">{item['name']}</a></td>
<td>{item['author']}</td>
<td>{item['sourceName']} {proxy_badge}</td>
<td>{item['kind']}</td>
<td>{item['lastChapter']}</td>
<td>{item['score']}</td>
</tr>"""

    error_rows = ""
    for err in debug.get("errors", []):
        proxy_tag = '<span class="tag tag-proxy">proxy</span>' if err.get('proxyUsed') else '<span class="tag tag-direct">direct</span>'
        error_rows += f"""<tr>
<td>{err.get('sourceId', '')}</td>
<td>{err.get('stage', '')}</td>
<td>{proxy_tag}</td>
<td class="error">{err.get('error', '')}</td>
</tr>"""

    content = f"""
<div class="card">
<h1>搜索结果: {keyword}</h1>
<form action="/debug/search" method="get">
<input type="text" name="keyword" value="{keyword}" required>
<button type="submit">搜索</button>
</form>
</div>
<div class="card">
<p>共 {len(items)} 条结果 | 耗时 {debug.get('elapsedMs', 0)}ms | 成功 {debug.get('successCount', 0)} | 失败 {debug.get('errorCount', 0)}</p>
<table>
<tr><th>书名</th><th>作者</th><th>来源</th><th>分类</th><th>最新章节</th><th>评分</th></tr>
{rows}
</table>
</div>
<div class="card">
<h2>错误详情</h2>
<table>
<tr><th>来源ID</th><th>阶段</th><th>代理</th><th>错误</th></tr>
{error_rows}
</table>
</div>
<div class="card">
<div class="debug">{str(debug)}</div>
</div>
"""
    return HTML_TEMPLATE.replace("{content}", content)


@router.get("/debug/book/{book_id}", response_class=HTMLResponse)
async def debug_book(book_id: str) -> str:
    catalog = Catalog()
    cache = Cache()
    result = await catalog.book_detail(book_id)
    data = result.get("data")

    if not data:
        content = f'<div class="card"><h1>书籍详情</h1><p class="error">无法获取详情</p><pre>{result}</pre></div>'
        return HTML_TEMPLATE.replace("{content}", content)

    state = cache.get_source_runtime_state(data.get('sourceId', '')) or {}
    proxy_badge = _proxy_badge(state.get('proxyStatus', 'unknown'))

    toc_url = f"/debug/book/{book_id}/toc"
    content = f"""
<div class="card">
<h1>{data['name']}</h1>
<p><strong>作者:</strong> {data['author']}</p>
<p><strong>分类:</strong> {data['kind']}</p>
<p><strong>最新章节:</strong> {data['lastChapter']}</p>
<p><strong>来源:</strong> {data['sourceName']} {proxy_badge}</p>
<p><strong>代理状态:</strong> {state.get('proxyStatus', 'unknown')} (模式: {state.get('proxyMode', 'auto')})</p>
<p><a href="{toc_url}">查看目录</a></p>
</div>
<div class="card">
<h2>简介</h2>
<p>{data['intro']}</p>
</div>
<div class="card">
<img src="{data['coverUrl']}" alt="cover" style="max-width:200px;">
</div>
"""
    return HTML_TEMPLATE.replace("{content}", content)


@router.get("/debug/book/{book_id}/toc", response_class=HTMLResponse)
async def debug_toc(book_id: str) -> str:
    catalog = Catalog()
    result = await catalog.toc(book_id)
    chapters = result.get("chapters", [])

    rows = ""
    for ch in chapters:
        chapter_url = f"/debug/chapter/{ch['chapterId']}"
        rows += f"""<tr>
<td><a href="{chapter_url}">{ch['title']}</a></td>
<td>{ch['updateTime']}</td>
</tr>"""

    content = f"""
<div class="card">
<h1>目录</h1>
<p>共 {len(chapters)} 章</p>
</div>
<div class="card">
<table>
<tr><th>章节</th><th>更新时间</th></tr>
{rows}
</table>
</div>
"""
    return HTML_TEMPLATE.replace("{content}", content)


@router.get("/debug/chapter/{chapter_id}", response_class=HTMLResponse)
async def debug_chapter(chapter_id: str) -> str:
    catalog = Catalog()
    result = await catalog.chapter(chapter_id)

    content = f"""
<div class="card">
<h1>{result.get('title', '章节')}</h1>
</div>
<div class="card">
<pre>{result.get('content', '')}</pre>
</div>
<div class="card">
<div class="debug">{result.get('debug', {})}</div>
</div>
"""
    return HTML_TEMPLATE.replace("{content}", content)


@router.get("/debug/sources", response_class=HTMLResponse)
async def debug_sources() -> str:
    pool = SourcePool()
    cache = Cache()
    config = pool.get_config()
    sources = config.get("sources", [])

    rows = ""
    for src in sources:
        sid = src["id"]
        state = cache.get_source_runtime_state(sid) or {}
        proxy_badge = _proxy_badge(state.get('proxyStatus', 'unknown'))
        enabled_tag = '<span class="tag tag-direct">启用</span>' if src.get('enabled') else '<span class="tag tag-failed">禁用</span>'
        rows += f"""<tr>
<td>{sid}</td>
<td>{enabled_tag}</td>
<td>{src.get('proxy_mode', 'auto')}</td>
<td>{proxy_badge}</td>
<td>{src.get('notes', '')}</td>
<td>{state.get('lastDirectError', '')}</td>
<td>{state.get('lastProxyError', '')}</td>
</tr>"""

    content = f"""
<div class="card">
<h1>书源状态</h1>
<p>共 {len(sources)} 个候选源</p>
</div>
<div class="card">
<table>
<tr><th>ID</th><th>状态</th><th>代理模式</th><th>代理状态</th><th>备注</th><th>最后直连错误</th><th>最后代理错误</th></tr>
{rows}
</table>
</div>
"""
    return HTML_TEMPLATE.replace("{content}", content)
