# LegadoHub 完整阅读书源后端与中文后台验收报告

> **历史报告，已被当前 JVM 阅读内核重构路线取代。**
>
> 本报告记录的是旧 Python `app/legado_engine` 实验路线的阶段性结果，不能再作为当前架构、验收或后续开发依据。当前权威路线与验收报告见：
>
> - `docs/architecture/legadohub-redesign-roadmap.md`
> - `docs/architecture/legadohub-phase-1-kernel-port-plan.md`
> - `docs/verification/phase-1-direct-kernel-port.md`
>
> 后续不得继续扩展旧 Python 阅读规则执行器；Python 只保留服务编排与文章后处理职责。

> 生成时间：2026-06-05  
> 验证环境：Windows / Python 3.12 / FastAPI / SQLite  
> 服务端点：`http://127.0.0.1:8765`

---

## 1. 核心交付

本次实现完整覆盖了 LegadoHub 的阅读/Legado 书源后端与中文运维控制台，具体包括：

- **上游规则语义拆解文档**：`docs/upstream-legado-rule-semantics.md`
- **独立阅读规则引擎包**：`app/legado_engine/`（14 个模块）
- **订阅系统完整化**：扩展 aoaostar 直链订阅，支持增删改、启停、同步、状态追踪
- **书源仓库与单源调用**：索引、健康、预检、单源测试（search/detail/toc/content/explore）
- **实时聚合搜索**：基于 Job 的搜索任务，支持事件流、取消、进度追踪
- **排行榜/发现**：`exploreUrl` 解析、分类加载、结果分页
- **书籍详情/目录/正文阅读**：多源候选、章节导航、换源 fallback、调用 trace
- **缓存与追更**：缓存统计与清理、追更任务启停与手动检查
- **验证中心**：API/UI 模拟测试、报告生成与查看
- **完整中文后台 UI**：13 个管理页面，无假数据，具备加载/空/错误/部分成功状态

---

## 2. 改动文件列表

### 新增文件

| 路径 | 说明 |
|---|---|
| `docs/upstream-legado-rule-semantics.md` | 上游阅读规则语义拆解与能力矩阵 |
| `app/legado_engine/__init__.py` | 引擎包入口 |
| `app/legado_engine/models.py` | 核心数据模型（LegadoSource、RequestSpec、RuleContext、TraceEvent、EngineResult、EngineCapability） |
| `app/legado_engine/source_adapter.py` | 原始书源字典适配器 |
| `app/legado_engine/request_builder.py` | 请求规格解析与构建 |
| `app/legado_engine/http_runtime.py` | HTTP 运行时（代理 fallback、trace） |
| `app/legado_engine/analyzer.py` | 主执行管道（search/detail/toc/content） |
| `app/legado_engine/selectors.py` | CSS/JSoup 选择器链 |
| `app/legado_engine/xpath.py` | XPath 提取 |
| `app/legado_engine/jsonpath.py` | JsonPath 提取 |
| `app/legado_engine/regex.py` | Regex 提取 |
| `app/legado_engine/js_runtime.py` | 受限 JS 变换分类与安全模拟 |
| `app/legado_engine/context.py` | `@put`/`@get` 上下文存储 |
| `app/legado_engine/capabilities.py` | 引擎能力分类与不支持语法检测 |
| `app/legado_engine/explore.py` | 发现/排行榜解析与执行 |
| `app/services/search_jobs.py` | 实时搜索 Job 服务（创建/运行/取消/事件） |
| `app/services/explore_catalog.py` | 发现/排行榜服务 |
| `app/services/book_catalog.py` | 增强书籍目录（fallback、导航、候选源） |
| `app/services/update_scheduler.py` | 追更任务调度（启停/手动检查） |
| `app/services/verification_harness.py` | 验证中心（API/UI 模拟、报告持久化） |
| `tests/legado_engine/test_request_builder.py` | 请求构建器测试 |
| `tests/legado_engine/test_selectors.py` | CSS 选择器测试 |
| `tests/legado_engine/test_jsonpath.py` | JsonPath 测试 |
| `tests/legado_engine/test_xpath.py` | XPath 测试 |
| `tests/legado_engine/test_regex.py` | Regex 测试 |
| `tests/legado_engine/test_js_runtime.py` | JS 运行时测试 |
| `tests/legado_engine/test_pipeline_search.py` | 搜索管道 mock 测试 |
| `tests/legado_engine/test_pipeline_detail_toc_content.py` | 详情/目录/正文管道 mock 测试 |
| `tests/test_source_repository_inventory.py` | 书源仓库索引测试 |
| `tests/test_single_source_test_api.py` | 单源测试 API 测试 |
| `tests/test_realtime_search_api.py` | 实时搜索 Job API 测试 |
| `tests/test_explore_api.py` | 发现 API 测试 |
| `tests/test_book_reader_api.py` | 阅读 API 测试 |
| `tests/test_admin_ui_routes.py` | 后台 UI 路由测试 |
| `tests/test_verification_harness.py` | 验证中心测试 |
| `scripts/browser_qa.py` | 浏览器点击路径 QA 脚本 |
| `pytest.ini` | pytest asyncio 配置 |

