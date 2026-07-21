# LegadoHub 书源插件协议

> **给 AI / 开发者：** 本文档定义了书源插件 API。实现时请不要自行发明接口。如果某个站点需要协议未覆盖的行为，先向本文档添加向后兼容的扩展，再实现。

**协议版本：** `1.0`

**运行时归属：** LegadoHub 核心。

**插件归属：** 站点特定的适配代码。

---

## 核心原则

书源插件描述一个站点或同族站点的适配方式，而不是控制引擎。

## 宿主层边界

重构后，以下职责明确归属宿主层，插件不得绕过或重复实现：

1. **配置集中化**：运行时配置统一由宿主从 `backend/config/app_config.json` 加载。旧的 `backend/config/source_pool.json`、`backend/config/aggregate_source.json` 和 `backend/data/ai_provider.json` 已废弃。
2. **Cookie 文件归属宿主**：Cookie 由宿主统一保存到 `backend/config/cookies/<plugin_id>.json`。插件不再读取或写入自身目录内的 `Cookie.json`。宿主只负责不透明的加载、保存和清除；JSON 载荷结构由插件自行定义。
3. **认证状态实时探测**：登录/认证状态不持久化到数据库。`auth_status` 由插件实时探测。宿主可以缓存 Cookie 载荷文件，但是否有效由插件判定。
4. **搜索事件/插件健康/运行时代理状态不持久化**：搜索过程事件由 `SearchCoordinator` 在内存中维护；进程日志与调试数据写入 `backend/runtime/logs/`，不进入数据库。
5. **代理策略收紧**：默认直连。仅当插件声明 `proxy.mode: always`，或 `proxy.mode: auto` 且 `proxy.required: true` 且宿主配置 `proxy.allowAutoRetry: true` 时才使用代理。`auto` 不再表示“每个源都先尝试代理”。
6. **搜索调度归属宿主**：插件不应假设搜索过程事件会被持久化，也不应自行调度搜索重试。

插件可以：

- 构造站点特定的 URL。
- 解析 HTML/JSON/API 响应。
- 生成站点特定的签名或 token。
- 解密章节载荷。
- 描述认证要求。
- 描述站点族域名配置，并在解析时动态选择。
- 通过 `ctx` 请求受控的浏览器/手动登录协助。

插件不可以：

- 控制书源级并发。
- 创建不受管理的后台线程。
- 创建绕过 `ctx` 的全局 HTTP 会话。
- 拥有自己的重试/代理/缓存策略。
- 塑造 Reading/Legado 聚合书源 JSON。
- 导入或依赖 `engine-jvm`、`app.legado_engine` 或 `app.engine`。

## 目录结构

```text
plugins/sources/<plugin_id>/
  metadata.yaml
  source.py
  README.md
  requirements.txt       # 可选；私有项目，按需安装
  tests/
    smoke.yaml
  skills/
    SKILL.md             # 可选的插件特定适配笔记
```

第一阶段允许按需安装依赖。新增的后端依赖记录在 `backend/requirements.txt`，前端依赖记录在 `frontend/package.json`，插件本地依赖可放在 `plugins/sources/<plugin_id>/requirements.txt`。

## metadata.yaml

必填字段：

```yaml
contractVersion: "1.0"
id: qidian
name: 起点中文网
version: 0.1.0
type: source
domains:
  - qidian.com
baseUrls:
  - https://www.qidian.com
capabilities:
  - search
  - detail
  - toc
  - chapter
auth:
  mode: optional
  loginUrl: https://www.qidian.com
  accountRequiredFor:
    - paid_chapter
  cookieDomains:
    - qidian.com
  sessionCheck:
    url: https://www.qidian.com
    successText:
      - 书架
content:
  access: mixed
  paid: supported_after_login
tags:
  - official
  - login
  - paid
  - json-api
```

必填字段规则：

