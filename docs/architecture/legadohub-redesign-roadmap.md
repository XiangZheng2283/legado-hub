# LegadoHub 阅读内核重构与后台重建路线

> 当前参考源码：`data/upstreams/luoyacheng-legado`  
> 上游仓库：`https://github.com/Luoyacheng/legado.git`  
> 当前 commit：`44e07fea541287804cc58d0168940a756cd11cfd`  
> 本路线替代旧的 Python 规则解析器补丁路线。

## 目标

LegadoHub 不再继续维护一套 Python 近似阅读规则引擎，而是拆成两个明确层次：

```text
Python/FastAPI 后端
  - 订阅、书源仓库、数据库、任务调度、缓存、SSE、聚合书源导出

Kotlin/JVM 阅读内核
  - BookSource 执行
  - AnalyzeUrl
  - AnalyzeRule
  - search/detail/toc/content/explore
  - JS/HTTP/Cookie/Trace runtime
```

第一阶段先完成阅读内核抽取重构，第二阶段再搭建新的动态后台。

## 总体原则

1. **以阅读源码为语义真相**  
   `Luoyacheng/legado` 的 `AnalyzeUrl`、`AnalyzeRule`、`WebBook`、`BookSource` 是规则执行基准。

2. **BookSource 是书源最小单位**  
   订阅文件只是 bundle；单个 `BookSource` 对象才是后端管理、启用、禁用、调试、搜索的单位。

3. **`bookSourceUrl` 是核心身份**  
   对齐阅读本地数据库。相同 `bookSourceUrl` 视为同一书源更新，不再使用“网站文件名 + index”作为身份。

4. **不继续按单网站文件聚合多配置**  
   废弃 `data/sources/raw/by-site/legado` 作为核心模型。新的内置源以订阅快照方式保存。

5. **后台不再使用静态 HTML**  
   第二阶段新建 `admin-web`，使用 React + Vite + TypeScript + Tailwind CSS + shadcn/ui。

6. **失败原因必须结构化**  
   网络失败、代理失败、规则缺口、JS 缺口、WebView 缺口、登录缺口、书源缺字段必须分开记录。

## 阶段一：阅读内核抽取重构

### 1.1 上游基准固定

产物：

```text
docs/architecture/upstream-legado-source-baseline.md
```

内容：

- 上游仓库 URL。
- commit hash。
- 必读源码入口。
- 哪些文件可直接抽取。
- 哪些 Android 依赖必须适配。
- GPL-3.0 许可证影响说明。

验收：

```powershell
git -C data\upstreams\luoyacheng-legado remote -v
git -C data\upstreams\luoyacheng-legado rev-parse HEAD
```

### 1.2 建立 `engine-jvm`

新增目录：

```text
engine-jvm/
  build.gradle.kts
  src/main/kotlin/legadohub/engine/
    api/
    model/
    runtime/
    trace/
    source/
  src/test/kotlin/legadohub/engine/
```

首批依赖：

```text
Kotlin/JVM + Java 17 toolchain
kotlinx-serialization-json
kotlinx-coroutines-core
OkHttp
Jsoup
JsonPath
Rhino 或上游 modules/rhino 兼容层
Kotest
```

第一批模型：

```text
BookSource
SearchRule
BookInfoRule
TocRule
ContentRule
ExploreRule
EngineRequest
EngineResult
EngineEvent
TraceEvent
UnsupportedReason
```

验收：

```powershell
.\gradlew :engine-jvm:test
```

如果本机没有 JDK，记录为环境阻塞，但模块结构和测试文件仍应完整落地。

### 1.3 BookSource 导入模型

实现目标：

- 能解析单个 BookSource JSON。
- 能解析 BookSource 数组。
- 能验证 `bookSourceName` / `bookSourceUrl`。
- 能保留 `bookSourceGroup`、`enabled`、`enabledExplore`、`header`、`loginUrl`、`enabledCookieJar`、`searchUrl`、`exploreUrl`、规则对象。

必须对齐阅读：

```text
primary identity = bookSourceUrl
group = bookSourceGroup
bundle index 只用于定位，不用于身份
```

测试：

```text
BookSourceJsonTest
BookSourceIdentityTest
```

### 1.4 Runtime 适配层

从阅读源码抽取时，Android 依赖必须替换为后端接口：

```text
HttpRuntime
CookieStore
SourceVariableStore
EngineCache
WebViewRuntime
EngineLogger
```

第一阶段默认策略：

```text
WebViewRuntime = 返回 unsupported(webview_required)
LoginRuntime = 返回 unsupported(login_required)
```

不要静默失败。

### 1.5 AnalyzeUrl 抽取

对齐阅读 `AnalyzeUrl.kt`：

- `{{key}}`、`{{page}}`、`{{title}}`、`{{author}}` 变量替换。
- GET / POST。
- body。
- header 合并。
- charset。
- source header。
- proxy hint。
- cookie jar hint。
- URL 中 `@js` / `<js>` 的分级处理。

测试：

```text
AnalyzeUrlTest
AnalyzeUrlHeaderTest
AnalyzeUrlBodyTest
AnalyzeUrlUnsupportedJsTest
```

