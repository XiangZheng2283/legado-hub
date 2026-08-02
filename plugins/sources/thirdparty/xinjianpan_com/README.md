# 新键盘小说网 (xinjianpan_com)

- 站点：`https://www.xinjianpan.com`
- 类型：简体中文 HTML 站，无登录、无 Cloudflare 挑战
- 访问层：四段全部 `ctx.access.http`；本机宿主直连 TLS 失败，metadata 固定走已验证的宿主代理，不需要浏览器或新增依赖

## 链路

| 阶段 | 请求 | 说明 |
|---|---|---|
| 搜索 | `GET /search/?searchkey=` | 同名书可能有多条；只返回精确或高可信候选中总字数最高的一条，再用详情补全订阅字段 |
| 详情 | `GET /txt/{book}/` | 读取 OpenGraph 元数据，并读取目录第 1 页的分页范围取得精确总章数 |
| 目录 | `GET /txt/{book}/list-1.html` ... | 从 `<select>` 读取全部分页，章节真实 URL 位于 `onclick="location.href='...'"` |
| 正文 | `GET /txt/{book}/{chapter}.html` | 静态前半段与 `var c` 中双层 Base64 后半段合并，移除站点广告和转载声明 |

## 实网取证（2026-07-31）

- 关键词：`凡人修仙传`
- 详情：`https://www.xinjianpan.com/txt/8ki/`，作者忘语，状态全本
- 完整目录：25 页，2456 章；首章「第一章 山边小村」
- 正文样本：`https://www.xinjianpan.com/txt/8ki/vl7.html`
- 访问对照：宿主 Fetcher 直连为 `ConnectError`；同一 Fetcher 走已配置代理后四段完整通过

## 订阅字段

搜索结果和详情均返回非空的 `sourceId`、`name`、`author`、`bookUrl`、`tocUrl`、
`lastChapter`、`bookStatus`，`chapterCount` 来自完整目录分页范围。站点详情未提供独立字数字段，
搜索结果的 `wordCount` 会在搜索链路中保留；`sourceName` 和 `bookId` 由宿主生成。

## 已知限制

- 搜索为了避免给大量模糊结果逐本抓取目录，只返回一个精确或高可信候选。
- 解密格式若变化会显式失败，不会把只有前半章的内容当作成功结果。