- `contractVersion`：第一阶段必须为 `"1.0"`。
- `id`：稳定的 ASCII 标识符，在所有插件中唯一。
- `name`：中文显示名，尽可能使用中文。
- `version`：插件版本，采用类 SemVer 格式（如 `0.1.0`）。解析规则、域名配置或访问策略变更时都需要升级版本。
- `type`：必须为 `source`。
- `domains`：插件允许或预期访问的域名。
- `baseUrls`：站点或站点族的入口 URL。
- `capabilities`：`search`、`detail`、`toc`、`chapter`、`explore`、`auth` 的子集。
- `auth.mode`：`none`、`optional`、`required`、`manual` 之一。
- `content.access`：`free`、`paid`、`mixed`、`unknown` 之一。
- `tags`：运营提示标签。

`explore` 涵盖排行榜、分类、热榜、完本榜等发现入口。仅允许官方/授权书源使用。当书源带有 `official` 标签或 `content.sourceRole: official` 时被视为官方书源。普通镜像/爬虫书源只能暴露 `search`、`detail`、`toc`、`chapter`，即使站点有这些页面也不得声明排行榜或分类能力。

可选字段：

```yaml
author: Yunwei
priority: 50
enabled: true
language: zh-CN
rateLimit:
  perHostConcurrency: 1
  minIntervalMs: 800
proxy:
  mode: auto        # never / auto / always
  required: false   # true / false
browser:
  mode: optional    # none / optional / required
  reason: cloudflare
accessStrategy:
  search: search_provider
  detail: stealth_http
  toc: stealth_http
  chapter: stealth_http
searchProvider:
  providerOrder:
    - duckduckgo_ddgs
    - bing_html
    - google_html
  targetDomain: www.example.com
  urlPatterns:
    - /book/\d+\.htm
domainProfiles:
  - id: mobile
    baseUrl: https://m.example.com
    domains:
      - m.example.com
    role: mobile
    fallback: true
  - id: desktop
    baseUrl: https://www.example.com
    domains:
      - www.example.com
    role: desktop
    fallback: true
sourceSeed:
  type: so-novel
  upstreamId: qidian
  upstreamFile: bundle/rules/main.json
  upstreamCommit: ""
```

`author` 是控制台展示的插件维护者署名，不是 `search()` 或 `detail()`
返回的书籍作者。

`enabled`：加载后默认是否启用。控制台可以按书源单独开关。

`proxy.mode`：
- `never`：永不使用运行时配置的代理（默认行为）。
- `auto`：仅当 `proxy.required: true` 且宿主配置 `proxy.allowAutoRetry: true` 时才允许代理；不满足条件时保持直连。
- `always`：始终通过配置的代理路由。

`proxy.required`：若为 `true`，表示该书源通常需要代理，但是否启用仍由 `proxy.mode` 与宿主 `proxy.allowAutoRetry` 共同决定。

`browser.mode`：
- `none`：不使用浏览器渲染。
- `optional`：先尝试 HTTP/stealth，遇到挑战或 JS 渲染页面时再 fallback 到 `ctx.access.browser`。
- `required`：始终使用 `ctx.access.browser.fetch_*`。

`browser.reason`：简短诊断标签，如 `cloudflare`、`js_rendered`、`login`。

`accessStrategy` 是每个生命周期阶段可选的最终运行路由。合法路由包括 `http`、`stealth_http`、`tls_impersonate`、`search_provider`、`headless_browser`、`remote_browser`、`api`、`feed`、`local_file`。完成的书源应声明预期路由，而不是保留隐藏的永久 fallback 链。

`searchProvider` 是可选的搜索引擎代理配置。DuckDuckGo 使用 DDGS 库提供方，Bing 和 Google 使用 HTTP 结果页提供方。声明的提供方并行执行，运行时不添加隐式 fallback。单个书源插件只需将返回的命中结果映射为书源结果对象。

## source.py 类

每个插件导出一个 `Source` 类。

必填类字段：

```python
class Source:
    id = "qidian"
    name = "起点中文网"
    contract_version = "1.0"
    last_modified = "2026-06-10"
```

- `id`：稳定的 ASCII 标识符，必须与目录名和 `metadata.yaml` 一致。
- `name`：中文显示名。
- `contract_version`：第一阶段必须为 `"1.0"`。
- `last_modified`：ISO-8601 日期（`YYYY-MM-DD`），表示插件逻辑最后被验证或更新的时间。控制台 UI 会显示此字段以便运营人员发现陈旧书源。

