# Kimi 执行交接：LegadoHub 完整阅读书源后端与后台

## 任务目标

你要完整实现 LegadoHub 的阅读/Legado 书源后端与中文后台。不要按最小实现处理，也不要只修单个页面。目标是把 LegadoHub 做成一个可长期维护的本地阅读书源聚合后端：

- 项目内订阅连接管理与同步
- 全量书源仓库索引与治理
- 独立阅读/Legado 规则引擎
- 单书源搜索/详情/目录/正文/发现调用
- 聚合实时搜索与进度显示
- 排行榜/发现页
- 书籍详情、目录、章节阅读后台
- 缓存、追更、失败诊断、代理状态
- 完整中文 Web 后台
- 每项功能都要有 API 模拟测试和 UI 模拟测试

Codex 会负责审查和验收，你负责实现。

## 当前仓库

项目路径：

```powershell
C:\Home\Workspace\UGit\legado-hub
```

不要提交或 push，除非用户另外明确要求。

## 已拉取的上游参考

已经在本地拉取：

```powershell
data\upstreams\aoaostar-legado
data\upstreams\luoyacheng-legado
```

如果目录不存在或不完整，使用以下命令恢复：

```powershell
cd C:\Home\Workspace\UGit\legado-hub

if (!(Test-Path data\upstreams)) {
  New-Item -ItemType Directory -Path data\upstreams | Out-Null
}

if (!(Test-Path data\upstreams\aoaostar-legado\.git)) {
  git clone https://github.com/aoaostar/legado.git data\upstreams\aoaostar-legado
} else {
  git -C data\upstreams\aoaostar-legado fetch --all --prune
}

if (!(Test-Path data\upstreams\luoyacheng-legado\.git)) {
  git clone --depth 1 https://github.com/Luoyacheng/legado.git data\upstreams\luoyacheng-legado
} else {
  git -C data\upstreams\luoyacheng-legado fetch --all --prune
}
```

说明：

- `aoaostar/legado` 是书源、订阅源、净化规则、排版、主题、TTS 的发布仓库，不是阅读 APP 规则引擎源码。
- 阅读 APP 的规则执行语义请参考 `data/upstreams/luoyacheng-legado`。

## 必读文档

先读这些文件，不要跳过：

```powershell
Get-Content docs\implementation-plan-full-legado-backend.md
Get-Content docs\project-plan.md
Get-Content PRODUCT.md
Get-Content docs\implementation-plan-phase-3.md
Get-Content config\source_subscriptions.json
Get-Content config\source_pool.json
Get-Content config\rule_engines.json
```

重点执行来源：

```powershell
docs\implementation-plan-full-legado-backend.md
```

## 必读上游源码入口

先定位阅读规则执行链路：

```powershell
rg "class Analyze|object Analyze|fun analyze|AnalyzeRule|AnalyzeUrl|BookSource|ruleSearch|ruleToc|ruleContent|exploreUrl|searchUrl|loginUrl|header" data\upstreams\luoyacheng-legado\app data\upstreams\luoyacheng-legado\modules -n --glob *.kt --glob *.java
```

重点文件：

```powershell
Get-Content data\upstreams\luoyacheng-legado\app\src\main\java\io\legado\app\model\analyzeRule\AnalyzeRule.kt
Get-Content data\upstreams\luoyacheng-legado\app\src\main\java\io\legado\app\model\analyzeRule\AnalyzeUrl.kt
Get-Content data\upstreams\luoyacheng-legado\app\src\main\java\io\legado\app\model\analyzeRule\AnalyzeByJSoup.kt
Get-Content data\upstreams\luoyacheng-legado\app\src\main\java\io\legado\app\model\analyzeRule\AnalyzeByXPath.kt
Get-Content data\upstreams\luoyacheng-legado\app\src\main\java\io\legado\app\model\analyzeRule\AnalyzeByJSonPath.kt
Get-Content data\upstreams\luoyacheng-legado\app\src\main\java\io\legado\app\model\analyzeRule\AnalyzeByRegex.kt
Get-Content data\upstreams\luoyacheng-legado\app\src\main\java\io\legado\app\model\webBook\WebBook.kt
Get-Content data\upstreams\luoyacheng-legado\app\src\main\java\io\legado\app\model\webBook\BookList.kt
Get-Content data\upstreams\luoyacheng-legado\app\src\main\java\io\legado\app\model\webBook\BookInfo.kt
Get-Content data\upstreams\luoyacheng-legado\app\src\main\java\io\legado\app\model\webBook\BookChapterList.kt
Get-Content data\upstreams\luoyacheng-legado\app\src\main\java\io\legado\app\model\webBook\BookContent.kt
Get-Content data\upstreams\luoyacheng-legado\app\src\main\java\io\legado\app\help\JsExtensions.kt
Get-Content data\upstreams\luoyacheng-legado\app\src\main\java\io\legado\app\data\entities\BookSource.kt
```

