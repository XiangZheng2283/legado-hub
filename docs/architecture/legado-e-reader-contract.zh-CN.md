# `legado-E` 阅读端契约

## 基准

- 目标客户端：[Luoyacheng/legado-E](https://github.com/Luoyacheng/legado-E)
- 本轮核验提交：`21855a7bf901becfd1caba5cf30a3c84fd1533e1`
- LegadoHub 只生成兼容该客户端公开规则能力的书源，不要求修改或分发定制 APK。

## 登录

1. `loginUi` 的按钮回调从 `result` 读取输入。
2. `legado-E` 将表单值作为 Java `MutableMap<String, String>` 注入 Rhino，因此必须优先直接调用 `result.get("授权码")`。
3. 兼容读取顺序为 Java Map `get`、属性访问、其他 Map 探测、持久化登录信息。
4. 兑换成功后只把 Bearer token 写入 `source.putLoginHeader`。
5. 只有响应明确返回非空用户名及 token 才判定登录成功。
6. Reading 数据面未授权统一返回 `当前未登陆，请登陆后使用。`；管理员控制面继续使用原认证文案。

## 正文与评论

1. 章节 URL 继续使用 `data:*;base64` 和非空 `type` 传递真实正文 URL，这是 `AnalyzeUrl` 返回十六进制正文 URL 所需的通用机制。
2. 不使用 `qingci`、`ruleReview` 或客户端私有评论协议。
3. `ruleContent` 先请求现有章节接口，再请求同章节的 `/reviews`；后端评论仍统一经过 `Catalog -> 插件 chapter_reviews`。
4. 热评使用后端的 `matchedParagraphIndex` 和 `matchedParagraphCount` 定位聚合正文；字段缺失或越界时，客户端规则再做一次保守模糊匹配。
5. 每个有效热门段落后插入 SVG `<img>` 气泡，图片参数使用 `style: "TEXT"` 和 `click`；点击进入对应 `paragraphId` 的段评专页，该页面不显示作家说和本章说。
6. 章末追加 `style: "single"` 的本章评论入口，打开作家说、本章说、段评说及回复的现有 HTML 页面。
7. 目录 `updateTime` 只在 Reading 输出层格式化为 `YYYY-MM-DD HH:mm`；内部处理时间继续保留完整 ISO 时间。

## 搜索与第三方直读

1. Reading 搜索复用既有 `SearchJobService -> SearchCoordinator` 实时搜索链，不另写逐插件调度器。
2. `SearchCoordinator` 统一完成评分过滤、候选分组、缓存回退和 `visible` 共享书注入；Reading API 保持协调器给出的评分顺序，不再把共享书强制排在第三方结果之前。官方插件结果不进入 Reading 搜索。
3. 第三方详情、目录、正文和插件声明支持的评论继续经过 `Catalog -> PluginScheduler -> 插件`，不得绕过插件体系调用目标站接口。
4. 直读只接受启用、非官方且声明对应 capability 的插件；未知、禁用和官方插件 ID 一律返回 404。
5. 解码后的第三方 URL 必须使用 `http/https`，且主机属于插件 `domains/baseUrls` 声明；用户信息 URL、跨域 URL和本机/元数据地址不能借插件 ID 转发。
6. Reading 响应只保留书名、作者、封面、简介、分类、最新章节、字数和本地读取 URL等公开字段；`rawBookUrl`、`rawChapterUrl`、`debug`、Cookie、路径和来源内部信息不得返回。
7. 搜索允许写既有搜索任务、搜索缓存和书目缓存；不得创建用户订阅、聚合书、聚合章节任务或触发维护操作。

## 书源更新

1. `bookSourceUrl` 固定为稳定唯一值，更新时不得改变，否则 Reading 会把它识别成新书源。
2. 生成规则的版本与 `lastUpdateTime` 由代码发布版本统一维护，不读取可能滞后的运行时版本配置。
3. `legado-E` 只在相同 `bookSourceUrl` 下发现新的 `lastUpdateTime` 时标记更新；`bookSourceName` 中的版本号只用于展示。

## 评论弹窗授权

`legado-E` 的 `showBrowser` 不会自动继承书源 Bearer Header，因此采用以下流程：

1. 图片点击脚本先通过 `java.ajax(reviewUrl)` 携带书源登录 Header 获取首屏 HTML。
2. 再将 HTML、基础 URL、预注入脚本和固定高度配置传给 `java.showBrowser`。
3. 预注入脚本只为与当前页面同源且路径以 `/api/legado/chapter/` 开头的 `fetch` 请求附加 Bearer。
4. token 不进入 URL、不写入生成书源、不转发给外部头像或媒体域名，也不写入 WebView Cookie。
5. 评论内部链接通过同一受限 `fetch` 桥加载，保持分页和回复入口可用。
6. 弹窗高度固定为屏幕高度的 `78%`，不随评论数量变化。

## 禁止项

- 禁止在 APP 官方插件中回退 Web 正文；跨源回退仍由 LegadoHub 处理。
- 禁止评论绕过插件体系直接调用站点接口。
- 禁止把授权 token 放进查询参数、HTML、日志或生成的书源 JSON。
- 禁止为评论另建客户端专用后端旁路接口。
- 禁止把 Bearer 附加到非同源或非章节评论路径。

## 验证边界

- 自动验证覆盖生成规则、Reading 401 契约、评论 API、安全矩阵和 JS 执行烟测。
- Android 真机上的导入、授权输入、分页布局、气泡点击和弹窗手势仍属于发布前人工验收。