生命周期方法在 metadata capabilities 中声明时必须为 async：

```python
async def search(self, ctx, keyword: str, page: int) -> list[dict]:
    ...

async def detail(self, ctx, book_url: str) -> dict:
    ...

async def toc(self, ctx, toc_url: str) -> list[dict]:
    ...

async def chapter(self, ctx, chapter_url: str) -> dict:
    ...

async def explore_groups(self, ctx) -> list[dict]:
    ...

async def explore(self, ctx, group_id: str | None = None, page: int = 1) -> list[dict]:
    ...
```

`explore` 是书源发现生命周期，覆盖 Reading/Legado 的 `enabledExplore`、`exploreUrl` 和 `ruleExplore`，例如排行榜、分类页、完本榜、新书架。声明 `explore` 的插件必须同时提供 `explore_groups` 和 `explore`，加载器会验证这对方法。

可选的认证方法：

```python
async def auth_status(self, ctx) -> dict:
    ...

async def prepare_login(self, ctx) -> dict:
    ...

async def after_login(self, ctx) -> dict:
    ...
```

第一阶段不要要求官方书源登录，除非用户明确选择该书源支持登录。第一阶段应定义协议和控制台 UI 挂钩。

## Smoke Fixture 协议

每个插件应提供 `tests/smoke.yaml`。常规测试和控制台 smoke 运行默认使用本地 fixture 文件；实时网络检查必须显式选择加入。

```yaml
keyword: 凡人修仙传
fixtures:
  search:
    url: https://example.com/search?q=%E5%87%A1%E4%BA%BA
    file: search.html
  detail:
    url: https://example.com/book/1/
    file: detail.html
  toc:
    url: https://example.com/book/1/
    file: toc.html
  chapter:
    url: https://example.com/book/1/1.html
    file: chapter.html
expect:
  search:
    minResults: 1
    firstName: 凡人修仙传
  detail:
    name: 凡人修仙传
    author: 忘语
    hasTocUrl: true
  toc:
    minChapters: 1
    firstTitleContains: 第
  chapter:
    minContentLength: 20
    titleContains: 第
```

Fixture 文件放在插件目录下的 `tests/fixtures/` 中。`fixtures.*.url` 中的 URL 必须与插件解析器请求的 URL 完全匹配。Fixture 运行器用 fixture 请求替换网络请求，但插件仍只调用 `ctx.access.http.fetch_text`、`ctx.access.http.fetch_json` 或 `ctx.access.http.fetch_bytes`。

Smoke 结果格式：

```python
{
    "pluginId": "xbiqugu_la",
    "mode": "fixture",
    "pass": True,
    "stages": {
        "search": {"status": "ok", "count": 1, "elapsedMs": 3},
        "detail": {"status": "ok", "elapsedMs": 2},
        "toc": {"status": "ok", "count": 2, "elapsedMs": 2},
        "chapter": {"status": "ok", "contentLength": 120, "elapsedMs": 1},
    },
    "errors": [],
    "diagnostics": [],
}
```

Fixture smoke 错误使用常规插件错误码外加：

- `SMOKE_CONTRACT_ERROR`：fixture 输出与声明的预期不匹配。
- `SMOKE_FIXTURE_MISSING`：smoke 规范或 fixture 文件缺失或格式错误。

## 标准数据结构

搜索结果：

```python
{
    "sourceId": "qidian",
    "name": "书名",
    "author": "作者",
    "bookUrl": "https://...",
    "coverUrl": "https://...",
    "intro": "简介",
    "kind": "分类/状态/标签",
    "lastChapter": "最新章节",
    "wordCount": "123万字",
    "score": 0.0,
    "extra": {},
}
```

搜索结果的完整性是书源插件的责任，不是调度器的责任。插件应尽可能直接从搜索页面解析标准字段。如果搜索页面不暴露 `lastChapter`、`author`、`coverUrl`、`intro`、`kind`、`wordCount` 或 `updateTime`，插件自身的 `search()` 方法必须使用同一书源的 `detail()` 解析器为前几个精确或高置信度匹配补全缺失字段。运行时调度器不得静默补全行业字段，因为单源测试需要暴露书源特定的解析器缺陷。

