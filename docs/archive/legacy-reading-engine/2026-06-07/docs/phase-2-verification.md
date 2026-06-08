# Phase 2 Verification Report

## 启动步骤

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8765
```

或双击 `start.bat`。

## 依赖变更

新增：
- `httpx>=0.27.0`
- `lxml>=5.0.0`
- `cssselect>=1.2.0`
- `beautifulsoup4>=4.12.0`

## 20 个候选源配置

| ID | 路径 | 状态 | 优先级 | proxy_mode | 预检结果 |
|----|------|------|--------|------------|----------|
| biquge365-net | data/sources/raw/by-site/legado/biquge365.net.json | 禁用 | 100 | auto | 反爬虫 alert |
| bbiquge8-net | data/sources/raw/by-site/legado/bbiquge8.net.json | 禁用 | 95 | auto | Connect timeout |
| 00xs-net | data/sources/raw/by-site/legado/00xs.net.json | 禁用 | 90 | auto | Connect timeout |
| bbiquge-cc | data/sources/raw/by-site/legado/bbiquge.cc.json | 禁用 | 85 | auto | Connect timeout |
| bbiquge-com | data/sources/raw/by-site/legado/bbiquge.com.json | 禁用 | 80 | auto | Connect timeout |
| bbiquge | data/sources/raw/by-site/legado/bbiquge.json | 禁用 | 75 | auto | Connect timeout |
| **biquges123-com** | data/sources/raw/by-site/legado/biquges123.com.json | **启用** | 70 | auto | **工作正常** |
| xiybook-com | data/sources/raw/by-site/legado/xiybook.com.json | 禁用 | 65 | auto | Connect error |
| 23dushu-net | data/sources/raw/by-site/legado/23dushu.net.json | 禁用 | 60 | auto | Connect timeout |
| siluwu-com | data/sources/raw/by-site/legado/siluwu.com.json | 禁用 | 55 | auto | `!0` 排除语法不支持 |
| m-siluke-cc | data/sources/raw/by-site/legado/m.siluke.cc.json | 禁用 | 50 | auto | Connect timeout |
| m-kanshuba-org | data/sources/raw/by-site/legado/m.kanshuba.org.json | 禁用 | 45 | auto | Search 404 |
| m-iquanben-net | data/sources/raw/by-site/legado/m.iquanben.net.json | 禁用 | 40 | auto | Connect error |
| hetus1-com | data/sources/raw/by-site/legado/hetus1.com.json | 禁用 | 35 | auto | POST 搜索无结果 |
| ibiquta-info | data/sources/raw/by-site/legado/ibiquta.info.json | 禁用 | 30 | auto | Search 403 |
| qixinge-com | data/sources/raw/by-site/legado/qixinge.com.json | 禁用 | 25 | auto | Search 404 |
| drxsw-com | data/sources/raw/by-site/legado/drxsw.com.json | 禁用 | 20 | auto | Connect error |
| ttd3-cn | data/sources/raw/by-site/legado/ttd3.cn.json | 禁用 | 15 | auto | Connect timeout |
| lwxstxt-com | data/sources/raw/by-site/legado/lwxstxt.com.json | 禁用 | 10 | auto | Connect error |
| m-63shu-com | data/sources/raw/by-site/legado/m.63shu.com.json | 禁用 | 5 | auto | 403 Forbidden |

## 测试运行命令与结果

```powershell
python -m pytest tests -v
```

结果：**30/30 通过**。

```
tests/test_catalog_api.py::test_search_returns_real_shape PASSED
tests/test_catalog_api.py::test_book_detail_invalid_id PASSED
tests/test_db.py::test_initialize_database PASSED
tests/test_db.py::test_initialize_database_idempotent PASSED
tests/test_extractor.py::test_extract_field_class_text PASSED
tests/test_extractor.py::test_extract_field_id_text PASSED
tests/test_extractor.py::test_extract_field_href PASSED
tests/test_extractor.py::test_extract_list PASSED
tests/test_extractor.py::test_extract_field_with_replace_regex PASSED
tests/test_health.py::test_health PASSED
tests/test_health.py::test_api_info PASSED
tests/test_legado_api.py::test_source_uses_request_host PASSED
tests/test_legado_api.py::test_routes_return_implemented PASSED
tests/test_legado_executor.py::test_book_id_roundtrip PASSED
tests/test_legado_executor.py::test_chapter_id_roundtrip PASSED
tests/test_phase2_sources.py::test_source_pool_loads_20_sources PASSED
tests/test_phase2_sources.py::test_enabled_sources_have_required_fields PASSED
tests/test_phase2_sources.py::test_all_source_files_exist PASSED
tests/test_proxy.py::test_decide_proxy_mode PASSED
tests/test_proxy.py::test_decide_proxy_mode_when_disabled PASSED
tests/test_proxy.py::test_should_retry_with_proxy_status_code PASSED
tests/test_proxy.py::test_should_retry_with_proxy_keyword PASSED
tests/test_proxy.py::test_fetcher_never_mode_no_proxy PASSED
tests/test_proxy.py::test_fetcher_always_mode_uses_proxy PASSED
tests/test_proxy.py::test_fetcher_auto_fallback_to_proxy PASSED
tests/test_proxy.py::test_catalog_records_proxy_status PASSED
tests/test_source_generator.py::test_generate_aggregate_source_shape PASSED
tests/test_source_generator.py::test_write_aggregate_source PASSED
tests/test_source_generator.py::test_source_calls_local_endpoints PASSED
tests/test_source_generator.py::test_source_accepts_lan_base_url PASSED
```

## API Smoke Test

搜索：
```
GET /api/legado/search?keyword=凡人修仙传&page=1
→ implemented: true, items: 10, debug: {sourceCount: 1, successCount: 1, errorCount: 0, elapsedMs: ~1775}
```

详情：
```
GET /api/legado/book/{bookId}
→ implemented: true, data: {name: "凡人修仙传", author: "作者：忘语", ...}
```

目录：
```
GET /api/legado/book/{bookId}/toc
→ implemented: true, chapters: 2467 章
```

正文：
```
GET /api/legado/chapter/{chapterId}
→ implemented: true, title: "第一章 山边小村", content: "二愣子睁大着双眼..." (2922 字符)
```

## Web Debug UI 验证

- `GET /debug` — 搜索输入页 ✅
- `GET /debug/search?keyword=凡人修仙传` — 搜索结果表格，含来源、耗时、成功/失败数、代理状态徽章 ✅
- `GET /debug/sources` — 20 个候选源状态表，含启用/禁用标签、代理模式、代理状态、备注、最后错误 ✅
- `GET /debug/book/{bookId}` — 书籍详情，含简介、封面、目录链接、代理状态 ✅
- `GET /debug/book/{bookId}/toc` — 目录列表（2467 章）✅
- `GET /debug/chapter/{chapterId}` — 章节正文 ✅

## 聚合书源验证

```powershell
python docs/skills/book-source-craft/scripts/inspect_legado_source.py generated/legadohub-source.json
```

输出：
```
path: generated\legadohub-source.json
top_type: list
source_count: 1

