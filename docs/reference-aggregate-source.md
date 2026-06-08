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
- 搜索、排行、详情、目录和正文响应可能返回 `debug.browserChallenges`。
  阅读端或外部客户端可使用
  `/api/legado/browser-challenges/{session_id}/browser/open` 启动浏览器助手，
  或使用 `/api/legado/browser-challenges/{session_id}/cookies`
  提交验证 Cookie，并使用
  `/api/legado/browser-challenges/{session_id}/retry-live-check` 重试排行榜阅读闭环；
  后台控制台仍可作为人工验证入口。

## 后续待办

1. 从样本中抽取最小聚合书源模板。
2. 将固定域名/路径替换为 LegadoHub 本地服务地址。
3. 设计 LegadoHub 服务端返回结构。
4. 生成第一版 `backend/generated/legadohub-source.json`。
5. 用阅读端导入验证搜索、详情、目录、正文四段链路。