`kind` 保留给 Reading 在完整搜索页上渲染为徽章的书籍元数据：分类、状态、标签、受众、评分或其他稳定的图书属性。不要把书源显示名放进 `kind`，也不要返回通用提供方标签如 `搜索提供器`。LegadoHub 的聚合书源通过 Reading 面向的字段（如 `readingSourceName` 和 `readingLastChapter`）暴露书源显示，同时保留 `kind` 用于分类/状态/字数类元数据。

当聚合书源返回结果时，运行时可能会将原始 `sourceName` 写入 `kind`（例如 `"笔趣阁22 / 玄幻"`），以便 Reading 显示每条结果的来源书源。书源插件不应预先用书源名填充 `kind`；请将其留给运行时，或仅用于真实的分类/状态元数据。

Reading 搜索页应在不先打开详情的情况下获得足够数据：`name`、`author`、`coverUrl`、`intro`、`kind`、`lastChapter` 和 `wordCount` 应在书源暴露它们时被填充。如果搜索页缺少最新章节、分类、字数或连载/完本状态，但详情页包含它们，插件必须通过调用自身的 `detail()` 解析器来丰富返回的搜索候选。这种丰富属于书源插件，而不是调度器。

详情丰富应保持书源本地化和有界：

- 仅丰富已有稳定 `bookUrl` 的候选。
- 优先精确标题匹配，再考虑宽泛搜索结果。
- 使用短超时或捕获失败，避免详情页失败抹掉有效搜索结果。
- 只填充空字段；不要覆盖更好的搜索页值，除非书源有明确理由。
- 在有用时通过 `extra.detailEnriched = true` 标记书源本地丰富。

对于不稳定的搜索，书源插件应按以下顺序降级：先正常 HTTP 搜索，然后在配置和可用时使用浏览器支持的获取，再使用站点本地排行榜/分类 fallback 来定位请求标题。如果所有稳定路由都失败，返回空列表并附带诊断，而不是伪造元数据。

常见的实现模式是提供一个私有的 `_search_from_explore(ctx, keyword)` 方法，扫描站点的排行榜、分类或最近更新页面，查找书名包含关键词的书籍。主 `search()` 方法先尝试主搜索端点，当初级端点返回无结果或失败时回退到此辅助方法。此 fallback 是插件本地的，不需要外部搜索引擎代理。

发现分组：

```python
{
    "sourceId": "qidian",
    "groupId": "rank_all",
    "title": "总排行榜",
    "url": "https://...",
    "kind": "rank",          # rank/category/full/new/other
    "pageable": True,
    "profile": "mobile",     # 可选域名配置 id
    "extra": {},
}
```

发现项：

```python
{
    "sourceId": "qidian",
    "sourceName": "起点中文网",
    "name": "书名",
    "author": "作者",
    "bookUrl": "https://...",
    "coverUrl": "https://...",
    "intro": "简介",
    "kind": "分类/状态/榜单",
    "lastChapter": "最新章节",
    "wordCount": "123万字",
    "rank": 1,
    "groupId": "rank_all",
    "groupTitle": "总排行榜",
    "extra": {},
}
```

发现项故意复用搜索结果形状，以便相同的 detail/toc/chapter 读取器验证可以在发现或搜索后运行。

书籍详情：

```python
{
    "sourceId": "qidian",
    "name": "书名",
    "author": "作者",
    "bookUrl": "https://...",
    "coverUrl": "https://...",
    "intro": "简介",
    "kind": "分类/状态/标签",
    "lastChapter": "最新章节",
    "wordCount": "123万字",
    "updateTime": "2026-06-08",
    "tocUrl": "https://...",
    "authRequired": False,
    "extra": {},
}
```

书籍详情应尽可能完整，因为 Reading/Legado 直接通过 `ruleBookInfo` 映射这些字段。`name`、`author`、`bookUrl` 和 `tocUrl` 是基线。`coverUrl`、`intro`、`kind`、`lastChapter`、`wordCount` 和 `updateTime` 在 HTML/JSON 或稳定 meta 标签中可见时都应填充。书源特定但可能有用的值（如 `status`、原始标签或评分）应放在 `extra` 下，而不是替换标准字段。插件应清理 `intro` 中的 SEO 关键词尾巴、重复标签和站点导航杂项。

