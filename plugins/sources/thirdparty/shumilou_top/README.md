# 书迷楼（top）插件

通过 `www.shumilou.top` 网页接口提供搜索、详情、完整目录和正文读取。

- 搜索：`POST /search/`，字段 `searchkey`。
- 详情：`/lou/{book_id}/`，详情页同时包含最新章节与正文目录入口。
- 目录：详情页正文目录区分页 `/lou/{book_id}/{page}/`，插件会跨页合并去重。
- 正文：`/shu/{book_id}/{chapter_id}.html`，内容在 `#chaptercontent`；部分章节含 `_2.html` 等同章分页，插件会自动合并。

`.top` 与 `.co` 不是镜像，解析链路不同，本插件不回退到 `.co`。
