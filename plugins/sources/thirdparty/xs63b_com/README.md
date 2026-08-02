# 小说路上 (xs63b_com)

- 站点：`https://m.xs63e.com`（`xs63b.com` 已跳转到该域名）
- 类型：简体中文 HTML 站，无登录
- 访问层：四段全部 `ctx.access.http`，当前宿主直连可用，不需要浏览器或新增依赖

## 链路

| 阶段 | 请求 | 说明 |
|---|---|---|
| 搜索 | 先取首页 CSRF token，再 `POST /search` | 只返回一个精确或高可信候选，并由详情补全订阅字段 |
| 详情 | `GET /{category}/{book}/` | OpenGraph 元数据；「正文」标题后的 `ul.chapter` 是正序完整目录 |
| 目录 | 同详情页 | 排除上方倒序的 6 条最新章节预览，只保留完整正文目录 |
| 正文 | `GET /{category}/{book}/{chapter}.html` | 续页 slug 由页内 `jsstr` Base64 解码后按 `jsarr` 重排；出现正常“下一章”链接即停止 |

## 实网取证（2026-07-31）

- 关键词：`凡人：我有一尊强化炉`
- 详情：`https://m.xs63e.com/qita/woyouyizunqianghualu/`，作者二哈奇士，状态连载中
- 完整目录：33 章；首章「第1章 万灵真经」，末章「第33章 出发」
- 首章正文：3 个动态 slug 页面合并，原始文本 3510 字符 / 2873 个中文字符

## 订阅字段

搜索结果和详情均返回非空的 `sourceId`、`name`、`author`、`bookUrl`、`tocUrl`、
`lastChapter`、`bookStatus`，`chapterCount` 与完整目录一致。站点不提供字数，`wordCount`
留空；`sourceName` 和 `bookId` 由宿主生成。

## 已知限制

- 搜索为了避免逐本抓取目录，只返回一个精确或高可信候选。
- 动态 slug 的编码或终止标记变化时会显式失败，不会把截断正文当作成功结果。