目录项：

```python
{
    "sourceId": "qidian",
    "index": 1,
    "title": "第1章",
    "chapterUrl": "https://...",
    "updateTime": "",
    "isVip": False,
    "isLocked": False,
    "extra": {},
}
```

`toc()` 必须按**正常阅读顺序**返回章节（第1章在前，最新章节在后）。如果站点按倒序排列（最新在前），插件必须在返回前反转列表。运行时和阅读客户端不会尝试自动检测或修复章节顺序。

`toc()` 必须返回站点暴露的完整可读目录。许多小说站点只渲染一个短的静态目录（包含开头几章和最近几章），然后通过 AJAX/API 端点、分页或"加载更多"脚本加载完整目录。插件必须优先使用完整目录端点，并将静态头/尾预览仅作为 fallback。如果没有完整目录，插件应返回最佳可用列表并跟踪限制。不要将预览列表报告为成功的完整目录。

目录解析器应按章节 URL 去重，移除 `#` 和导航链接，并在站点可在正常/倒序之间切换时按显式章号排序。有效的解析器应保留作为实际阅读顺序一部分的序言/额外章节，但应排除独立的"最新更新"、推荐和相关书籍块。

在编写 `toc()` 或 `chapter()` 的选择器之前，主动检查页面是否有 JSON/AJAX/get 端点。常见信号包括脚本变量、包含 `api`、`ajax`、`chapterlist`、`chapters`、`content`、`reader` 的网络路径，或移动/AMP 端点。优先使用稳定的 API/AJAX 响应而不是 HTML 解析获取完整目录和正文内容；HTML 选择器仅作为文档化的 fallback。如果端点探测返回 404/500/挑战页面，将探测结果保留在验证笔记或 `ctx.trace()` 中，以便下一次适配迭代不会重复盲目猜测。

重复镜像框架常出现相同的陷阱：

- "最新章节"预览出现在真实目录之前。按区块边界解析，而不是仅使用宽泛选择器如 `#list a`。
- 某些 HTML 结构为 `<a><dd>title</dd></a>` 而不是 `<dd><a>title</a></dd>`。在假设框架形状之前，针对实时 DOM 验证。
- 分页目录可能使用兄弟 URL 如 `/book/123-2.html`，而不是子 URL 如 `/book/123/123-2.html`。跟随实际的 `下一页` 链接。
- 不要仅按章号去重。`番外`、`完结感言` 等无编号章节必须保留。
- 章节页面可能包含短的广告 `<p>` 加真实文本节点。不要让"第一个 `<p>` 获胜"的逻辑丢弃正文。
- 如果来源页面本身返回缺失、串章、混章正文，插件应跟踪或为该章节返回空，而不是将明显被污染的内容缓存为有效文本。解析器不得伪造缺失正文。

章节内容：

```python
{
    "sourceId": "qidian",
    "title": "第1章",
    "chapterUrl": "https://...",
    "content": "正文",
    "format": "text",
    "authRequired": False,
    "isPaid": False,
    "extra": {},
}
```

`format` 为 `"text"` 时表示以 `\n\n` 分隔的纯文本段落。插件应通过 `ctx.clean_html()` 传递原始章节 HTML 以移除脚本、广告和站点导航，然后再返回。除非下游消费者明确要求，否则不要返回原始 HTML 并使用 `format: "html"`。

章节正文最佳实践：