读取 `aoaostar/legado` 发布清单：

```powershell
Get-Content data\upstreams\aoaostar-legado\README.md
Get-Content data\upstreams\aoaostar-legado\index.html
Get-ChildItem data\upstreams\aoaostar-legado\sources
```

## 禁止事项

- 不要做最小实现。
- 不要只改一个 API 或一个页面就汇报完成。
- 不要让测试默认访问真实上游网络。
- 不要让完整回归测试触发几千个真实书源。
- 不要把 `aoaostar/legado` 当成阅读 APP 规则引擎源码。
- 不要剥离书源名里的符号；书源原始名称必须原样传递。
- 系统 UI 文案不要使用装饰性表情符号。
- 不要在没有 API 与 UI 双重模拟证据时宣称功能完成。
- 不要提交或 push。

## 设计要求

后台是中文本地运维控制台：

- 简体中文界面
- 不做 landing page
- 不做营销式 hero
- 不过度极简
- 用分割线、表格行线、分组面板、留白、对齐、状态标签体现设计感
- 不用装饰性表情符号
- 无假数据
- 每个核心页面必须有加载、空、错误、部分成功状态
- 表格需要分页、过滤、排序或至少可扩展的分页结构
- 移动/窄屏不能明显重叠

参考：

```powershell
PRODUCT.md
```

## 执行阶段

### 阶段 A：上游拆解文档

目标：先写清楚阅读规则语义，不急着重构代码。

创建：

```powershell
docs\upstream-legado-rule-semantics.md
```

必须包含：

- 阅读搜索链路
- 发现/排行榜链路
- 书籍详情链路
- 目录链路
- 正文链路
- `AnalyzeRule` 规则语法
- `AnalyzeUrl` 请求语法
- JS 扩展能力
- headers/cookie/login 行为
- 当前 LegadoHub 差距矩阵
- 立即实现/安全模拟/暂不支持的分类

### 阶段 B：建立独立阅读规则引擎包

创建：

```powershell
app\legado_engine\__init__.py
app\legado_engine\models.py
app\legado_engine\source_adapter.py
app\legado_engine\request_builder.py
app\legado_engine\http_runtime.py
app\legado_engine\analyzer.py
app\legado_engine\selectors.py
app\legado_engine\xpath.py
app\legado_engine\jsonpath.py
app\legado_engine\regex.py
app\legado_engine\js_runtime.py
app\legado_engine\context.py
app\legado_engine\capabilities.py
app\legado_engine\explore.py
```

旧的：

```powershell
app\engine\*
```

可以作为兼容 wrapper 暂留，但新功能必须走独立包。

### 阶段 C：订阅系统完整化

当前已有：

```powershell
config\source_subscriptions.json
app\services\source_subscriptions.py
```

需要扩展内置订阅，至少包含 `aoaostar/legado` 中的这些直链：

```text
https://legado.aoaostar.com/sources/b778fe6b.json
https://legado.aoaostar.com/sources/71e56d4f.json
https://legado.aoaostar.com/sources/4dc410d1.json
https://legado.aoaostar.com/sources/e3e5d620.json
https://legado.aoaostar.com/sources/e29e19ee.json
https://legado.aoaostar.com/sources/2a1f129b.json
https://legado.aoaostar.com/sources/3bb7b751.json
```