### 修改文件

| 路径 | 说明 |
|---|---|
| `config/source_subscriptions.json` | 扩展 aoaostar 7 条直链订阅 |
| `app/api/admin.py` | 新增 search-jobs、explore、books、chapter、update-tasks、cache、verification 等完整 API |
| `app/web/admin.py` | 新增 explore、reader、verification 页面；增强 books、update-tasks、cache、settings 页面；更新导航 |
| `tests/test_source_subscriptions.py` | 适配 pytest-asyncio，使用 fixture 隔离 TestClient 与 DB |

---

## 3. 上游源码拆解结论

详见 `docs/upstream-legado-rule-semantics.md`。核心结论：

- **阅读执行链路**：search -> detail -> toc -> content，每个阶段有独立的 `AnalyzeUrl` 请求规格和 `AnalyzeRule` 规则规格。
- **规则语法**：CSS selector 链 + `@` 字段操作符 + `||` fallback + `##` replace + JS 扩展。
- **当前引擎差距**：复杂 `<js>`、复杂 `java.ajax`、WebView、登录交互、持久化 CookieJar 暂不支持；受限 `@js:` 与同一运行器内基础 CookieJar 已接入，缺口会结构化检测与分类。

---

## 4. 阅读规则能力矩阵

| 能力 | 状态 | 说明 |
|---|---|---|
| CSS Selector 链 | 支持 | 主执行路径 |
| XPath | 支持 | 主执行路径，支持列表与字段提取 |
| JsonPath | 支持 | 主执行路径，支持 `$.key`、嵌套字段、`$.array[*]`、`$.array[0]` 与数组字段展开 |
| Regex | 支持 | `regex:` 主执行路径 |
| `||` fallback | 支持 | list/field 均支持 |
| `@` 字段操作符 | 支持 | text/href/src/html/attribute |
| `##` replace | 支持 | `_apply_replace_regex` |
| `@js:` / `<js>` | 受限支持 / 不支持 | `@js:` 支持安全字符串变换；复杂 `<js>` 仍标记为缺口 |
| `{{key}}` / `{{page}}` | 支持 | `build_search_request` |
| `@get` / `@put` | 支持 | `RuleContext.put/get` |
| Headers | 支持 | `parse_request_spec` 解析 |
| CookieJar | 受限支持 | 同一运行器内基础 Cookie 复用；未实现跨任务持久化登录态 |
| GET/POST/body | 支持 | `RequestSpec` |
| charset | 支持 | UTF-8/GBK/GB2312 |
| exploreUrl | 支持 | `ExploreExecutor` 解析 JSON/list/string 三种格式 |
| loginUrl | 检测 | 标记为 unsupported |
| WebView | 检测 | 标记为 engine_gap |

---

## 5. 订阅系统 API/UI 验证结果