1. **保留段落** — 将 `<br>` 转换为 `\n`，将 `<p>` 标签提取为以 `\n\n` 连接的段落。如果站点使用带 `<br>` 的裸文本节点，在替换 `<br>` 后按空行分割。
2. **合并分页** — 许多章节页面被拆分为 `_1.html`、`_2.html` 等。仅在 URL stem 匹配原始章节时跟随 `下一章` / `下一页` / `#next_url`；指向下一章时停止。
3. **移除页码标记** — 从标题中去掉 `(1/3)`、`(2/3)`、`（第2页）`。
4. **积极清洗广告** — 移除 `script/style/iframe/ins/nav/header/footer`、广告容器（`.contentadv`、`.bottom-ad`、 `#txtright`）以及包含"最新网址"、"加入书签"、"返回目录"、"本章结束"或站点名的短文本节点。
5. **将空/污染内容视为无效** — 不要返回或缓存明显损坏的章节。返回空字符串并跟踪失败。
6. **优先使用 API/AJAX/get 端点**。常见信号是脚本变量、包含 `api`、`ajax`、`chapterlist`、`chapters`、`content`、`reader` 的网络路径，或移动/AMP 端点。在 `ctx.trace()` 中记录任何成功或失败的探测，以便下一次适配迭代不会重复盲目猜测。

认证状态：

```python
{
    "sourceId": "qidian",
    "authenticated": False,
    "accountName": "",
    "expiresAt": "",
    "message": "未登录",
    "requiredActions": ["manual_login"],
}
```

登录准备：

```python
{
    "sourceId": "qidian",
    "mode": "manual_browser",
    "loginUrl": "https://www.qidian.com",
    "instructions": "在打开的浏览器中完成登录，然后回到后台点击检测登录状态。",
    "cookieDomains": ["qidian.com"],
}
```

## 运行时上下文 API

网络（所有访问都通过 `ctx.access` 子门面）：

```python
# 直接 HTTP（httpx / curl_cffi）
await ctx.access.http.fetch_text(url, method="GET", params=None, data=None, json=None, headers=None, timeout=None, impersonate=None, proxy=True)
await ctx.access.http.fetch_json(url, method="GET", params=None, data=None, json=None, headers=None, timeout=None, impersonate=None, proxy=True)
await ctx.access.http.fetch_bytes(url, method="GET", params=None, data=None, json=None, headers=None, timeout=None, impersonate=None, proxy=True)

# Stealth HTTP — 浏览器级 headers + TLS 指纹伪装（默认 chrome120）
await ctx.access.stealth.fetch_text(url, method="GET", params=None, data=None, json=None, headers=None, timeout=None, impersonate=None, proxy=True)
await ctx.access.stealth.fetch_json(url, method="GET", params=None, data=None, json=None, headers=None, timeout=None, impersonate=None, proxy=True)
await ctx.access.stealth.fetch_bytes(url, method="GET", params=None, data=None, json=None, headers=None, timeout=None, impersonate=None, proxy=True)

# 浏览器渲染 — Playwright 无头 Chromium
await ctx.access.browser.fetch_text(url, method="GET", headers=None, data=None, wait_ms=2500, timeout_ms=90000)
await ctx.access.browser.fetch_json(url, method="GET", headers=None, data=None, wait_ms=2500, timeout_ms=90000)
await ctx.access.browser.fetch_bytes(url, method="GET", headers=None, data=None, wait_ms=2500, timeout_ms=90000)

# 搜索引擎代理 — DDGS / Bing / Google
await ctx.access.search_provider(keyword, target_domain=..., url_patterns=..., provider_order=...)
```

`ctx.access.http` 是普通请求的默认路径。

`ctx.access.stealth` 添加浏览器指纹 headers 和 TLS 伪装（使用 `curl_cffi`）。插件应在站点阻止裸 HTTP 客户端时使用此层。

`ctx.access.browser` 使用 Playwright Chromium 进行完整浏览器渲染。仅在需要 JavaScript 执行或复杂挑战处理时使用。运行时拥有进程生命周期、代理、超时、配置清理和挑战分类。插件不得启动自己的 Playwright 实例。

各层之间**没有自动 fallback**。插件必须显式选择与需求匹配的访问层。

解析：

```python
ctx.select(html_or_node, selector)
ctx.text(html_or_node, selector=None)
ctx.html(html_or_node, selector=None)
ctx.attr(html_or_node, selector, name)
ctx.json_path(data, path)
ctx.regex(text, pattern, group=1, default="")
```

工具：

```python
ctx.urljoin(base, href)
ctx.clean_html(html)
ctx.clean_text(text)
ctx.decode_text(content_bytes, charset=None)
ctx.trace(stage, url="", message="", data=None)
ctx.cache_get(key)
ctx.cache_set(key, value, ttl_seconds)
```

