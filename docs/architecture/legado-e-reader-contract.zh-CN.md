# `legado-E` 阅读端契约

## 基准

- 定制客户端：[XziXmn/legado-X](https://github.com/XziXmn/legado-X)，从 `legado-E` 同步上游能力。
- `chapterComment` 是通用书源契约，不得依赖 LegadoHub 或起点专有类型；评论能力只面向支持该协议的定制客户端。
- 定制能力默认只在 `legado-X` 分支维护，不向上游提交。

## 登录

1. `loginUi` 的按钮回调从 `result` 读取输入。
2. `legado-E` 将表单值作为 Java `MutableMap<String, String>` 注入 Rhino，因此必须优先直接调用 `result.get("授权码")`。
3. 兼容读取顺序为 Java Map `get`、属性访问、其他 Map 探测、持久化登录信息。
4. 兑换成功后只把 Bearer token 写入 `source.putLoginHeader`。
5. 只有响应明确返回非空用户名及 token 才判定登录成功。
6. Reading 数据面未授权统一返回 `当前未登陆，请登陆后使用。`；管理员控制面继续使用原认证文案。

## 正文与评论

1. 章节 URL 继续使用 `data:*;base64` 和非空 `type` 传递真实正文 URL，这是 `AnalyzeUrl` 返回十六进制正文 URL 所需的通用机制。
2. 不使用 `qingci`、`ruleReview` 或站点专有客户端协议；定制客户端只消费通用 `chapterComment` v2 数据。
3. 定制客户端通过 `chapterComment.url/data/action` 请求同章节的 `/reviews`；普通客户端不显示评论入口。后端评论仍统一经过 `Catalog -> 插件 chapter_reviews`。
4. 热评使用后端的 `matchedParagraphIndex` 和 `matchedParagraphCount` 定位聚合正文；字段缺失或越界时，客户端规则再做一次保守模糊匹配。
5. 段评按聚合正文中的真实段落锚点绘制为“小对话气泡 + 数字”；视觉尺寸跟随正文画笔并设置上下限，点击热区独立保持可触达尺寸。书源只能选择受支持的显示预设，不能注入原生布局。
6. 页热评由客户端在真实分页后按当前页段落聚合，显示在阅读页顶部标题行；下拉打开当前页热门评论集合，集合页不显示作家说和本章说。
7. 章末先直接显示不可点击的“作家说”补充卡片，再追加全宽“本章说 / N 条评论”入口。本章说优先显示 `chapterEndHot` 的 1 至 3 条有效摘要，不足时按顺序回退 `chapterEnd`；v2 只使用 `previews` 数组。点击本章说后的 HTML 页面只显示本章说、段评说及其回复，作家说不再作为弹窗 Tab。
8. 原生入口统一使用 `ReadBookConfig.textColor`、阅读字体和标题/正文画笔比例适配日间、夜间及墨水屏。
9. 原生段评和页热评只能使用完成排版后的 `TextPage`/段落投影定位；不支持 v2 的客户端不显示评论，禁止用正文图片、负边距或伪绝对定位模拟入口。
10. `legado-X` 会预加载当前章及相邻章节的正文和评论摘要。每次执行都必须由该章自己的 `contentUrl` 派生评论地址，禁止用全局状态猜测当前章；`/reviews` 摘要与热段预览会随正文预加载，完整段评、本章说后续页和回复只在用户点击后通过插件扩展分页加载。
11. 目录 `updateTime` 只在 Reading 输出层格式化为 `YYYY-MM-DD HH:mm`；内部处理时间继续保留完整 ISO 时间。

## 搜索与第三方直读

1. Reading 搜索复用既有 `SearchJobService -> SearchCoordinator` 实时搜索链，不另写逐插件调度器。
2. `SearchCoordinator` 统一完成第三方结果的评分过滤、候选分组和缓存回退；Reading API 保持第三方结果顺序，再按请求页追加 `visible` 共享书并按 `bookId` 去重。官方插件结果不进入 Reading 搜索。
3. Reading 的单次搜索请求只等待配置的首批结果窗口，不等待所有慢源或超时源结束；后台搜索任务可以继续完成，但不得让客户端请求耗时达到全局搜索超时。
4. 第三方详情、目录、正文和插件声明支持的评论继续经过 `Catalog -> PluginScheduler -> 插件`，不得绕过插件体系调用目标站接口。
5. 直读只接受启用、非官方且声明对应 capability 的插件；未知、禁用和官方插件 ID 一律返回 404。
6. 解码后的第三方 URL 必须使用 `http/https`，且主机属于插件 `domains/baseUrls` 声明；用户信息 URL、跨域 URL和本机/元数据地址不能借插件 ID 转发。
7. Reading 响应只保留书名、作者、封面、简介、分类、最新章节、字数和本地读取 URL等公开字段；`rawBookUrl`、`rawChapterUrl`、`debug`、Cookie、路径和来源内部信息不得返回。
8. 搜索允许写既有搜索任务、搜索缓存和书目缓存；不得创建用户订阅、聚合书、聚合章节任务或触发维护操作。

## 书源更新

1. 公网与内网**双源并存**：按导入时的 reading base Host 分叉身份。
   - 公网域名：`bookSourceUrl=LegadoHub`，显示名保持配置原名。
   - 局域网/私网 IP / localhost：`bookSourceUrl=LegadoHub-LAN`，显示名追加 `·内网`，分组追加 `内网`。
   - 同一网络身份内 `bookSourceUrl` 保持稳定，更新时不得在公网/内网之间互换，否则 Reading 会当成另一书源。
2. 生成规则版本由代码发布常量维护；`lastUpdateTime` 取发布常量与持久化配置文件修改时间的较大值，使评论入口设置变化能被 Reading 识别，同时避免无变化请求反复制造更新。
3. `legado-E` 只在相同 `bookSourceUrl` 下发现新的 `lastUpdateTime` 时标记更新；`bookSourceName` 中的版本号只用于展示。

## 评论弹窗授权

`legado-X` 使用来源隔离的原生评论弹窗，流程如下：

1. 客户端执行书源 `chapterComment.action`，只接受受限的 `sourceWebView` 动作。
2. 动作 URL 必须与摘要 URL 同源；客户端固定 DNS 解析结果并拒绝跨源跳转、私网元数据地址及凭据查询参数。
3. 首屏 HTML 由客户端使用书源 Header 和 Cookie 获取，再交给 `SOURCE_SCOPED` 模式的 `BottomWebViewDialog`。
4. 后续同源请求继续经过来源隔离的网络上下文；认证信息不会转发给外部头像或媒体域名。
5. token 不进入 URL、不写入生成书源、不写日志，也不写入外部域 Cookie。
6. 弹窗高度由客户端固定，不随评论数量变化。

## 禁止项

- 禁止在 APP 官方插件中回退 Web 正文；跨源回退仍由 LegadoHub 处理。
- 禁止评论绕过插件体系直接调用站点接口。
- 禁止把授权 token 放进查询参数、HTML、日志或生成的书源 JSON。
- 禁止为评论另建客户端专用后端旁路接口。
- 禁止把 Bearer 附加到非同源或非章节评论路径。

## 验证边界

- 自动验证覆盖生成规则、Reading 401 契约、评论 API、安全矩阵和 JS 执行烟测。
- Android 真机上的导入、授权输入、标题行热评布局、段评气泡、日夜主题切换、章末摘要、弹窗点击和下拉手势仍属于发布前人工验收。