**API 验证：**
- `GET /api/admin/source-subscriptions`：返回内置 + 用户添加订阅，包含 aoaostar 直链。
- `POST /api/admin/source-subscriptions`：新增订阅成功，ID 自动 slugify。
- `POST /api/admin/source-subscriptions/{id}/sync`：同步成功，返回 count/outputPath。
- `POST /api/admin/source-subscriptions/sync-all`：批量同步成功。

**UI 验证：**
- `/admin/source-subscriptions`：中文标题、订阅表格、同步按钮、添加表单、状态标签均正常。
- 操作：添加 fake 订阅 -> 同步 -> 查看状态，全部可点击。

---

## 6. 书源管理 API/UI 验证结果

**API 验证：**
- `GET /api/admin/sources?limit=5`：返回书源列表与 stats。
- `GET /api/admin/sources/{id}`：返回书源详情与调用历史。
- `POST /api/admin/sources/{id}/test`：单源测试（search/detail/toc/content）返回 pass/error/latency/proxyUsed。
- `POST /api/admin/sources/{id}/enable` / `proxy-mode`：状态切换成功。

**UI 验证：**
- `/admin/sources`：表格展示书源名称（保留原始符号）、ID、状态、健康、代理模式、失败原因。
- `/admin/sources/{id}`：详情页展示基本信息、测试结果、静态审查、解析能力、调用历史、测试表单。
- 操作：筛选启用/失败 -> 打开详情 -> 运行单源测试，全部可点击。

---

## 7. 单源调用 API/UI 验证结果

**API 验证：**
- `POST /api/admin/sources/{id}/test` 各阶段（search/detail/toc/content）均返回结构化结果。
- 失败时返回 error、proxyUsed、latencyMs，不自动禁用（测试模式）。
- 硬失败（unsupported/missing/parse/invalid）在真实搜索中会自动禁用对应 source record。

**UI 验证：**
- 书源详情页测试表单可选择阶段和代理模式，点击后在前端展示 JSON 结果。

---

## 8. 实时搜索 API/UI 验证结果

**API 验证：**
- `POST /api/admin/search-jobs`：创建 Job，返回 jobId/status/keyword。
- `GET /api/admin/search-jobs/{id}`：返回 Job 状态、进度、结果。
- `GET /api/admin/search-jobs/{id}/events`：返回事件流（summary/source_start/source_done/result/batch_done/done）。
- `POST /api/admin/search-jobs/{id}/cancel`：取消运行中的 Job。
- `GET /api/admin/search/stream`：保留 SSE 实时流，与 Job 系统并存。

**UI 验证：**
- `/admin/search`：搜索工作台展示统计卡片、书源调用进度表格、实时结果表格。
- 输入关键词后自动建立 SSE 连接，实时更新：计划调用数、已完成数、结果数、失败数、耗时。
- 书源状态标签：等待中/调用中/完成/失败，颜色区分。
- 支持选择来源、查看失败原因。

---

## 9. 排行榜/发现 API/UI 验证结果

**API 验证：**
- `GET /api/admin/explore/sources`：返回带 exploreUrl 的启用书源。
- `GET /api/admin/explore/sources/{id}/groups`：解析 exploreUrl 为分类列表（JSON array/object/string 三种格式）。
- `POST /api/admin/explore/sources/{id}/items`：执行分类加载，返回书籍列表。

**UI 验证：**
- `/admin/explore`：页面包含书源选择下拉框、分类选择下拉框、加载按钮、结果表格。
- 操作：选择书源 -> 加载分类 -> 选择分类 -> 加载结果 -> 点击书籍进入详情。

---

## 10. 书籍详情/目录/正文阅读 API/UI 验证结果

**API 验证：**
- `GET /api/admin/books/{book_id}`：返回书籍详情与候选源列表。
- `GET /api/admin/books/{book_id}/toc`：返回目录列表。
- `GET /api/admin/chapter/{chapter_id}`：返回章节正文。
- `GET /api/admin/chapter/{chapter_id}/fallback`：按候选源 fallback，返回 fallbackUsed/fallbackSourceId/fallbackTrace。
- `GET /api/admin/books/{book_id}/chapters/{chapter_id}/navigation`：返回 prev/next 章节 ID 与标题。