文本转换（繁简中文互转）：

```python
ctx.to_simplified(value)
ctx.to_traditional(value)
```

对于提供繁体中文的站点（如 `69shuba.tw`、`twkan.com`），插件**必须**应用双向转换：

1. **输入侧** — 搜索前将用户关键词转为繁体：
   ```python
   search_keyword = ctx.to_traditional(keyword)
   html = await ctx.access.http.fetch_text(
       f"{self.base_url}/search?kw={search_keyword}"
   )
   ```
2. **输出侧** — 将站点返回的每个文本字段转为简体：
   ```python
   return {
       "name": ctx.to_simplified(name),
       "author": ctx.to_simplified(author),
       "intro": ctx.to_simplified(intro),
       "kind": ctx.to_simplified(kind),
       "lastChapter": ctx.to_simplified(last),
       # ...
   }
   ```

所有面向用户的字符串字段（`name`、`author`、`intro`、`kind`、`lastChapter`、`title`、`content`、`groupTitle` 等）都必须经过 `ctx.to_simplified()`。URL、ID、时间戳等内部值不应转换。

认证/会话：

```python
ctx.cookies.get(domain, name=None)
ctx.cookies.set(domain, cookie)
ctx.cookies.clear(domain=None)
await ctx.auth_status()
await ctx.request_manual_login(login_url, cookie_domains, message="")
```

`ctx.cookies` 是宿主提供的 Cookie 载荷抽象，宿主负责将载荷持久化到 `backend/config/cookies/<plugin_id>.json`。插件不应直接读写插件目录内的 `Cookie.json`。

`auth_status` 由插件实时探测；登录/认证状态不写入数据库。宿主可以缓存 Cookie 文件，但 Cookie 是否有效由插件自行判断。

浏览器/手动登录支持是受控的运行时功能。插件可以请求它，但控制台/后端决定如何呈现和执行。

## 错误码

插件应抛出或返回结构化失败，核心会规范化为：

- `PLUGIN_VALIDATION_ERROR`
- `PLUGIN_RUNTIME_ERROR`
- `PLUGIN_TIMEOUT`
- `FETCH_NETWORK_ERROR`
- `FETCH_HTTP_4XX`
- `FETCH_HTTP_5XX`
- `PARSE_EMPTY`
- `PARSE_ERROR`
- `AUTH_REQUIRED`
- `LOGIN_REQUIRED`
- `PAID_CONTENT_REQUIRED`
- `BROWSER_REQUIRED`
- `CLOUDFLARE_REQUIRED`
- `RATE_LIMITED`
- `UNSUPPORTED_SOURCE`

不要将认证或付费需求隐藏为解析失败。

## 官方与登录型书源

官方书源如起点、番茄、七猫、QQ 阅读可能需要登录、cookie、反 bot 检查、付费章节访问或移动/API 签名。

插件协议通过以下方式支持它们：

- `auth` metadata。
- `auth_status`。
- `prepare_login`。
- `after_login`。
- `ctx.cookies`。
- `ctx.request_manual_login`。
- `authRequired`、`isVip`、`isLocked`、`isPaid` 输出字段。
- 控制台 UI 动作："打开登录"、"检测登录状态"、"清除 Cookie"、"重试章节"。

### 浏览器挑战绕过

Cloudflare 和类似的浏览器挑战被视为需要绕过的源失败。当 `ctx.access.http.fetch_text/json/bytes` 或插件代码抛出 `CLOUDFLARE_REQUIRED` / `BROWSER_REQUIRED` 时，调度器会记录一个规范化的失败，并附带 `extra.bypassRequired = true`，然后在当前请求中跳过该书源。

运行时不再创建浏览器挑战会话、验证页面、Reading 回调 URL 或 Cookie 往返 API。插件可以声明 `browser.mode: required` 并可以抛出结构化错误，但它不得拥有浏览器进程控制、重试调度、并发、超时、代理、缓存或 cookie 持久化策略。

