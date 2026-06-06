# LegadoHub 项目规划

## 项目定位

LegadoHub 是一个面向阅读/Legado APP 的本地书源聚合中间层。阅读端只导入一个由 LegadoHub 生成的聚合书源；搜索、详情、目录、正文、追更、缓存、书源治理和 AI 校对都由本地服务端完成。

第一阶段优先运行在 Windows 下，以脚本形式启动；Docker 放到后期封装。项目根目录为：

`C:/Home/Workspace/UGit/legado-hub`

## 核心目标

1. 对阅读端暴露一个聚合后的单书源。
2. 聚合多个阅读书源、So Novel 规则源和后续自定义源。
3. 当阅读端搜索时，服务端并发搜索多个上游源，合并、去重、排序和规范化结果。
4. 用户打开书籍后，服务端记录本地追更任务，定时检查新章节。
5. 章节正文由服务端拉取、清理、缓存，并按需做多源 fallback。
6. 后续加入 AI 多源对照、元数据校对、错字整理、异常段落清理和屏蔽处理。
7. 后续从搜索引擎、公开仓库和聚合索引中发现候选新书源。
8. 定期检测、降权、禁用或清理无用书源。

## 已确认的架构方向

### 运行形态

- 第一阶段：Windows 本地脚本启动。
- 后期：Docker / Docker Compose 封装。
- 阅读端访问本机或局域网中的 LegadoHub HTTP 服务。

### 解析引擎方向

采用 Python 自研统一解析引擎，不直接抽取 Kotlin/JVM/Android 引擎作为运行时。

原因：

- 阅读 APP 原生引擎依赖 Android、Room、WebView、Rhino、OkHttp、配置和实体模型，直接复用成本高。
- LegadoHub 是服务端聚合系统，更适合把规则抽象成统一中间表示，再由 Python 执行。
- `Luoyacheng/legado` 作为语义参考，`freeok/so-novel` 作为规则模型和站点适配参考。

### 统一规则层

设计 LegadoHub 自己的规则中间层：

- `SearchRule`
- `BookInfoRule`
- `TocRule`
- `ContentRule`
- `ExploreRule`
- `RequestSpec`
- `ExtractSpec`
- `CleanSpec`
- `RateLimitSpec`

不同来源通过适配器转换为统一规则：

- `LegadoRuleAdapter`：读取阅读书源 JSON。
- `SoNovelRuleAdapter`：读取 So Novel 规则 JSON。
- `NativeRuleAdapter`：读取 LegadoHub 自有规则。
- `PluginAdapter`：为特别复杂的网站提供 Python 原生插件。

## 已定义功能列表

### 聚合书源生成

- 生成一个阅读端可导入的单书源 JSON。
- 参考样本：`data/sources/reference/光遇聚合26.6.2.json`。
- 生成结果输出到 `generated/legadohub-source.json`。
- 书源内部通过 JS 请求 LegadoHub 服务端接口。
- 书源 JS 只负责请求、编码、解码和轻量兼容；复杂逻辑放服务端。

### 本地 HTTP 服务

- 提供健康检查接口。
- 提供阅读端调用接口：
  - 搜索
  - 详情
  - 目录
  - 正文
- 提供后续管理接口：
  - 上游来源同步
  - 书源状态查询
  - 缓存状态查询
  - 追更任务查询

### 后端 Web 界面

阶段 2 开始同步建立后端 Web 界面，用于在服务端直接验证规则解析和聚合结果。第一版 Web 界面不追求完整管理台，而是作为调试和浏览工具：

- 搜索书籍。
- 展示聚合搜索结果。
- 查看书籍详情。
- 查看目录列表。
- 查看章节正文。
- 展示命中的上游来源、耗时、错误和 fallback 情况。
- 查看缓存命中状态。

该界面用于缩短规则调试闭环，避免所有验证都依赖阅读端。

### 上游来源管理

- 从配置文件读取来源：`config/upstream_sources.yml`。
- 支持 GitHub raw 文件、Git 分支、网站索引等来源类型。
- 记录来源类型、优先级、启用状态、备注。
- 原始书源归档输出到 `data/sources/raw/`，并按站点拆分，详见 `docs/raw-source-archive.md`。
- 初始来源包括：
  - `XIU2/Yuedu`
  - `aoaostar/legado`
  - `Luoyacheng/legado`
  - `freeok/so-novel`
  - `sjshb57/legado-57`
  - `Yiove 综合书源库`

### 规则解析引擎

- 支持阅读书源常见能力：
  - CSS selector
  - XPath
  - JsonPath
  - Regex
  - `@js:`
  - `<js>...</js>`
  - `{{...}}`
  - URL 参数规则
  - 请求头
  - Cookie
  - GET / POST
  - 分页搜索
  - 分页目录
  - 分页正文
- 支持 So Novel 规则：
  - `bundle/rules/main.json`
  - `proxy-required.json`
  - `rate-limit.json`
  - `no-search.json`
  - `cloudflare.json`
