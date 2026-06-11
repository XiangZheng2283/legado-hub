# 聚合书源参考样本

参考文件：

- 原始文件：`C:/Users/moo/Desktop/光遇聚合26.6.2.json`
- 归档副本：`docs/archive/legacy-reading-engine/2026-06-07/data/sources/reference/光遇聚合26.6.2.json`

## 样本定位

该文件是后续 LegadoHub 生成“暴露给阅读端的聚合书源”的格式参考。它不是活跃运行时输入，也不是多个书源列表，而是一个单条阅读书源：

- `bookSourceName`: `🔅光遇聚合(26.6.2)`
- `bookSourceUrl`: `光遇聚合`
- `bookSourceType`: `0`
- `bookSourceGroup`: `聚合,番茄,七猫,塔读,QQ阅读,书旗,轻小说`
- 顶层包含完整的 `searchUrl`、`ruleSearch`、`ruleBookInfo`、`ruleToc`、`ruleContent`、`ruleExplore`、`jsLib`。

## 对 LegadoHub 的参考价值

LegadoHub 后续也应生成一个“单书源聚合壳”，让阅读端只导入一个书源。这个书源内部通过 JS 和规则请求 LegadoHub 服务端接口，再把服务端返回的数据转换为阅读能识别的搜索、详情、目录和正文结果。

推荐对齐的链路：

1. `searchUrl`：构造搜索请求参数，例如关键字、页码、搜索模式、禁用源等。
2. `ruleSearch.bookList`：解析服务端搜索结果列表。
3. `ruleSearch.bookUrl`：把选中的搜索结果编码成详情入口。
4. `ruleBookInfo.init`：根据详情入口请求或还原服务端详情数据。
5. `ruleBookInfo.tocUrl`：把书籍信息编码成目录入口。
6. `ruleToc.chapterList`：请求并解析目录列表。
7. `ruleToc.chapterUrl`：把章节信息编码成正文入口。
8. `ruleContent.content`：请求服务端正文，做清理、格式化和 fallback。
9. `jsLib`：放置聚合书源公共函数，例如编码/解码、接口地址、设置读取、通用请求、错误处理。

## 生成器约束

- 生成结果应是 JSON 数组，第一阶段只包含一个聚合书源对象。
- `bookSourceUrl` 应使用稳定唯一值，例如 `LegadoHub` 或 `legado-hub.local`。
- `bookSourceName` 应包含版本号，便于阅读端识别更新。
- `enabledCookieJar` 建议开启，方便后续处理需要 Cookie 的源。
- 聚合 API 地址应集中写入 `jsLib` 或变量，不要散落在每个规则里。
- 服务端返回结构要尽量稳定，避免频繁修改阅读端规则。
- 大量业务逻辑应放在 LegadoHub 服务端，书源 JS 只做请求、编码、解析和必要兼容。
- 搜索 URL 的等待时间应与后端整体搜索窗口平齐。当前聚合源使用
  `waitMs=180000`，后端 `/api/legado/search` 也允许最多等待 180000ms。若
  命中整词缓存，阅读端应直接返回缓存结果，并在后台异步刷新缓存；若没有缓存，
  再进入实时搜索等待窗口。
- 阅读端导入书源时使用的 `base_api` 必须贯穿搜索、详情、目录和章节返回。
  如果用户从局域网地址导入，后续 `bookUrl`、`tocUrl`、`chapterUrl` 也必须
  使用同一个可访问的局域网地址，不能回落到 `127.0.0.1`。
- 完整搜索页和换源页的展示字段要分开：`kind` 保留分类、状态、标签等书籍
  元数据；换源页需要的来源展示通过 `readingSourceName` 与
  `readingLastChapter` 承载。`readingLastChapter` 推荐格式为
  `书源 · 最新章节`，作者继续走标准 `author` 字段，避免阅读端把作者误拼到
  最新章节列中。
- 搜索、排行、详情、目录和正文遇到 Cloudflare 或浏览器挑战时，不再向阅读端返回手动验证入口。
  服务端会在 `debug.errors[]` 或诊断信息中标记 `bypassRequired`，当前请求跳过该源；
  后续应通过后端绕过策略、浏览器模拟能力或其他可维护方案恢复，而不是让用户逐源验证。

## 付费聚合源经验

- 参考源通常不会把真实站点 URL 直接暴露给阅读端，而是用
  `data:...;base64,...` 包装搜索、详情、目录、正文阶段的内部 payload。
  下一阶段规则再解包 payload 并请求服务端接口。
- 搜索结果直接映射真实书籍字段：`name` 是书名，`author` 是作者，
  `lastChapter` 拼接来源和最新章节，`kind`/`intro` 承载分类、状态、简介等
  信息，避免阅读端把聚合源名或搜索提供器名误当成书名。
- 搜索页拿不到的最新章节、分类、字数、连载状态，应在详情阶段补齐；
  对 LegadoHub 的 Python 书源插件来说，这个补齐必须发生在插件自己的
  `search()` 中，通常通过同源 `detail()` 解析器完成。
- 风控降级顺序应是普通 HTTP 搜索、浏览器能力、站内排行榜/分类兜底。
  降级仍必须返回可验证的真实字段，不能伪造缺失信息。

## 后续待办

1. 从样本中抽取最小聚合书源模板。
2. 将固定域名/路径替换为 LegadoHub 本地服务地址。
3. 设计 LegadoHub 服务端返回结构。
4. 生成第一版 `backend/generated/legadohub-source.json`。
5. 用阅读端导入验证搜索、详情、目录、正文四段链路。