浏览器模拟仍然是后端拥有的能力，用于可维护的绕过策略、stealth HTTP、搜索引擎代理和受控渲染。它不是面向用户的手动验证环境。

有些站点正常阅读就需要浏览器上下文。对于这些站点，metadata 可以声明 `browser.mode: required`，插件代码可以使用 `ctx.access.browser.fetch_text(...)`。运行时给这些书源单独的 `browser_source_timeout_seconds` 预算，而普通 HTTP 书源保持正常的 `source_timeout_seconds` 预算。

对于搜索，遇到挑战页面或不稳定的直接 HTML 时，书源插件应按以下顺序降级，除非书源文档化了更好的站点特定路由：

1. 通过声明的访问层进行正常书源搜索。
2. 当检测到挑战或 JavaScript 渲染的结果页时，对同一站点搜索 URL 进行浏览器渲染搜索。
3. 站点本地发现 fallback，如站点自身的排行榜、分类、最近更新或完本页面。
4. 仅作为最终书源拥有的 bypass 使用外部搜索引擎代理，且仅在插件显式声明并映射该提供方时。

HTTP 200 响应仍然可能是挑战页面。插件在将解析失败视为空结果之前，应检查返回的 HTML 中是否有 Cloudflare/Turnstile/浏览器挑战标记。

第一阶段要求：

- 实现协议和控制台 UI 挂钩。
- 不要求官方书源的付费内容提取正常工作。
- 如果创建了官方书源插件，它可以先支持免费元数据的 search/detail/toc，对锁定章节返回 `AUTH_REQUIRED` 或 `PAID_CONTENT_REQUIRED`。

## 多域名与代理书源规则

插件代表一个站点族，而不一定是一个主机名。当解析规则基本相同且插件可以安全地从一个基础 URL fallback 到另一个时，它可以在一个插件中保留多个镜像或历史域名。

规则：

- 如果单个域名/配置无法到达，插件可以尝试同一生命周期方法的其他声明域名配置。
- Fallback 是站点特定的 URL 构造和解析的本地化操作。全局并发、超时、重试、代理、缓存和健康评分仍是运行时的责任。
- 如果移动端和桌面端域名有 substantially 不同的 DOM/API 结构，优先拆分为独立插件或内部清晰分离的配置。不要在一个难以维护的方法中混合两个无关的解析器形状。
- 如果两个域名共享品牌但验证行为和 DOM 不同，如 `www.69shuba.com` 和 `69shuba.tw`，它们应是独立插件而不是一个多域名插件。
- `metadata.proxy.required: true` 标记通常应使用运行时代理路径的书源。插件仍只调用 `ctx.fetch_*`；不得创建自己的代理客户端。
- `metadata.proxy.mode` 可以是 `auto`、`always` 或 `never`。运行时代码决定如何用配置的代理 URL 来遵守它。

带有 `explore` 的书源的实时验收路径为：

1. `explore_groups`
2. `explore` 挑选一本发现/排行榜书籍
3. `detail`
4. `toc`
5. `chapter`
6. 使用发现的书籍名进行 `search`
7. 从搜索候选重复 `detail -> toc -> chapter`

## 兼容性策略

协议是版本化的。

- 第一阶段只接受 `contractVersion: "1.0"`。
- 未来引擎可以添加可选字段。
- 现有字段不得在没有迁移的情况下重命名。
- 新的生命周期方法必须是可选的。
- 添加新能力时，旧插件应继续工作。

聚合 Reading/Legado 书源仍然是一个兼容性外壳。它可以通过宿主受控路由展示启用的第三方插件搜索与直读结果，但不得暴露插件内部 URL、调试信息、Cookie、路径或官方插件能力；所有直读 URL 都必须经过插件启用状态、官方属性、capability 和声明域名校验。

## 依赖策略

这是私有项目。如果插件或前端任务需要依赖，安装并记录它。

规则：

- 后端 Python 依赖放入 `backend/requirements.txt`。
- 前端依赖放入 `frontend/package.json`。
- 优先共享运行时依赖，避免每个插件重复。
- 如果插件需要特殊依赖，在插件目录中添加 `requirements.txt` 并在插件 README 中记录。
- 报告依赖安装失败时附上确切命令和错误。