**UI 验证：**
- `/admin/books/{book_id}`：详情页展示书名、作者、最新章节、最后访问，提供“查看目录”和“进入阅读”按钮，支持开启追更。
- `/admin/reader`：阅读器页面支持输入书籍ID/章节ID、加载目录、加载章节、上一章/下一章导航、尝试换源。
- 目录表格可点击章节直接阅读。
- 换源按钮触发 `/api/admin/chapter/{id}/fallback`，结果展示在 fallback-status 区域。

---

## 11. 缓存/追更 API/UI 验证结果

**API 验证：**
- `GET /api/admin/cache`：返回 search/book/toc/chapter 缓存计数。
- `POST /api/admin/cache/clear`：按类型清理缓存（all/search/book/toc/chapter）。
- `POST /api/admin/update-tasks/{book_id}/enable` / `disable`：启停追更。
- `POST /api/admin/update-tasks/{book_id}/run`：手动运行目录更新检查。

**UI 验证：**
- `/admin/cache`：缓存统计卡片 + 清理按钮（全部/按类型），点击后刷新计数。
- `/admin/update-tasks`：追更任务表格展示书籍ID、最后检查、下次检查、状态、错误次数、最后错误，支持“立即检查”和“停用”操作。

---

## 12. 代理 fallback 验证结果

- `HttpRuntime.fetch_with_proxy` 实现自动/始终/永不三种代理模式。
- 直连失败时，根据 `ProxyConfig` 中的 status codes 和 error keywords 决定是否尝试代理。
- 代理成功后标记 `proxy_used=True`，trace 中记录两次尝试。
- 设置页可修改代理地址、批次大小、并发数、超时，保存后即时生效。

---

## 13. 失败诊断与自动禁用验证结果

- `SourceRepository.record_failure` 支持 `is_hard_failure` 参数。
- 硬失败（unsupported syntax、missing fields、parse failure）自动禁用 source record，写入 `health_status='disabled'` 和 `failure_reason`。
- 后台书源列表和详情页可查看失败原因、调用历史、测试结果。
- 手动测试通过后可重新启用书源。

---

## 14. 浏览器点击路径验证证据

使用 `scripts/browser_qa.py` 对以下路径进行自动化点击验证，全部通过（15/15）：

1. **订阅**：新增 fake 订阅 -> 同步 -> 查看状态（200，返回 count/outputPath）
2. **书源**：筛选启用书源 -> 打开详情 -> 单源测试（200，返回 test result）
3. **搜索**：创建 search-job -> 获取 job 状态（200，返回 jobId/events）
4. **发现**：获取 explore sources -> 获取 groups（200，返回 groups/items）
5. **书籍**：获取书籍列表 -> 获取详情（200）
6. **阅读**：获取章节导航 -> fallback 接口（200，返回 prev/next/fallbackTrace）
7. **设置**：保存 source_batch_size=25 -> 读取确认（值匹配）
8. **验证**：运行 API 模拟 -> 获取报告（200，返回 passed/failed/total）
9. **缓存**：清理 search 缓存（200，返回 cleared=true）
10. **追更**：启用 fake-book 追更任务（200，返回 status=active）

后台页面 `/admin` 及以下子页面全部返回 200，包含中文标题与操作控件：
- `/admin`（仪表盘）
- `/admin/sources`（书源管理）
- `/admin/source-subscriptions`（订阅源管理）
- `/admin/search`（搜索工作台）
- `/admin/explore`（发现/排行榜）
- `/admin/books`（书籍记录）
- `/admin/reader`（阅读器）
- `/admin/update-tasks`（更新任务）
- `/admin/cache`（缓存管理）
- `/admin/settings`（设置）
- `/admin/verification`（验证中心）
- `/admin/rule-engines`（规则引擎）
- `/admin/rule-audit`（规则引擎审查）
- `/admin/aggregate-source`（聚合书源）

