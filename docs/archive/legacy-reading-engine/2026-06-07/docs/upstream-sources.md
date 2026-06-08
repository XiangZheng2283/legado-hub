# LegadoHub 上游来源清单

本文记录第一批书源与规则来源。LegadoHub 后续会把这些来源分成“直接导入书源”“聚合索引”“规则/净化来源”“同步器参考实现”几类，避免把不同用途混在同一条链路里。

## 来源

### XIU2/Yuedu

- 地址：https://github.com/XIU2/Yuedu
- 类型：直接导入书源
- 当前主分支：`master`
- 核心文件：`shuyuan`
- 用途：第一阶段优先接入，作为小规模精品书源样本。
- 注意：README 明确说明书源较少、维护不积极，因此适合作为稳定样本，不适合作为唯一来源。

### aoaostar/legado

- 地址：https://github.com/aoaostar/legado
- 类型：聚合发布站 + 同步器参考实现
- 当前分支：
  - `main`：Python 同步器源码与来源配置
  - `release`：生成后的 README、网页与 `sources/*.json`
- 用途：参考其同步配置、聚合产物结构和发布方式；第一阶段可读取 release 分支中的书源 JSON。
- 注意：`main` 分支内已经把 `XIU2/Yuedu` 作为一个上游来源。

### Luoyacheng/legado

- 地址：https://github.com/Luoyacheng/legado
- 类型：阅读 APP 本体 + 原生书源解析引擎来源
- 当前主分支：`main`
- 核心文件：
  - `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeRule.kt`
  - `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeUrl.kt`
  - `app/src/main/java/io/legado/app/model/analyzeRule/RuleAnalyzer.kt`
  - `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByJSoup.kt`
  - `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByXPath.kt`
  - `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByJSonPath.kt`
  - `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByRegex.kt`
  - `app/src/main/java/io/legado/app/data/entities/BookSource.kt`
  - `app/src/main/java/io/legado/app/data/entities/rule/*.kt`
  - `app/src/main/java/io/legado/app/model/webBook/SearchModel.kt`
  - `app/src/main/java/io/legado/app/model/webBook/BookChapterList.kt`
  - `app/src/main/java/io/legado/app/model/webBook/BookContent.kt`
  - `modules/rhino/src/main/java/com/script/**/*.kt`
- 用途：优先用于获取/移植/桥接阅读原生书源解析引擎。它覆盖 URL 规则、CSS/JSoup、XPath、JsonPath、Regex、JS/Rhino、WebView JS、Cookie、并发限速、搜索、目录和正文解析链路。
- 注意：该项目是 Android/Kotlin 工程，解析链路依赖 Android、OkHttp、Rhino、Room 实体、配置和部分 WebView 能力。第一阶段不应直接硬搬全 APP，而应先评估“JVM 规则引擎抽取”或“独立解析服务桥接”。

### Yiove 综合书源库

- 地址：https://shuyuan.yiove.com/
- 类型：在线聚合索引 + 可下载书源合集
- 真实 API：`https://shuyuan-api.yiove.com`
- 核心接口：
  - `GET /shuyuan/book-source-collections?page=1&page_size=100`
  - `GET /import/book-source-collection/{collection_id}`
- 用途：作为“发现候选书源”的入口之一，并已接入 2026 年更新的书源合集。
- 当前处理：筛选 `create_time` 位于 2026 年内的合集，下载合集内容后按站点归档。
- 注意：页面路由 `https://shuyuan.yiove.com/book-source-collections?page=1&page_size=20` 是 SPA 前端路由，直接请求会返回 HTML；真实数据来自 `shuyuan-api.yiove.com`。

### freeok/so-novel

- 地址：https://github.com/freeok/so-novel
- 类型：规则来源 + 聚合搜索实现参考
- 当前主分支：`main`
- 核心文件：
  - `bundle/rules/main.json`
  - `bundle/rules/proxy-required.json`
  - `bundle/rules/rate-limit.json`
  - `bundle/rules/no-search.json`
  - `bundle/rules/cloudflare.json`
  - `bundle/rules/rule-template.json5`
- 用途：作为第一批规则来源和规则引擎参考。该项目已经有聚合搜索、规则分类、限流、代理、Cloudflare、正文过滤等实践。
- 注意：它不是阅读 APP 书源格式，而是 So Novel 自有规则格式。接入时需要做规则转换或单独实现 So Novel 规则适配层。

### sjshb57/legado-57

- 地址：https://github.com/sjshb57/legado-57
- 类型：规则/净化/辅助来源候选
- 当前主分支：`main`
- 用途：作为规则来源候选，后续检查其目录结构、规则格式、可复用范围。
- 注意：接入前需要单独扫描内容类型，确认哪些是书源、哪些是替换规则、哪些只是脚本或说明。

## 第一阶段接入顺序

1. `XIU2/Yuedu`：小、直接、适合验证解析链路。
2. `Luoyacheng/legado`：阅读原生解析引擎来源，决定规则执行兼容性。
3. `aoaostar/legado` release：聚合产物多，适合验证批量导入和去重。
4. `freeok/so-novel`：规则集和聚合搜索实现成熟，适合做规则适配层参考。
5. `sjshb57/legado-57`：先扫描分类，再决定是否接入。
6. `Yiove`：已接入 2026 年更新合集，后续再扩展为持续自动发现。

## 原则

- 不直接公开大规模缓存正文；第一阶段只缓存用户访问或追更过的书籍章节。
- 自动发现的新来源先进入候选池，不直接暴露给阅读端。
- 每个来源记录许可、更新时间、可用率、响应速度和失败原因。
- AI 校对默认用于元数据、章节标题和异常段落；不要默认对所有正文做全量重写。
- 生成给阅读端导入的聚合书源参考 `docs/reference-aggregate-source.md`，样本副本位于 `data/sources/reference/光遇聚合26.6.2.json`。