- 支持源级限流、重试、代理和失败降级。

### 聚合搜索

- 并发搜索多个启用源。
- 合并同名同作者结果。
- 保留多个来源的候选信息。
- 按匹配度、来源权重、响应速度、结果完整度排序。
- 支持精确搜索和宽松搜索。
- 搜索后可触发本地书籍记录和追更任务创建。

### 书籍详情

- 从搜索结果还原或请求详情页。
- 合并多源元数据：
  - 书名
  - 作者
  - 简介
  - 封面
  - 分类
  - 字数
  - 状态
  - 最新章节
  - 更新时间
- 后续可加入 AI 元数据规范化。

### 目录与正文

- 获取目录并缓存。
- 识别目录更新和新增章节。
- 获取正文并缓存。
- 正文失败时按候选源 fallback。
- 基础清理：
  - 空行整理
  - 广告段过滤
  - 异常 HTML 清理
  - 屏蔽词处理
  - 简繁/标点规范化候选

### 追更任务

- 用户访问或添加书籍后，创建本地追更任务。
- 周期性检查目录是否更新。
- 有新章节时拉取正文并缓存。
- 记录最后检查时间、最新章节、失败原因和重试状态。

### AI 校对与多源对照

第一阶段不做全文 AI 重写。后续按成本控制逐步加入：

- 搜索结果规范化。
- 书名、作者、章节名校对。
- 多源正文差异检测。
- 异常段落识别。
- 错字和 OCR/乱码疑似段落修复。
- 屏蔽词与广告段落清理。
- 仅在规则判断有必要时调用 AI。

### 书源发现与治理

后续阶段加入：

- 从 Yiove、GitHub、搜索引擎发现候选源。
- 候选源进入待审核/沙箱池。
- 定期健康检查。
- 记录可用率、响应时间、失败类型、章节完整度。
- 自动降权或禁用失效源。
- 清理长期无效源。

## 阶段规划

### 阶段 0：项目基线

- 建立目录结构。
- 登记上游来源。
- 保存聚合书源参考样本。
- 明确 Python 自研解析引擎方向。
- 拉取第一批可公开获取的书源/规则，并按站点归档到 `data/sources/raw/`。

当前状态：已完成。

### 阶段 1：Windows 本地服务最小闭环

**状态：已完成。**

- 建 FastAPI 服务骨架。
- 添加 `start.bat`。
- 添加 SQLite 存储。
- 实现健康检查。
- 生成第一版聚合书源 JSON。
- 阅读端导入后能请求本地服务。

**实现产物：**

- `requirements.txt`
- `start.bat`
- `app/__init__.py`
- `app/main.py`
- `app/config.py`
- `app/api/__init__.py`
- `app/api/health.py`
- `app/api/legado.py`
- `app/core/__init__.py`
- `app/core/source_generator.py`
- `app/storage/__init__.py`
- `app/storage/db.py`
- `tests/test_health.py`
- `tests/test_db.py`
- `tests/test_source_generator.py`
- `docs/phase-1-verification.md`

**验收标准：**

- 双击脚本可启动。
- 浏览器访问健康检查成功。
- 手机端可使用脚本打印的局域网 URL 导入聚合书源。
- 生成的聚合书源 JSON 可被阅读导入。
- pytest 全部通过。

### 阶段 2：阅读书源解析 MVP

**状态：已完成。**

- 建立 20 个 Legado 候选书源池，不默认全量加载 2307 个站点文件。
- 建立面向大量书源的并发搜索执行模型：有限并发、单源超时、整体超时、失败隔离、结构化 debug 信息。
- 实现阅读规则的最小解析能力（CSS selector 链、XPath、text/href/src 提取、replaceRegex）。
- 跑通搜索、详情、目录、正文。
- 缓存搜索结果、目录和正文。
- 同步建立后端 Web debug 界面。

**实现产物：**

- `config/phase2_sources.json`
- `app/rules/__init__.py`
- `app/rules/models.py`
- `app/rules/legado_loader.py`
- `app/rules/legado_adapter.py`
- `app/engine/__init__.py`
- `app/engine/fetcher.py`
- `app/engine/extractor.py`
- `app/engine/legado_executor.py`
- `app/services/__init__.py`
- `app/services/source_pool.py`
- `app/services/catalog.py`
- `app/services/cache.py`
- `app/web/__init__.py`
- `app/web/debug.py`
- `tests/test_phase2_sources.py`
- `tests/test_extractor.py`
- `tests/test_legado_executor.py`
- `tests/test_catalog_api.py`
- `docs/phase-2-verification.md`

**验收标准：**

- 20 个候选源完成预检，清楚标记启用、禁用和禁用原因。
- 至少一个真实阅读书源可完成搜索到正文（biquges123-com）。
- 阅读端通过 LegadoHub 聚合书源能请求本地服务端点。
- 后端 Web debug 界面可完成搜索、打开详情、查看目录、阅读正文。
- pytest 全部通过。

