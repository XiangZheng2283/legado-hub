# 起点中文网（Web 协议版）

- Plugin ID: `qidian_com_web`
- Domain: `qidian.com`
- Base URL: `https://www.qidian.com`
- Auth: optional (Web 端手机验证码登录)
- Content: mixed / official
- Version: `0.1.7`

> 本插件基于 `m.qidian.com` Web 移动端协议实现，与 `qidian_com_app`（App 协议版）共享同一套私有扩展代码结构。

## 完整逆向工程文档

**所有API端点、数据结构、登录流程、解密机制详见：**

📄 [`reverse-engineering/docs/qidian-web-app-api-reference.md`](../../reverse-engineering/docs/qidian-web-app-api-reference.md)

📄 [`docs/reference-sources/official/qidian.com/qidian-com-reverse-engineering.md`](../../../docs/reference-sources/official/qidian.com/qidian-com-reverse-engineering.md)

## 本章说聚合规划

**本章说接入AI聚合书源的完整实施规划：**

📄 [`docs/superpowers/plans/2026-06-11-qidian-reviews-aggregate-plan.md`](../../../docs/superpowers/plans/2026-06-11-qidian-reviews-aggregate-plan.md)

## 当前实现状态

| 方法 | 状态 | 备注 |
|------|------|------|
| `auth_status` | ✅ | 检测Cookie字段 + 移动站用户中心探测；只有明确昵称/用户名或登录手机号才判定已登录；含 **懒续期（checkStatus）** |
| `prepare_login` | ✅ | 浏览器弹窗登录，6个cookieDomain |
| `after_login` | ✅ | 委托给auth_status |
| `search` | ✅ | m.qidian.com 移动端搜索，失效自动续期重试 |
| `detail` | ✅ | m.qidian.com 书籍详情，失效自动续期重试 |
| `toc` | ✅ | 完整目录，**`sS=1=免费, sS=0=VIP`**，失效自动续期重试 |
| `chapter` | ✅ | 免费章完整内容，VIP/限免章预览，失效自动续期重试 |
| `explore_groups` | ✅ | 排行榜+分类 |
| `explore` | ✅ | 结构化解析（按语义类名前缀匹配，不依赖哈希后缀） |
| `chapter_reviews` | ✅ | 路由到 `private/reviews.py`；公开兜底保持串行，入口文件不再自管并发 |
| `author_say` | ⚠️ | 已公开能力壳；优先尝试章节页字段，当前还不是稳定来源 |
| `chapter_say` | ✅ | 章末热评优先，后接普通章末评论 |
| `paragraph_say` | ✅ | 返回段评能力壳；当前热评能力弱于 App |
| `vip_chapter_preview` | ✅ | 返回预览内容与字数壳 |
| `vip_chapter_words` | ✅ | 返回章节字数壳 |
| `vip_unbought_chapters` | ✅ | 返回基于目录的 VIP 章节元信息壳 |
| **keepalive** | ✅ | `private/web_keepalive.py`：alk→checkStatus→刷新 ywguid/ywkey/ticket |

## 续期 / 保活机制

Web 端登录态为两层令牌结构：`alk`（15天长期）→ `ywguid/ywkey/ticket`（~45秒短期）。
插件通过 `private/web_keepalive.py` 自动刷新短期凭证：

- **懒触发**：每次 `auth_status` 调用时，若存在 `alk` 则主动跑一次 checkStatus。
- **运行时失效续期**：所有 HTTP 请求（search/detail/toc/chapter/explore/reviews）
  遇到 401/403/重定向到登录页时，自动尝试一次续期并重试。
- **alk 过期处理**：checkStatus 返回 `code=10521` 时，`auth_status` 返回
  `authStatus="expired"` + `requiredActions=["relogin"]`，提示用户重新登录。
- **不走 sublogin**：直接用 checkStatus 返回的 `ywGuid/ywKey/ticket` 字段写回
  cookie jar，无需 GET 302url（POC 已验证此路径足够）。

详见 `reverse-engineering/docs/qidian-web-login-keepalive-flow.md` §6。

## Reviews / 本章说现状说明

本章说属于**私有能力**，由私有包 `private/reviews.py` 实现。主插件 `source.py` 只负责路由与降级：

- **有 `private/reviews.py`**：`chapter_reviews()` 调用私有实现，走 `reviewsummary4m` + `reviewlist4m`
- **无私有包**：返回空结构 `{"paragraphs": {}, "chapterEnd": [], "summary": {}, "debug": {"error": "reviews private plugin not installed"}}`

宿主的 `PluginScheduler`、`Catalog` 和 `/api/legado/chapter/{id}/reviews` 已支持直接章节评论契约。共享聚合书目前不复制远端评论缓存，虚拟共享章节返回空评论结构；评论不属于订阅和正文发布关键路径。

当前还额外公开了以下宿主可统一调用的能力壳：

- `author_say`
- `chapter_say`
- `paragraph_say`
- `vip_chapter_preview`
- `vip_chapter_words`
- `vip_unbought_chapters`

其中 Web 版 `author_say` 和部分 VIP 元信息目前仍属于降级能力，不应和 App 版增强能力等同看待。

## Fixture Smoke

```powershell
.venv\Scripts\python source-plugin\WEB-plugin\smoke\validate_offline_regressions.py
python sync-to-legado-hub.py --variant WEB-plugin
..\legado-hub\.venv\Scripts\python ..\legado-hub\backend\scripts\validate_source_plugin.py --plugin ..\legado-hub\plugins\sources\official\qidian_com_web
```

离线回归锁住严格登录身份、手机号格式、Cookie 解析与 Web 章节契约；2026-07-16 离线回归和同步后宿主 validator 均通过。
