# 企鹅小说 (qiexs_cc)

- 站点：`http://www.qiexs.cc`
- 类型：简体中文 HTML 站，无登录、无 Cloudflare 挑战
- 访问层：四段全部 `ctx.access.http`

## 链路

| 阶段 | 请求 | 说明 |
|---|---|---|
| 搜索 | `POST /search/`，表单 `keyword`，带 `Referer` | 结果页含书名、作者、封面、简介、最新章节 |
| 详情 | `GET /xiaoshuo/{book_id}.html` | OpenGraph 元数据齐全；`tocUrl` 就是详情页自身 |
| 目录 | 同详情页 `#list-chapterAll` | 正序完整目录；页面上方另有倒序「最新章节」预览块，必须避开 |
| 正文 | `GET /xiaoshuo/{book_id}/{chapter_id}.html` | `#htmlContent` 下的 `<p>` 段落，无同章分页 |

## 解析注意

- 搜索结果的书名被 `<em>` 包裹关键词，`title` 属性里是 HTML 转义后的 `&lt;em&gt;`，
  因此取 `a` 的文本而不是 `title`。
- 目录页同一本书会出现两个区块：`最新章节`（倒序，只有末尾若干章）和
  `#list-chapterAll`（正序全量）。只解析后者，否则目录顺序会被污染。
- 正文页 `#htmlContent` 内可能混入 `div` 广告块，解析前整体丢弃 `div`；
  再按 60 字以内且含站点关键词的行过滤导航噪声。

## 实网取证（2026-07-27）

- 搜索：`POST http://www.qiexs.cc/search/`，关键词「小小凡人修仙传」-> 1 条精确结果
  （关键词「凡人修仙传」-> 30 条）
- 详情：`http://www.qiexs.cc/xiaoshuo/20789.html`，书名「小小凡人修仙传」，作者「至尊小宝」
- 目录：同上 URL，**628 章**，首章「第1章 想要一个梦想」
- 正文：`http://www.qiexs.cc/xiaoshuo/20789/11207891.html`，**2763 字符**

## 已知限制

- 站点在连续探测时会出现请求超时，重试一次即可恢复；插件不实现自有重试，由宿主负责。
- 站点没有收录《凡人修仙传》原作，smoke 关键词使用站内实际存在的「小小凡人修仙传」。
- 未验证镜像域，`metadata.baseUrls` 只写实测通过的 `http://www.qiexs.cc`。