[0]
name: LegadoHub 聚合(0.1.0)
url: LegadoHub
group: 聚合,LegadoHub
type: 0
searchUrl: str: http://127.0.0.1:8765/api/legado/search?keyword={{key}}&page={{page}}
ruleSearch: dict(10): bookList, name, author, coverUrl, intro, kind, lastChapter, wordCount, bookUrl, checkKeyWord
exploreUrl: missing
ruleExplore: missing
ruleBookInfo: dict(9): init, name, author, coverUrl, intro, kind, lastChapter, wordCount, tocUrl
ruleToc: dict(4): chapterList, chapterName, chapterUrl, updateTime
ruleContent: dict(2): content, title
jsLib: str: function baseUrl() { return 'http://127.0.0.1:8765'; }
```

## Proxy 配置与行为

全局代理配置（`config/phase2_sources.json`）：
```json
{
  "enabled": false,
  "url": "",
  "retry_on_failure": true,
  "failure_status_codes": [403, 429, 451, 502, 503, 504],
  "failure_error_keywords": ["timeout", "connection", "reset", "forbidden", "captcha", "blocked"]
}
```

**代理 URL 未配置**，验证使用模拟 fetcher 完成。所有 20 个源的 `proxy_mode` 均为 `auto`。

### 代理行为测试结果

| 测试 | 结果 |
|------|------|
| `proxy_mode: "never"` — 不使用代理，仅直连一次 | ✅ 通过 |
| `proxy_mode: "always"` — 跳过直连，直接使用代理 | ✅ 通过 |
| `proxy_mode: "auto"` — 直连 403 失败后自动代理重试并成功 | ✅ 通过 |
| 代理成功后 `source_runtime_state.proxy_status = "proxy_succeeded"` | ✅ 通过 |
| `proxy_mode: "always"` 时状态记录为 `"forced_proxy"` | ✅ 通过 |
| 直连成功时状态记录为 `"direct_ok"` | ✅ 通过 |

### 运行时代理状态示例

```
source_id            proxy_mode  proxy_status    last_success_via_proxy
biquges123-com       auto        direct_ok       False
```

## Unsupported Syntax 清单

Phase 2 解析器未实现以下语法，遇到时返回结构化错误或在预检中标记为禁用：

| 语法 | 影响源数 | 说明 |
|------|---------|------|
| `<js>...</js>` | 1 | `bbiquge8-net` content 规则使用 `<js>` 块 |
| `@js:` | 1 | `00xs-net` coverUrl 使用 `@js` 语法 |
| `||` fallback | 2 | 实现为仅取第一个分支（如 `m-siluke-cc` chapterList） |
| `!N` / `!0` 排除 | 2 | `siluwu-com` bookList 使用 `!0` 排除语法，不支持；`biquge365-net` 有类似排除逻辑 |
| `exploreUrl` / `ruleExplore` | — | Phase 2 不实现发现页 |
| `loginUrl` / `loginUi` | 0 | 候选池无登录要求源 |

## 已知限制与阶段 3 建议

1. **源池存活率低**：20 个候选源中仅 1 个（`biquges123-com`）能稳定完成搜索→详情→目录→正文闭环。其余源大多因网络不可达（Connect timeout/403/404）被禁用。阶段 3 需要：
   - 自动健康检测与评分系统
   - 代理配置后可重新激活被 403 拦截的源
   - 自动发现新源或从社区源库补充

2. **解析器语法覆盖有限**：仅支持常见 CSS selector 链、text/href/src/html/title 提取、replaceRegex、list 提取。阶段 3 扩展：
   - `||` fallback 的完整分支评估
   - `!N` 排除语法
   - `@js` 沙箱执行（轻量级 JS 引擎或外部进程）
   - XPath 支持

3. **Web UI 仅为 debug 表面**：无完整管理控制台、无源编辑/导入/导出功能。阶段 3/6 扩展为管理后台。

4. **内容清理简单**：仅支持 `replaceRegex`，阶段 3/5 加入广告过滤、AI 校对。

5. **缓存 TTL 硬编码**：搜索 10 分钟、详情 1 天、目录 1 小时、正文 7 天。阶段 3 可配置化。

6. **阅读端验证受限**：当前环境无法直接运行 Android 阅读 APP，但聚合书源结构和端点形状已对齐阅读规则规范，可在局域网内导入验证。实际验证结果：
   - 聚合源 JSON 已生成并可通过 `http://<lan-ip>:8765/api/legado/source` 导入
   - `bookUrl`、`tocUrl`、`chapterUrl` 均指向本地 API 代理端点
   - 阅读 APP 导入后应能正常搜索、获取目录和正文