后台必须能：

- 查看订阅
- 添加订阅
- 编辑订阅
- 启停订阅
- 同步单个订阅
- 同步全部订阅
- 查看同步状态、数量、失败原因、输出文件

### 阶段 D：书源仓库与单源调用

完善：

```powershell
app\services\source_repository.py
app\services\source_health.py
```

要求：

- 每个 JSON 文件可包含单对象或多对象
- 每个对象独立 source record
- 记录 subscription id、upstream url、raw file path、source index、engine type
- 支持 source 预检
- 支持单源调用：
  - search
  - detail
  - toc
  - content
  - explore
- 调用结果必须有 trace
- 失败原因写入后台
- 硬失败只禁用对应 source record

### 阶段 E：实时聚合搜索

不要只做一次性 `/api/legado/search`。

后台搜索必须能实时显示：

- 当前批次
- 正在调用的书源
- 已完成数量
- 单源耗时
- 单源成功/失败
- 单源失败原因
- 实时返回结果
- 最终合并结果
- 候选来源
- 排名解释

建议 API：

```text
POST /api/admin/search-jobs
GET  /api/admin/search-jobs/{job_id}
GET  /api/admin/search-jobs/{job_id}/events
POST /api/admin/search-jobs/{job_id}/cancel
```

可以保留 SSE，但要有 job state，不要只是一次性 generator。

### 阶段 F：排行榜/发现

从 Legado `exploreUrl` 实现：

```text
GET /api/admin/explore/sources
GET /api/admin/explore/sources/{source_id}/groups
POST /api/admin/explore/sources/{source_id}/items
```

后台页面：

```text
/admin/explore
```

要求：

- 选择书源
- 查看发现/排行榜分类
- 加载分类结果
- 支持分页
- 点击进入书籍详情

### 阶段 G：书籍阅读后端与 UI

实现：

- 书籍详情
- 多源候选
- 目录
- 章节正文
- 上一章/下一章
- 正文缓存
- 失败 fallback
- 调用 trace

后台页面：

```text
/admin/books
/admin/books/{book_id}
/admin/reader
```

### 阶段 H：缓存、追更、验证中心

完善：

```text
/admin/cache
/admin/update-tasks
/admin/verification
```

追更要求：

- 开启/关闭追更
- 手动检查
- 记录最新章节
- 记录失败原因
- 记录下一次检查时间

验证中心要求：

- API 模拟结果
- UI 模拟结果
- 最近一次验收报告
- 不依赖真实网络的 fake source 测试

## API 模拟测试要求

每个功能都要写 API 模拟测试。默认使用 fake source、mock HTTP、临时 DB，不能访问真实网络。

建议测试文件：

```powershell
tests\legado_engine\test_request_builder.py
tests\legado_engine\test_selectors.py
tests\legado_engine\test_jsonpath.py
tests\legado_engine\test_xpath.py
tests\legado_engine\test_regex.py
tests\legado_engine\test_js_runtime.py
tests\legado_engine\test_pipeline_search.py
tests\legado_engine\test_pipeline_detail_toc_content.py
tests\test_source_subscriptions.py
tests\test_source_repository_inventory.py
tests\test_single_source_test_api.py
tests\test_realtime_search_api.py
tests\test_explore_api.py
tests\test_book_reader_api.py
tests\test_admin_ui_routes.py
tests\test_verification_harness.py
```

测试命令：

```powershell
cd C:\Home\Workspace\UGit\legado-hub
.venv\Scripts\python.exe -m pytest tests\legado_engine -q
.venv\Scripts\python.exe -m pytest tests\test_source_subscriptions.py tests\test_source_repository_inventory.py tests\test_single_source_test_api.py -q
.venv\Scripts\python.exe -m pytest tests\test_realtime_search_api.py tests\test_explore_api.py tests\test_book_reader_api.py -q
.venv\Scripts\python.exe -m pytest tests\test_admin_ui_routes.py tests\test_verification_harness.py -q
```

完整测试只有在确认不会访问真实网络、不会调用全量真实书源后再跑：

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

## UI 模拟测试要求

后端启动：