### 1.6 AnalyzeRule 抽取

对齐阅读 `AnalyzeRule.kt`：

- CSS/JSoup。
- XPath。
- JsonPath。
- Regex。
- `@` 字段操作符。
- `||` fallback。
- `##` replace。
- `@put` / `@get`。
- `@js` 受限或 Rhino 执行。
- `<js>` 按能力执行或结构化 unsupported。

测试：

```text
AnalyzeRuleCssTest
AnalyzeRuleXPathTest
AnalyzeRuleJsonPathTest
AnalyzeRuleRegexTest
AnalyzeRuleFallbackTest
AnalyzeRuleReplaceTest
AnalyzeRuleJsTest
```

### 1.7 WebBook Pipeline

实现单源执行入口：

```kotlin
suspend fun search(source: BookSource, keyword: String, page: Int): EngineResult<SearchBook>
suspend fun detail(source: BookSource, bookUrl: String): EngineResult<BookInfo>
suspend fun toc(source: BookSource, tocUrl: String): EngineResult<BookChapter>
suspend fun content(source: BookSource, chapterUrl: String): EngineResult<BookContent>
suspend fun explore(source: BookSource, explorePath: String): EngineResult<SearchBook>
```

每个阶段必须输出：

```text
ok
items/data
trace
unsupported
error
latencyMs
```

### 1.8 批量并发执行

JVM engine 负责 batch 内并发，Python 负责 job 与 batch 调度。

默认：

```text
batchSize = 20
globalConcurrency = 20
perHostConcurrency = 2
sourceTimeout = 15s
requestTimeout = 8s
```

事件：

```text
source_started
request_started
direct_failed
proxy_started
result
source_done
source_failed
batch_done
job_done
```

### 1.9 Phase 1 验收

最低验收：

1. `engine-jvm` 能解析 XIU2/Yuedu 的 BookSource 数组。
2. 至少一个非 WebView/非登录源完成 `search -> detail -> toc -> content`。
3. WebView/login/复杂 JS 不静默失败，必须返回结构化 unsupported。
4. Python 旧规则执行器不再作为未来路线继续扩展。

命令：

```powershell
.\gradlew :engine-jvm:test
.venv\Scripts\python.exe -m pytest tests -q
```

## 阶段二：动态后台搭建

### 2.1 技术栈

```text
admin-web/
  React
  Vite
  TypeScript
  Tailwind CSS
  shadcn/ui
  TanStack Query
  TanStack Table
  React Router 或 TanStack Router
  Zustand
```

阅读 Web 参考：

```text
data/upstreams/luoyacheng-legado/modules/web/src/views/SourceEditor.vue
data/upstreams/luoyacheng-legado/modules/web/src/components/SourceList.vue
data/upstreams/luoyacheng-legado/modules/web/src/components/SourceDebug.vue
data/upstreams/luoyacheng-legado/modules/web/src/views/BookShelf.vue
```

只参考信息架构和交互，不复刻 Element Plus。

### 2.2 页面

```text
/admin/dashboard
/admin/sources
/admin/sources/:id
/admin/source-subscriptions
/admin/search
/admin/explore
/admin/books
/admin/reader
/admin/rule-engines
/admin/rule-audit
/admin/cache
/admin/update-tasks
/admin/settings
/admin/verification
```

### 2.3 UI 原则

- 中文界面。
- 无装饰性表情符号。
- 书源原始名称原样展示。
- 高信息密度但不混乱。
- 用分割线、留白、表格、抽屉、标签体现设计感。
- shadcn/ui 组件状态必须完整：loading、empty、error、partial success。
- 搜索和调试必须实时显示事件流。

### 2.4 核心布局

书源管理：

```text
左侧分组/状态筛选
中间虚拟滚动书源列表
右侧详情与调试抽屉
```

实时搜索：

```text
顶部搜索控制
中间实时结果
右侧书源调用进度
底部事件 trace
```

单源调试：

```text
阶段选择
请求参数
响应片段
规则 trace
解析结果
失败原因
```

## 阶段三：Python 后端整合

Python 后端保留：

```text
订阅同步
source_health
搜索任务
缓存
追更
API
SSE
聚合书源导出
```

Python 后端删除或冻结：

```text
app.engine.extractor
app.engine.legado_executor
app.engine.fetcher
```

代理策略可迁移为公共模块，或交给 JVM engine。

## 阶段四：最终验收

完整验收：

```powershell
.\gradlew :engine-jvm:test
.venv\Scripts\python.exe -m pytest tests -q
pnpm --dir admin-web typecheck
pnpm --dir admin-web build
```

验收报告：

```text
docs/verification/legado-kernel-redesign-verification.md
docs/verification/admin-web-redesign-verification.md
```

## 当前第一阶段执行顺序

1. 固定 `Luoyacheng/legado` commit。
2. 建立 `engine-jvm` Gradle 模块。
3. 实现 BookSource JSON 模型与测试。
4. 实现 EngineRequest / EngineResult / TraceEvent。
5. 实现第一版 CLI 或 library API。
6. 再开始抽取 AnalyzeUrl。

第一阶段不要先写后台，不要先做 shadcn/ui。