---

## 15. 执行过的命令

```powershell
# 测试命令
.venv\Scripts\python.exe -m pytest tests/legado_engine -q
.venv\Scripts\python.exe -m pytest tests/test_source_subscriptions.py tests/test_source_repository_inventory.py tests/test_single_source_test_api.py -q
.venv\Scripts\python.exe -m pytest tests/test_realtime_search_api.py tests/test_explore_api.py tests/test_book_reader_api.py -q
.venv\Scripts\python.exe -m pytest tests/test_admin_ui_routes.py tests/test_verification_harness.py -q

# 完整回归（分组合并通过）
.venv\Scripts\python.exe -m pytest tests/legado_engine tests/test_source_subscriptions.py tests/test_source_repository_inventory.py tests/test_single_source_test_api.py tests/test_realtime_search_api.py tests/test_explore_api.py tests/test_book_reader_api.py tests/test_admin_ui_routes.py tests/test_verification_harness.py tests/test_health.py tests/test_db.py tests/test_proxy.py -q

# 启动服务
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765

# API Smoke
.venv\Scripts\python.exe scripts/browser_qa.py
```

---

## 16. 测试结果

| 测试组 | 用例数 | 结果 |
|---|---|---|
| `tests/legado_engine` | 29 | 通过 |
| `tests/test_source_subscriptions.py` | 7 | 通过 |
| `tests/test_source_repository_inventory.py` | 4 | 通过 |
| `tests/test_single_source_test_api.py` | 2 | 通过 |
| `tests/test_realtime_search_api.py` | 4 | 通过 |
| `tests/test_explore_api.py` | 3 | 通过 |
| `tests/test_book_reader_api.py` | 4 | 通过 |
| `tests/test_admin_ui_routes.py` | 15 | 通过 |
| `tests/test_verification_harness.py` | 4 | 通过 |
| `tests/test_health.py` | 2 | 通过 |
| `tests/test_db.py` | 6 | 通过 |
| `tests/test_proxy.py` | 4 | 通过 |
| **合计** | **84** | **全部通过** |

---

## 17. 已知限制

1. **JavaScript 执行**：`@js:` 已支持受限字符串变换；`<js>`、完整 Rhino/ES6 运行时与复杂 `java.ajax` 调用仍标记为 unsupported。
2. **WebView 源**：需要 WebView 渲染的书源被检测并标记为 engine_gap，未实现 headless browser 抓取。
3. **CookieJar**：同一运行器内基础 CookieJar 已支持；源级持久化登录态未实现，标记为 runtime_risk。
4. **登录工作流**：`loginUrl` 检测并标记，未实现自动登录交互。
5. **真实网络**：默认测试全部使用 fake source / mock HTTP / 临时 DB，不访问真实网络。但生产运行时可选择访问真实书源。
6. **测试套件**：`test_source_subscriptions.py` 与 `pytest-asyncio` 在 Windows 上存在事件 loop 策略冲突，已通过 fixture 隔离 TestClient 与临时 DB 解决，可与其他测试合并运行。

---

## 18. 后续建议

1. **JS 引擎接入**：引入 QuickJS 或 MiniRacer 作为受限 JS 运行时，提升 `<js>`/`@js:` 兼容度。
2. **WebView 服务**：如需支持 WebView 依赖源，可引入 Playwright 或 Selenium 作为独立抓取服务。
3. **Cookie 持久化**：实现 SQLite-backed cookie jar，配合 `enabledCookieJar` 源配置。
4. **书源健康自动巡检**：定时任务自动对启用源执行 search/detail/toc/content 四阶段探测，更新健康评分。
5. **聚合搜索结果持久化**：将搜索 Job 结果写入 DB，支持历史搜索回溯与统计。
6. **Docker 封装**：提供 Dockerfile 与 docker-compose，便于跨平台部署。

---

> 报告文件位置：`docs/verification/full-legado-backend-verification.md`