### 阶段 3：完整解析引擎、Web 后台与追更

- 完整推进阅读/Legado 书源解析引擎，覆盖 CSS selector、XPath、JsonPath、Regex、`@js:`、`<js>...</js>`、`{{...}}`、请求头、Cookie、GET/POST、分页搜索、分页目录、分页正文和常见清理规则。
- 更新聚合书源配置层，新增 `config/aggregate_source.json`，确保书源版本、生成路径、启用源数量、健康源数量、代理源数量和 parser progress 可同步展示。
- 建立完整中文 Web 后台控制台，替代 Phase 2 debug-only 页面；界面设计使用 `impeccable` 为主，`taste-skill` 作为反模板化和视觉预检约束。
- Web 后台不要过度极简，使用分割线、分组面板、表格行线、清晰网格和适度留白体现设计感；禁止使用表情符号。
- 默认代理地址配置为 `http://192.168.31.233:7890`，支持全局代理、单源代理模式、代理 fallback、代理状态记录和 Web 后台配置。
- 书源直接使用 `data/sources/raw/by-site/legado/` 作为 canonical repository；当前目录包含 2307 个 `*.json` 站点书源，后台必须能索引、分页、筛选和批量预检。
- 同一个站点文件可能包含多个 Legado 书源对象，必须展开为多个独立 source record，分别记录 `source_file_path`、`source_index/source_key`、启用状态、失败原因和测试结果。
- 运行时搜索不默认全量请求 2307 个站点，只搜索通过预检、健康检查、用户启用或 overlay 标记启用的 active pool。
- 书源调用必须分批执行，并自动记录失败书源；硬失败要禁用对应 source record，在后台书源列表和详情页展示失败阶段、失败原因、时间、直连/代理尝试记录。
- Web 后台必须支持对单个书源执行测试，测试结果可用于重新启用、禁用或标记代理模式。
- 并发搜索、去重、合并、排序，保留多源候选和排名解释。
- 建立书籍记录和追更任务。
- 定时检查新章节并缓存。

验收标准：

- Parser capability matrix 清楚列出支持、部分支持、暂不支持的阅读规则语法。
- 聚合书源配置和 parser/source progress 能在 API 与 Web 后台同步展示。
- Web 后台包含 Dashboard、Sources、Source Detail、Search Workbench、Books、Update Tasks、Cache、Settings、Aggregate Source 等页面。
- Web 后台无假数据，默认使用简体中文，具备加载、空、错误、部分成功状态，且符合 `PRODUCT.md`、`impeccable` 与 `taste-skill` 的产品 UI 约束。
- Web 后台不使用表情符号；页面层级主要通过分割线、留白、对齐、字体权重和状态标签体现。
- 默认代理 `http://192.168.31.233:7890` 生效，并能验证自动 fallback 或模拟 fallback。
- 多对象 raw JSON 文件能完整展开，不再只读取第一个书源对象。
- 分批搜索返回 batch count、attempted source count、success/failure/disabled count 和 partial-success 状态。
- 某个书源失败后，对应 source record 自动记录失败原因并禁用；后台能看到原因并手动测试该书源。
- 同一本书能展示多源聚合结果。
- 访问过的书能自动建立追更任务，并能手动触发一次目录更新检查。
- 阅读端通过 LegadoHub 聚合书源能完成搜索、详情、目录、正文。
- pytest 全部通过。

### 阶段 4：So Novel 规则适配

- 解析 So Novel 规则格式。
- 转换为 LegadoHub 内部规则。
- 接入限流、代理、Cloudflare 分类信息。

验收标准：

- 至少一个 So Novel 规则源能通过 LegadoHub 执行搜索和正文获取。

### 阶段 5：AI 与书源治理

- AI 元数据规范化。
- 章节标题和异常正文检测。
- 书源健康评分。
- 自动发现候选源。
- 自动降权和清理失效源。

### 阶段 6：Docker 化与管理台

- Dockerfile。
- Docker Compose。
- 完整 Web 管理台。
- 配置 AI provider、代理、并发、缓存策略。

## 暂缓事项

- 不在第一阶段做 Docker。
- 不在第一阶段做完整 Web 管理台。
- 不在第一阶段做全文 AI 校对。
- 不在第一阶段自动抓取公开互联网全量书源。
- 不在第一阶段追求 100% 兼容阅读全部规则语法。

## 当前已建立文件

- `docs/upstream-sources.md`
- `docs/reference-aggregate-source.md`
- `docs/project-plan.md`
- `docs/raw-source-archive.md`
- `docs/skills/book-source-craft/SKILL.md`
- `config/upstream_sources.yml`
- `data/sources/reference/光遇聚合26.6.2.json`
- `data/sources/raw/manifest.json`
- `data/sources/raw/by-site/legado/*.json`
- `data/sources/raw/by-site/so-novel/*.json`
- `data/sources/raw/rule-packs/*.json`
- `scripts/collect_source_archives.py`
