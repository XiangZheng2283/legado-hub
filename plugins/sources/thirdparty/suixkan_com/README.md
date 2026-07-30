# 随心看 (suixkan_com)

- 站点：`https://m.suixkan.com`（悦友 `yueyouxs` 平台的移动站）
- 类型：简体中文 HTML 站，无登录、无 Cloudflare 挑战
- 访问层：四段全部 `ctx.access.http`

## 链路

| 阶段 | 请求 | 说明 |
|---|---|---|
| 搜索 | `GET /s/1.html?keyword=` | 结果项带书名、作者、分类、字数、简介、封面 |
| 详情 | `GET /b/{book_id}.html` | 作者/分类/字数在 `.face-info .v-words span` 的「作者：」等行里 |
| 目录 | `GET /c/{book_id}.html` | 单页完整目录（示例书 3876 章），无分页 |
| 正文 | `GET /r/{book_id}/{chapter_id}.html` | 整章在同一页，分成多个 `div.section` |

## 解析注意

1. **搜索结果没有 `href`**：书链接写在 `onclick="newWebView('/b/231970.html', …)"` 里，
   必须从 `onclick` 提取，普通的 `a[href]` 扫描什么都找不到
   （这也是第一轮启发式探测判定「搜索无结果」的原因）。
2. **正文分块但不分页**：一章在 HTML 里就是完整的，切成
   `div.section`（第一个可见，其余带 `class="section none"`），
   标题形如「第一章：风口浪尖(1/5)」。插件拼接所有 `.con` 段落，
   去掉「（本章未完，请翻页）」「（本章完）」，并从标题里去掉 `(1/5)`。
3. **部分容器 class 是随机串**（如 `mxyrDAiUlq rbvhqhoGSHeq`），
   不要依赖它们；`.book / .section / .con / .v-list-item / .face-info` 是稳定的。
4. 搜索是**模糊匹配**：搜「凡人修仙传」会返回一堆带「传」的书。
   精确命中会排在第一位，插件按精确书名优先。

## 实网取证（2026-07-27）

- 搜索：`GET https://m.suixkan.com/s/1.html?keyword=清宫熹妃传` -> 1 条精确结果
- 详情：`https://m.suixkan.com/b/231970.html`，清宫熹妃传 / 解语 / 古代言情 / 814.43 万字
- 目录：`https://m.suixkan.com/c/231970.html`，**3876 章**，首章「第一章：风口浪尖」
- 正文：`https://m.suixkan.com/r/231970/231971.html`，**1553 字符**（5 个 section 合并）

## 已知限制

- 站内没有《凡人修仙传》，smoke 关键词使用站内存在的「清宫熹妃传」。
- 目录页单页 626 KB，解析成本偏高，但只有一次请求。
- 详情页不暴露最新章节和更新时间，`lastChapter` / `updateTime` 返回空。
- 未验证镜像域，`metadata.baseUrls` 只写实测通过的 `https://m.suixkan.com`。