```powershell
cd C:\Home\Workspace\UGit\legado-hub
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765
```

若 8765 被占用：

```powershell
netstat -ano | findstr :8765
```

不要随意杀掉非本任务进程；确认是本项目旧服务后再处理。

需要用浏览器或 Playwright 模拟这些页面：

```text
http://127.0.0.1:8765/admin
http://127.0.0.1:8765/admin/subscriptions
http://127.0.0.1:8765/admin/sources
http://127.0.0.1:8765/admin/search
http://127.0.0.1:8765/admin/explore
http://127.0.0.1:8765/admin/books
http://127.0.0.1:8765/admin/reader
http://127.0.0.1:8765/admin/update-tasks
http://127.0.0.1:8765/admin/cache
http://127.0.0.1:8765/admin/settings
http://127.0.0.1:8765/admin/verification
```

每个页面都要验证：

- 页面 200
- 中文标题
- 无假数据
- 有空状态/错误状态/部分成功状态之一
- 操作按钮可点击
- 表格不重叠
- 窄屏不明显错位

关键点击路径：

1. 订阅页：新增 fake 订阅，点击同步，查看同步状态。
2. 书源页：筛选启用/失败，打开详情，运行单源测试。
3. 搜索页：输入关键词，实时查看书源调用和搜索结果。
4. 发现页：选择书源，选择排行榜分类，加载结果。
5. 书籍页：打开详情，加载目录，进入阅读。
6. 阅读页：上一章/下一章，查看 source trace，触发 fallback。
7. 设置页：修改代理地址和批次大小，保存，再读取确认。
8. 验证页：运行 API/UI 模拟，查看报告。

## API Smoke 命令

启动服务后执行：

```powershell
@'
import json
from urllib.parse import quote
from urllib.request import Request, urlopen

base = "http://127.0.0.1:8765"

def get(path):
    with urlopen(base + path, timeout=30) as response:
        body = response.read().decode("utf-8")
        print("GET", path, response.status, body[:180].replace("\n", "\\n"))
        assert response.status == 200
        return json.loads(body)

def post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = Request(base + path, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=30) as response:
        body = response.read().decode("utf-8")
        print("POST", path, response.status, body[:180].replace("\n", "\\n"))
        assert response.status == 200
        return json.loads(body)

get("/api/admin/settings")
get("/api/admin/source-subscriptions")
get("/api/admin/sources?limit=5")
get("/api/admin/progress")

post("/api/admin/search-jobs", {"keyword": "凡人修仙传", "page": 1, "limit": 3})

get("/api/admin/explore/sources")
get("/api/admin/books?limit=5")
get("/api/admin/update-tasks?limit=5")
get("/api/admin/cache")
get("/api/admin/verification")
'@ | .venv\Scripts\python.exe -
```

如果 API 名称不同，必须在最终报告中列出实际 API 和原因。

## 最终验收报告必须包含

写入：

```powershell
docs\verification\full-legado-backend-verification.md
```

必须包含：

1. 改动文件列表。
2. 新增模块说明。
3. 上游源码拆解结论。
4. 阅读规则能力矩阵。
5. 订阅系统 API/UI 验证结果。
6. 书源管理 API/UI 验证结果。
7. 单源调用 API/UI 验证结果。
8. 实时搜索 API/UI 验证结果。
9. 排行榜/发现 API/UI 验证结果。
10. 书籍详情/目录/正文阅读 API/UI 验证结果。
11. 缓存/追更 API/UI 验证结果。
12. 代理 fallback 验证结果。
13. 失败诊断与自动禁用验证结果。
14. 浏览器点击路径验证截图或文字证据。
15. 所有执行过的命令。
16. 测试结果。
17. 未完成项和明确原因。
18. 后续建议。

## Kimi 最终回复格式

最终回复请用中文，包含：

```text
完成状态：

核心交付：
- ...

验证结果：
- API 模拟：
- UI 模拟：
- 浏览器点击：
- 测试命令：

关键文件：
- ...

已知限制：
- ...

验收报告：
docs/verification/full-legado-backend-verification.md
```

不要只说“已完成”，必须给证据。

