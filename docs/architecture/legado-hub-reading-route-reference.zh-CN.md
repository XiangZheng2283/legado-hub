# LegadoHub 阅读端路由参考：客户端触发链路 × Hub 子路由契约

> 本文面向「Hub → 定制阅读端（legado-X / legado-E）」的完整链路，逐条说明：
> 1. 入口书源接口 `/api/subscribe/legado/source?code=xxx` 返回什么、客户端拿它做哪几件事（搜索 / 加载详情 / 点击第一章 / 加载章评）。
> 2. 每个暴露的子路由：**请求方法、请求体、响应格式**。
> 3. 每个子路由在**下游客户端的触发时机、详细前置条件、完整触发链路**（附 legado-X 源码引用）。

配套文档：[`docs/architecture/legado-e-reader-contract.zh-CN.md`](./legado-e-reader-contract.zh-CN.md)（契约约束与安全边界）。

---

## 0. 通则

### 0.1 前缀与命名空间

| 前缀 | 用途 | 认证 |
|---|---|---|
| `/api/subscribe/legado/*` | 订阅搜索 / 探索（虚拟源）入口 | 阅读用户（Bearer），`source` 例外 |
| `/api/legado/*` | 书 / 目录 / 章节 / 评论（共享库与直读） | 阅读用户（Bearer），`media` 例外 |
| `/api/auth/access/*` | 授权码兑换 / 会话状态 / 管理入口 | 匿名（exchange code）或 Bearer |

> 历史入口 `/api/legado/source` 已删除；现行唯一书源入口是 `/api/subscribe/legado/source`。

### 0.2 阅读用户认证（前置条件的公共基础）

所有阅读数据面接口（除 `source` 与 `media` 外）都要求一个「阅读用户」会话：

- 凭据来源：HTTP 头 `Authorization: Bearer <token>`（优先）或会话 Cookie（浏览器用）。
- 取法：`auth_service.require_reading_user(request, touch=False)` → `session_token_from_request` 解析 `Authorization`（要求恰好两段、前缀 `Bearer`、无逗号、长度 20–128、无空白），查 `user_sessions`，校验未过期、用户未禁用。
- 失败：`401`，body `{"detail":"当前未登陆，请登陆后使用。"}`（常量 `READING_LOGIN_REQUIRED_MESSAGE`）。
- 令牌即 `/api/auth/access/redeem` 返回的 `token`（会话 id）。

### 0.3 限流

- 阅读接口按动作类型限流：`reading_access_limiter.guard(user_id, kind)`，`kind` ∈ `search` / `metadata` / `chapter` / `reviews`，超限 `429`。
- 授权码兑换 `/api/auth/access/redeem` 另有独立速率限制（按 IP + 授权码标识），失败记 `access` 计数，超限 `429` 带 `Retry-After`。

### 0.4 查询参数防抖 / 校验

- `_reject_query_anomalies(request, allowed)`：出现未知参数（不在 `allowed` 集合）或某参数重复出现 → `422 {"detail":"查询参数无效"}`。
- ID / 数值字段都有白名单与范围上限（见各节）。

---

## 1. 入口书源：`GET /api/subscribe/legado/source?code=xxx`

### 1.1 请求

| 项 | 值 |
|---|---|
| 方法 | `GET` |
| 路径 | `/api/subscribe/legado/source` |
| 查询参数 | `code`（必填，授权码） |
| 请求头 | 无（源码是个人专属链接，授权码在 URL 里） |
| 请求体 | 无 |

### 1.2 前置条件

- `code` 必须是被管理员发放的合法授权码：`authenticate_access_code(access_code)`。非法 / 缺失 → `401`。
- 限流：按客户端 IP + 授权码标识，失败累计，超限 `429` 带 `Retry-After`。
- 响应为终态（不再重定向），直接返回书源 JSON。

### 1.3 响应

返回**一个 JSON 数组**，内含**恰好一个**书源对象（`generate_legado_source` → `[_build_source(...)]`）。Legado 导入时按数组解析。关键字段：

| 字段 | 值 / 含义 |
|---|---|
| `bookSourceName` | `"{name}({_READER_RULE_VERSION})"`，如 `LegadoHub 聚合(0.0.27)` |
| `bookSourceGroup` | 组名（配置可改，内网追加 `内网`） |
| `bookSourceUrl` | `LegadoHub`（公网）/ `LegadoHub-LAN`（内网）——**书源身份与更新键** |
| `lastUpdateTime` | 毫秒时间戳；Reading 只在该值增大时提示更新 |
| `bookSourceType` | `0` |
| `enabled` / `enabledCookieJar` / `enabledExplore` | `true` |
| `header` | `@js:` 只注入已存 Bearer（**不做网络请求**，避免登录页卡片打不开） |
| `loginUi` | JSON：`订阅` / `书库` 按钮（管理入口） |
| `loginUrl` | JS：授权码读取、`login()`、redeem 兑换、`legadoHubStatus` |
| `loginCheckJs` | 401 检测脚本：匹配 `当前未登陆|未登陆|请登陆后使用|Unauthorized` → 清 Bearer，绑定码自动重新兑换 |
| `searchUrl` | `@js:` → `{base}/api/subscribe/legado/search?keyword=…&page=…` |
| `respondTime` | `25000`（略高于 page2 的 20s 短等待） |
| `exploreUrl` | `已发布书库::@js:{base}/api/subscribe/legado/explore?page=…` |
| `ruleSearch` / `ruleExplore` | 见 1.4 |
| `ruleBookInfo` | 见 1.4 |
| `ruleToc` | 见 1.4 |
| `ruleContent` | `content`（@js）+ `title` + `chapterComment`（v2 协议） |
| `jsLib` | 全部鉴权/重写辅助函数（绑定码、Bearer、`legadoHubAjax`、`legadoHubRewriteApiUrl` 等） |

### 1.4 客户端拿它做哪几件事（用途映射）

| 客户端动作 | 用到的书源字段 | 触发的 Hub 接口 |
|---|---|---|
| **搜索** | `searchUrl` + `ruleSearch.bookList="$.items"` | `GET /api/subscribe/legado/search?keyword=&page=` |
| **书库 / 发现** | `exploreUrl` + `ruleExplore` | `GET /api/subscribe/legado/explore?page=` |
| **加载详情页** | 搜索结果 `$.bookUrl`（= `{base}/api/legado/book/{id}`）+ `ruleBookInfo.init="$.data"`；详情返回 `$.tocUrl` | `GET /api/legado/book/{book_id}` |
| **点击第一章 / 目录** | `ruleBookInfo.tocUrl`（= `{base}/api/legado/book/{id}/toc`）+ `ruleToc.chapterList="$.chapters"` | `GET /api/legado/book/{book_id}/toc` |
| **加载章节正文** | `ruleToc.chapterUrl`（`data:contentUrl;base64,…`）+ `ruleContent.content` | `GET /api/legado/chapter/{chapter_id}`（通过 `legadoHubAjax`） |
| **进入章节预取段评气泡/计数** | `ruleContent.chapterComment.url/data`（→ segments 摘要） | `GET /api/legado/chapter/{chapter_id}/reviews`（JSON） |
| **点开段评 / 本章说 / 页热评（弹窗正文）** | `ruleContent.chapterComment.action`（`@js` → `sourceWebView` URL） | `GET /api/legado/chapter/{chapter_id}/reviews/view?tab=…`（HTML） |
| **评论内图片 / 头像** | 评论 HTML 的 `img src` 首选**原始签名 CDN URL**（`avatarUrl`/`imageSrcs`）；该 URL 签名过期/不可加载时才**回退**到 `/api/legado/media/{book_id}/{filename}`（fqdown 按 sha1(url) 存的不可变本地镜像） | 直接载 CDN；回退时 `GET /api/legado/media/{book_id}/{filename}` |
| **兑换授权（冷启）** | `loginUrl` / `searchUrl @js` 内 `legadoHubRedeemToAuth` | `POST /api/auth/access/redeem` |
| **登录状态** | `legadoHubStatus` / `loginCheckJs` | `GET /api/auth/access/me` |

---

## 2. 客户端触发链路总览（下游 = legado-X）

```
导入 source JSON（code 链接）
   │
   ├─ 首次使用（搜索/目录/正文）→ @js 内 legadoHubResolveAuth()
   │      已存 Bearer？用；否则读绑定码 → POST /api/auth/access/redeem → putLoginHeader(Bearer)
   │
   ├─ 搜索          SearchActivity.submit → SearchViewModel.search(key)
   │                  → SearchModel.search(id,key) page=1 → WebBook.searchBookAwait(src,key,page)
   │                  → AnalyzeUrl(searchUrl @js) [header 带 Bearer] → GET /api/subscribe/legado/search
   │     【翻页】滚动到底部且 hasMore → viewModel.search("") → 同 searchID → page++ → 再次 GET
   │
   ├─ 详情        点击搜索结果 → WebBook.getBookInfoAwait
   │                 → bookUrl 非空 → AnalyzeUrl(bookUrl) → GET /api/legado/book/{id} → ruleBookInfo
   ├─ 目录/第一章 打开目录或开始阅读 → WebBook.getChapterListAwait
   │                 → tocUrl → GET /api/legado/book/{id}/toc → ruleToc → chapterUrl=<js> data:contentUrl;base64,…
   ├─ 章节正文   点击章节 → ReadBook.loadContent(durIndex±1) → BookHelp.getContent(缓存)
   │                → 未命中 → getContentAwait → AnalyzeUrl(章节 data:URL)
   │                → type=legadoHub → getStrResponseAwait 返回 hex(真实URL)
   │                → ruleContent.content: hexDecodeToString → legadoHubAjax(contentUrl) → GET /api/legado/chapter/{id}
   └─ 章评   （章节进入时预取段评气泡）
                   【进入章节】正文排好 → loadChapterComment → ChapterCommentLoader.load
                   → Repository 缓存(键=源+fingerprint+书URL+章URL+版本, TTL=300s)
                   → GET /api/legado/chapter/{id}/reviews → rule.data @js → v2 载荷 → Parser.parse
                     （该 JSON 只提供段落气泡/本章说计数，不在弹窗里渲细节）
                 【点开气泡】点段落气泡(segment) / 页热评(page) / 本章说(chapter)
                   → ContentTextView/ReadView 回调 → ChapterCommentEvent → openChapterComment
                   → ChapterCommentActionExecutor.resolveAndLoad 执行 rule.action(@js)
                   → contentUrl + /reviews/view?tab=paragraph&paragraphId/<paragraphIds>|tab=chapter
                   → GET /reviews/view（HTML）→ ChapterCommentPanel 底部 WebView（来源隔离）
```

每条的具体触发时机、前置条件、链路在 §3 逐节详述。

---

## 3. 子路由契约（请求 / 响应 / 客户端触发链路）

### 3.0 认证子路由

#### `POST /api/auth/access/redeem`

- **请求体**：`{"accessCode": "…"}`
- **响应**：`{"ok":true,"token":"<sessionId>","expiresAt":"ISO 时间","user":{"username":…,"role":…}}`
- **失败**：`401/403`（授权码无效或封禁，附 `Retry-After` 时 `429`）。
- **客户端用途**：`jsLib.legadoHubRedeemToAuth` 用 `java.ajax(base+"/api/auth/access/redeem",{method:"POST",body})` 兑换，成功后 `source.putLoginHeader({Authorization:"Bearer "+token})`。
- **前置条件**：授权码（绑定码或登录页输入的 `授权码`）。

#### `GET /api/auth/access/me`

- **请求头**：`Authorization: Bearer <token>`（或会话 Cookie）
- **响应**：`{"authenticated":true,"user":{"username":…}}`；未登录 `{"authenticated":false,"user":null}`。
- **客户端用途**：`jsLib.legadoHubStatus` 校验；**判定成功必须非空用户名 + token**，否则清 Bearer 重新兑换。

#### `GET /api/auth/access/enter?code=&next=`

- 浏览器入口：授权码换会话 Cookie 并 `302` 到 `next`（默认 `/console/subscription`）。`loginUi` 的 `订阅/书库` 按钮即调用（`legadoHubOpenConsolePath`）。

#### `POST /api/auth/access/logout`

- 清会话 / Cookie；`jsLib.legadoHubLogout` 调用。

---

### 3.1 搜索：`GET /api/subscribe/legado/search`

| 项 | 值 |
|---|---|
| 查询参数 | `keyword`、`page`（1..1000）、`waitMs`（可选） |
| 认证 | 阅读用户 Bearer |
| 限流 | `kind="search"` |

**响应格式**（`_legado_search_payload`）：

```jsonc
{
  "implemented": true,
  "keyword": "…",
  "page": 1,
  "items": [
    {
      "displayType": "aggregate",      // 或 "source"
      "resultKind": "aggregate",
      "sourceId": "legadohub_ai_aggregate",
      "sourceName": "LegadoHub 订阅聚合",
      "bookId": "<encoded>",
      "rawBookUrl": "legadohub://aggregate/library/<id>",
      "bookUrl": "{base}/api/legado/book/<book_id>[?lane=lan]",  // 内网带 lane=lan
      "name": "…", "author": "…",
      "coverUrl": "…", "intro": "…",
      "lastChapter": "…", "readingLastChapter": "…",
      "wordCount": 123,
      "kind": "…",
      "aggregateBookId": "…",
      "searchVisibilityStatus": "…",
      "libraryStatus": "…",
      "processedChapters": n, "visibleProcessedChapters": n, "totalChapters": n,
      "networkLane": "lan|public", "score": 0
    }
    // … 更多（厂商/直读 source 项，公开子集）
  ],
  "jobId": "…",
  "status": "completed|partial|timed_out|failed|running",
  "liveSearchPending": true|false
}
```

**页语义（关键）**：

- **page=1**：短等待（默认 `_READING_SEARCH_PAGE1_WAIT_MS=6_000`）后返回「已发布共享书 + 首批厂商结果」。
- **page≥2**：同一后台 job 的「新厂商结果」增量；等待 `_READING_SEARCH_FOLLOW_WAIT_MS=20_000`。该页无新条目返回空 `items` → 客户端停止翻页。
- 整个 job 硬截止 `_READING_SEARCH_TIMEOUT_MS=120_000`；单次请求不等待所有慢源。
- 客户端 `respondTime=25000` 略高于 page≥2 等待，使后续页能完成返回。

**客户端触发链路**：
1. `SearchActivity` 提交 → `SearchViewModel.search(key)`。
2. `SearchModel.search(id, key)`：新 id → `searchPage=1`；随后对每个启用书源 `WebBook.searchBookAwait(src, searchKey, searchPage)`（单源超时 `withTimeout(30000)`）。
3. `WebBook.searchBookAwait` → `AnalyzeUrl(mUrl=searchUrl, key=key, page=page)`。构造时 `source.getHeaderMap(hasLoginHeader=true)` 并入已存 Bearer；`initUrl→analyzeJs` 执行 `searchUrl @js`（内含 `legadoHubResolveAuth()`，必要时先兑换）。
4. `getStrResponseAwait` → GET 搜索接口（Accept + 可选 Authorization）→ 401 时 `loginCheckJs` 清/补 Bearer。
5. `ruleSearch.bookList="$.items"` 解析为 `SearchBook`。
6. **翻页**：滚动到底部 `scrollToBottom()`，条件 `!isSearchLiveData && searchKey.isNotEmpty() && hasMore` → `viewModel.search("")` → 同 `searchID` → `searchPage++` → 再次 `startSearch()`。只要某页有条目 `hasMore` 保持 true；Hub 返回空页即停。

**前置条件**：已启用书源且关键词非空；页 `1..1000`；Bearer 可解出；`search` 未限流；参数无额外/重复。

---

### 3.2 探索 / 书库：`GET /api/subscribe/legado/explore`

| 项 | 值 |
|---|---|
| 查询参数 | `sourceId`（可空）、`groupId`（可空，默认 `published`）、`page`（1..1000） |
| 认证 | 阅读用户 Bearer |
| 限流 | `kind="search"` |

**响应格式**：

```jsonc
{
  "implemented": true,
  "sourceId": "…",
  "groupId": "published",
  "page": 1,
  "items": [ /* 与搜索 items 相同 */ ]
}
```

（`page_published_books`：只列 `search_visibility_status='visible'` 且 `visible_processed_chapters>0`。）

**客户端触发链路**：`exploreUrl="已发布书库::@js:{base}/api/subscribe/legado/explore?page=…"`；`WebBook.exploreBook` → `AnalyzeUrl`（同样先 resolve auth）→ GET → `ruleExplore.bookList="$.items"`。

**前置条件**：与搜索相同。

---

### 3.3 书详情：`GET /api/legado/book/{book_id}`

| 项 | 值 |
|---|---|
| 路径参数 | `book_id` = `{source_id}:{base64url(book_url)}`（`encode_book_id`，去 `=` 填充） |
| 查询参数 | `lane`（可选双源消歧，忽略） |
| 认证 / 限流 | Bearer / `metadata` |
| 虚拟源书_id | `legadohub_ai_aggregate:<b64url("legadohub://aggregate/library/<id>")>` |

**响应格式**（`_public_book_response`）：

```jsonc
{
  "implemented": true,
  "data": {
    "sourceId": "…", "bookId": "…",
    "name": "…", "author": "…",
    "coverUrl": "…", "intro": "…", "kind": "…",
    "lastChapter": "…",
    "wordCount": 123,
    "status": "…",
    "updateTime": "YYYY-MM-DD HH:mm",
    "bookUrl": "{base}/api/legado/book/{book_id}",
    "tocUrl":  "{base}/api/legado/book/{book_id}/toc"
  }
}
```

- 虚拟源走 `library_books_service.legado_book_detail`；未发布 → `404 {"detail":"书籍尚未发布"}`。
- 第三方源要求启用、非官方、声明 `detail` 且 URL 主机在插件声明内；否则 `404`。

**客户端触发链路**：点搜索结果 → `BookDetailActivity` → `WebBook.getBookInfoAwait` → `infoHtml` 空 → `AnalyzeUrl(book.bookUrl)` → GET 详情 → `ruleBookInfo.init="$.data"` → 解析含 `tocUrl`（`canReName=1`）。

**前置条件**：书未在书架（或强制刷新）；`book_id` 可解码且发布/插件可用；Bearer 有效；`metadata` 未限流。

---

### 3.4 目录：`GET /api/legado/book/{book_id}/toc`

| 项 | 值 |
|---|---|
| 路径参数 | `book_id`（同 3.3） |
| 查询参数 | `lane`（可选） |
| 认证 / 限流 | Bearer / `metadata` |

**响应格式**（`_public_toc_response` / `legado_toc`）：

```jsonc
{
  "implemented": true,
  "bookId": "…",
  "chapters": [
    {
      "sourceId": "legadohub_ai_aggregate",
      "chapterId": "<encoded>",
      "index": 0,
      "title": "第1章 …",
      "chapterUrl": "{base}/api/legado/chapter/<chapter_id>",
      "updateTime": "YYYY-MM-DD HH:mm",
      "isVip": false, "isPaid": false, "isPay": false,
      "previewOnly": false
    }
  ]
}
```

- 虚拟源共享目录与 `fanqie_local` 增量目录采用**合并语义**：已聚合发布的共享章节优先；主源为 `fanqie_local` 时，Hub 同时触发 `127.0.0.1:18423` 的整本任务，并读取 `downloaded_chapters.jsonl`，用已下载但尚未聚合发布的章节补齐目录。因此一本书即使已经“部分发布”，目录仍会随下载增长，而不会冻结在首次发布的章节子集。
- 第三方源由 `Catalog.toc` 生成，chapter_id 重编码并做白名单校验。

**客户端触发链路**：打开目录/首次阅读 → `WebBook.getChapterListAwait` → `AnalyzeUrl(book.tocUrl)` → GET 目录 → `ruleToc.chapterList="$.chapters"`；`chapterUrl` 规则包成 `data:contentUrl;base64,<b64>,{"type":"legadoHub"}`。

**前置条件**：详情已得 `tocUrl`；书已发布 / 插件 `toc`；Bearer 有效；`metadata` 未限流。

---

### 3.5 章节正文：`GET /api/legado/chapter/{chapter_id}`

| 项 | 值 |
|---|---|
| 路径参数 | `chapter_id` = `{source_id}:{base64url(chapter_url)}` |
| 查询参数 | `lane`（可选） |
| 认证 / 限流 | Bearer（`Accept: application/json`）/ `chapter` |
| 真实调用 | 客户端用 `jsLib.legadoHubAjax(url)`（含 Bearer） |

**响应格式**（`_public_chapter_response`）：

```jsonc
{
  "implemented": true,
  "chapterId": "<chapter_id>",
  "title": "第1章 …",
  "content": "<段落/HTML>",
  "authRequired": false,
  "isVip": false, "isPaid": false, "isPay": false,
  "previewOnly": false,
  "extra": { "previewOnly": …, "isVip": …, "contentAccess": … }  // 仅三个安全字段
}
```

- 虚拟源：优先由 `library_books_service.legado_chapter` 读共享 UTF-8 正文；若共享章尚未发布但目录项来自 `fanqie_local` 增量落盘，则根据聚合章中的 `sourceChapterId` 动态委托本地插件，直接读取 `downloaded_chapters.jsonl`。详情、目录和正文三个入口都会幂等触发 `127.0.0.1:18423/api/jobs`，避免客户端命中本地缓存后绕过某个入口而没有启动下载。已聚合清洗正文不再实操净化/作家说剥离（`apply_purify=False, strip_author_say=False`）。
- 增量章尚未落盘时返回 HTTP 200、空 `content` 与 `debug.retryable=true`；Reading 本身不会按该字段自动轮询，用户刷新/客户端后续预取会再次请求。因此“边下边看”的准确含义是：**已落盘章节立即可读、目录持续增长**，不是在一个 HTTP 响应中流式推送未完成正文。
- 第三方源：`Catalog.chapter` + 实时净化（`purify_for_reading`）→ 作家说剥离。

**客户端触发链路**（核心 `data:contentUrl` 机制）：
1. 点章节 → `ReadBook.loadContent(durChapterIndex)`，同时预取 `durChapterIndex±1`（三个实例）。
2. `loadContent(index)` → `BookHelp.getContent`（本地缓存/已下载命中则回放）→ 未命中 → `download` → `WebBook.getContentAwait`。
3. `contentRule.content` 非空 → `AnalyzeUrl(bookChapter.getAbsoluteURL())`（章节 data:URL）。
   - `paramPattern=\s*,\s*(?=\{)` 把 `data:contentUrl;base64,<b64>,{"type":"legadoHub"}` 切成 url 与 JSON 选项；`type="legadoHub"` 非空。
   - `getStrResponseAwait`：因 `type != null` → `StrResponse(url, HexUtil.encodeHexStr(getByteArrayAwait()))`；`getByteArrayIfDataUri` base64 解码出真实章 URL 字节 → hex 作为请求体返回。
4. `ruleContent.content @js`：hexDecodeToString → 真实 URL → `legadoHubRewriteApiUrl` → `legadoHubAjax(contentUrl)`（GET，Bearer）→ 章节 JSON → `chapterPayload.content` 作正文；否则回退 `java.ajax`。
5. `title="$.title"`；按 `<p>/<div>` 判断段落，否则 `\n\n→<br><br>`、`\n→<br>`。

**前置条件**：章 `chapter_id` 可解码且对应发布章 / 直读插件；目录已加载（data:URL 由规则生成）；Bearer 有效；`chapter` 未限流。

---

### 3.6 章节评论摘要（段评气泡 / 本章说计数）：`GET /api/legado/chapter/{chapter_id}/reviews`

> **本接口只在「进入章节」时预取一次**，返回 JSON 摘要，用来在正文里画「段评气泡、本章说/作家说徽章与计数」。它**不提供**可直接阅读的评论正文——用户点开气泡后真正渲染评论内容的是 §3.7 的 `/reviews/view` HTML。不要把两者混为一谈。

| 项 | 值 |
|---|---|
| 路径参数 | `chapter_id`（同 3.5） |
| 查询参数 | `lane`（可选） |
| 认证 / 限流 | Bearer / `reviews` |
| 服务端缓存 | `chapter_review_cache`（TTL 600s / ≤256 条，同章共享） |
| 客户端缓存 | `chapterComments`（20 MiB / 2000 条，键=源+fingerprint+书URL+章URL+版本） |

**响应格式**（聚合/插件评数据，经对齐与汇总）：

```jsonc
{
  "implemented": true,
  "chapterId": "<chapter_id>",
  "mappedChapterId": "<源章_id>",   // 虚拟源才有
  "mappedSourceId": "…",
  "mappingReason": "…",
  "paragraphs": { /* 段->评论 映射（直连时） */ },
  "hotParagraphReviews": [
    {
      "id": "…", "paragraphId": 12, "matchedParagraphIndex": 3, "matchedParagraphCount": 2,
      "matchedText": "…", "paragraphText": "…",
      "content": "…", "userName": "…", "CommentCount": 5,
      "topReviews": [ … ]
    }
  ],
  "chapterEndHot": [ … ],   // 本章说 1..N 摘要
  "chapterEnd": [ … ],      // 本章说回退桶
  "authorReviews": [ … ],   // 作家说
  "summary": { "chapterEndCount": n, … },
  "debug": { "aggregate": true, "reviewSource": "…", "snapshotSourceId": "…", "mediaUploaded": … }
}
```

**客户端侧规则消费**（`ruleContent.chapterComment`）：

- `url`（`_chapter_comment_url_rule` @js）：从 data:URL 里 `java.base64Decode` 出真实 `contentUrl` → `legadoHubReviewRoot(legadoHubRewriteApiUrl(contentUrl))` 拼接 `"/reviews"`。
- `data`（`_chapter_comment_data_rule` @js）：把 /reviews 响应规约为 **v2 载荷**：

```jsonc
{
  "version": 2,
  "segments": [
    {
      "id": "12", "paragraphIndex": 3, "paragraphCount": 2,
      "excerpt": "…",
      "counts": { "total": 5, "hot": 2 },
      "pageEligible": true,
      "actionData": { "paragraphId": "12" }
    }
  ],
  "author": { "label": "作者", "badge": "作家说", "counts": {"total":0,"hot":0}, "actionData": null, "previews": ["…"] } | null,
  "chapter": { "label": "本章说", "counts": {"total":n,"hot":m}, "actionData": {}, "previews": ["…≤3"] } | null
}
```

- `ChapterCommentParser.parse`（legado-X）严格校验：`version==2`、payload ≤256KB、segments ≤200、id ≤256、excerpt/preview ≤512、previews ≤3，任意不符 → 该章评论 `Unavailable`。

**客户端触发链路**（进入章节时预取）：
1. 每章正文排好（`ReadBook.contentLoadFinish`，当前/上一/下一 `TextChapter`）→ `loadChapterComment`（当前章 `CURRENT`，邻居 `PRELOAD`）。
2. 前置条件：source 非空、`rule.url` 非空、且 `display.segment/page/chapter` 至少一个 enabled；否则 `Disabled` 不发请求，也没有气泡。
3. `ChapterCommentLoader.load` → `ChapterCommentRepository.load`：
   - 请求键 = sha256(source.bookSourceUrl + ruleFingerprint + book.bookUrl + chapter.getAbsoluteURL() + protocolVersion)。
   - 本地 `chapterComments` 缓存命中且 <TTL(300s) → 直接复用；过期先发 stale 再刷新；刷新失败保留 stale。请求超时 15s；并发同键合并；PRELOAD 信号量串行。
4. 网络层：`AnalyzeUrl(rule.url @js …)` → GET `contentUrl/reviews`（头含 Bearer）→ 响应字符串。
5. `rule.data @js` 解析 → `ChapterCommentParser.parse`（v2）→ `Ready(payload, stale)` / `Unavailable`；把 segments 画成段落气泡、chapter 徽章、author 徽章（`SegmentCommentOverlay`）。

**前置条件**：章节正文存在（依赖章 `chapter_id`）；评论显示预设至少一个启用；Bearer 有效；`reviews` 未限流。**这里只定位气泡与徽章；真正的评论正文属于 §3.7。**

---

### 3.7 段评 / 页热评 / 本章说详情（弹窗内容）：`GET /api/legado/chapter/{chapter_id}/reviews/view`

> **这是用户「点开评论」时真正渲染评论正文的接口**，返回 `text/html`，在阅读页底部弹层（`ChapterCommentPanel` + `SourceScopedWebController` 的 WebView）里展示。`rule.action` 只负责拼出这个 URL；客户端用本书源 header + Cookie 抓取首屏 HTML。

| 项 | 值 |
|---|---|
| 查询参数 | `tab`（chapter|paragraph，非法 → 422）、`paragraphId`（单个段）、`paragraphIds`（≤50 逗号分隔非负整数，≤1024 字符，页热评）、`rootReviewId`（回复）、`page`（1..1000）、`pageSize`（1..50，服务端再压到 ≤20）、`cursorId`、`lane` |
| 认证 / 限流 | Bearer / `reviews` |
| 响应 | `text/html`（`render_chapter_reviews_html`），`X-Frame-Options: SAMEORIGIN` + CSP `frame-ancestors 'self'` |

**行为（服务端按查询参数选数据源）**：
- `rootReviewId` → `review_replies`（在某段里的回复列表）+ 层切 paragraph。
- `paragraphIds` 非空 → `page_hot_reviews`（当前页全部段的热评聚合，对应 `page` 气泡）。
- `paragraphId` 单个 → `paragraph_reviews`（该段完整评论，对应 `segment` 气泡）。
- 否则 `tab=chapter` 且 `page>1` → `chapter_say`（本章说翻页）。分页统一由 `chapter_review_catalog._paged_review_operation`（pageSize ≤20）。

**客户端触发链路**（点开评论弹层）：
1. **触发点**（三处，都在排版层）：
   - 点**段评气泡**：`ContentTextView.clickChapterComment` → `SegmentCommentOverlay.hitTest(...)` 命中 → `callBack.openChapterComment(ChapterCommentEvent.segment(page, anchor))`（源码 `ContentTextView.kt:336`）。
   - 点**本章说徽章**：命中 `ChapterCommentPageBlock` → `ChapterCommentEvent.chapter(page, block.summary)`（`ContentTextView.kt:342`）。
   - 点**页热评**入口：`ReadView.kt:543` `ChapterCommentEvent.page(page, projection, count)` → 回调（`ReadView.kt:462/551`）。
2. `ReadBookActivity.openChapterComment(event)`（`ReadBookActivity.kt:1385`）：取源 `getContentRule().chapterComment`、`panel.openLoading()`、起协程。
3. `ChapterCommentActionExecutor.resolveAndLoad(source, book, chapter, rule, event)`（`ChapterCommentActionExecutor.kt:29`）：
   - 执行 `rule.action @js`（`_chapter_comment_action_rule`，经 `source.evalJS`，绑定 book/chapter/title/baseUrl/event/result），从 `event.toContractJson()` 取 `scope`：
     - `segment` → `contentUrl + /reviews/view?tab=paragraph&paragraphId=<id>`，标题「段评说」；
     - `page` → `…?tab=paragraph&paragraphIds=<id1,id2,…≤50>`，标题「页热评」；
     - `chapter` → `…?tab=chapter`，标题「本章说」；
   - 结果 `ChapterCommentActionParser.parse` → `{"type":"sourceWebView","url":viewUrl,"title":…,"presentation":"bottomSheet","heightRatio":0.78}`。
4. 同源校验：`rule.url` 求 `summaryOrigin`（`SourceScopedRequestPolicy.validateActionUrl`），`pinActionUrl(initialUrl, summaryOrigin)` 固定 DNS——两 URL 必须同源，拒绝跨源跳转/私网元数据/凭据参数；重定向 ≤5。
5. 抓首屏：`newSourceScopedHttpClient`，书源 header（过滤 cookiejar/host/content-length/connection/transfer-encoding，仅设 UA），合并 Cookie；HTML ≤2 MiB。
6. 渲染：`panel.showPage(ChapterCommentWebPage)` → `SourceScopedWebController.load` 在 `ChapterCommentPanel`（底部卡片，高度比 0.78）的 `PooledWebView` 里展示；后续图片/子请求走来源隔离网络上下文，**Bearer token 不外泄**给头像/媒体域。

**前置条件**：该章存在（`chapterIndex` 能查到 `Chapter`）；评论显示启用；action 可构建且与摘要同源；Bearer 有效；`reviews` 未限流；`tab` 非法 → 422。

---

### 3.8 评论媒体（签名 URL 的回退镜像）：`GET /api/legado/media/{book_id}/{filename}`

> **这是「回退」路由，不是评论 HTML 的首选 `src`。** 评论 HTML 的图片/头像首选**带签名的原始 CDN URL**（`avatarUrl`/`imageSrcs`，见 `_enrich_review_media` 的 `avatar_url = avatar_orig or avatar_local`、`image_orig[i] if … else image_urls_local[i]`，CDN 优先、本地镜像兜底）。CDN 签名 URL 会**过期/失效**，此时才回退到本路由——从 fqdown 按 `sha1(url)` 存的不可变本地镜像读取。

| 项 | 值 |
|---|---|
| 路径参数 | `book_id`（纯数字，非数字→404）、`filename`（`[0-9a-f]{40}.(jpeg|jpg|png|gif|webp|avif|heic|heif)` 正则） |
| 认证 | **无**（公开内容寻址缓存） |
| 响应 | FileResponse；`Cache-Control: public, max-age=31536000, immutable, s-maxage=31536000` + `CDN-Cache-Control` + ETag |
| 失败 | 未缓存 → `404`（`<img onerror>` 静默隐藏） |

**触发时机与回退逻辑**：
- 客户端 `/reviews/view` 拿到的 HTML 里，图片 `src` 首选**原始签名 CDN URL**（`avatarUrl` / `imageSrcs`）。只有该 URL 无法加载（签名过期/403/404/非 https 可信）时才回退到 `/api/legado/media/{book_id}/{filename}`。
- 服务端 `_enrich_review_media`（chapter_review_catalog.py:159）：把评论的 `avatarRef`/`imageRefs`（fqdown 本地 `save_dir/<book_id>/images/<sha1>.<ext>`）经 `_fanqie_ref_to_media_url` 映射成本路由 URL，作为 CDN URL 的**兜底**；评论 HTML 只嵌「原 URL 或本地镜像」二选一，且 CDN 优先。
- 文件名 = sha1(原始 URL)，**内容寻址、不可变**；长缓存（1 年 immutable + CDN s-maxage）让浏览器/边缘按 .png/.jpeg 等静态扩展名持久缓存，签名过期后仍可命中本地镜像。
- 本路由**不做**任何代理/下载：绝不写下载器、不经 img 上传队列（`media_upload_queue` 只负责封面等需整改域外 URL 的场景）。客户端**没有** onerror 自动换 `/media/` 的注入脚本——回退由**服务端渲染时二选一**决定（CDN 可用则不用 /media/）。

---

### 3.9 fanqie_local 本机下载器的触发时机（什么时候才下载）

> 面向「Hub → legado 客户端」对番茄（fq）内容：**搜索命中时不触发下载**，用户对这本书产生「承诺动作」时才幂等触发整本下载。搜索是廉价的探索性动作（`WebBook.searchBookAwait` 只列表分页），若每个搜索命中就 `POST /api/jobs`，会为大量用户并不真正读的书打爆本机番茄下载器。

**触发点（按用户承诺程度排序）**：

| 触发点 | 客户端动作 | Hub 实现 | 特点 |
|---|---|---|---|
| ① **订阅 / 建书** | 用户在搜索点「订阅/加书架」→ 客户端建书 | `backend/app/api/subscribe.py:800 spawn_trigger_for_book(book)` | **首选**：第一个承诺信号，整本下载随即开始 |
| ② **打开详情** | 点搜索结果 → `WebBook.getBookInfoAwait` → `GET /api/legado/book/{id}` | `backend/app/api/legado.py:413-415 spawn_fanqie_trigger_for_url`（仅 `fanqie_local`） | 覆盖未走订阅直达路径的兜底 |
| ③ **聚合在线读（章未就绪）** | 进章 → `getContentAwait` → `GET /api/legado/chapter/{id}` → 聚合处理占位 | `backend/app/services/aggregate_processor.py:4503 _trigger_fanqie_download_on_aggregate_read`（仅 primary=`fanqie_local`） | 幂等整本触发，随阅读立即开始 |
| ④ **章节懒触发** | 任一 `chapter()` 缺失 | 插件自身 `_ensure_job_started` | 最迟兜底 |

**幂等与并发安全**（所以多处触发不冲突）：
- `fanqie_local_trigger.ensure_fanqie_download_job`：模块级 asyncio 锁（`_FANQIE_JOB_LOCK`）内 check-then-create，并发 fire-and-forget（阅读打开/订阅/章节懒触发）对同一本书**不会双 POST** `/api/jobs`。
- 下载器 `/api/jobs` 本身按 `book_id` 幂等：已 `queued/running/done` 复用；`failed/canceled` 不自动重建。
- 全部触发 **fire-and-forget、永不阻塞响应、永不 raise**——订阅、详情、章节响应当下即返回，与下载无关。

**结论**：搜索不触发；**订阅/加书架建书**触发整本下载（首选），**打开详情**、**聚合章在线读未就绪**作幂等兜底重触发，**章节懒触发**作最终保底。保证用户一旦真正要看，增量数据（`downloaded_chapters.jsonl` / `segment_comments/<id>.json` / `images/`）立刻开始产生。

---

## 4. 前置条件汇总表

| 子路由 | 认证 | 限流 kind | 主要前置条件 | 失败 |
|---|---|---|---|---|
| `/api/subscribe/legado/source` | 匿名（code） | 兑码限流 | 合法 `code` | 401 |
| `/api/subscribe/legado/search` | Bearer | search | 页 1..1000、关键词、Bearer | 401/422/429 |
| `/api/subscribe/legado/explore` | Bearer | search | 参数合法 | 401/422/429 |
| `/api/legado/book/{id}` | Bearer | metadata | 书发布/插件 detail | 401/404/422/429 |
| `/api/legado/book/{id}/toc` | Bearer | metadata | 目录发布/插件 toc | 401/404/422/429 |
| `/api/legado/chapter/{id}` | Bearer | chapter | 章发布/插件 chapter | 401/404/422/429 |
| `/api/legado/chapter/{id}/reviews` | Bearer | reviews | 章存在、评论启用 | 401/404/422/429 |
| `/api/legado/chapter/{id}/reviews/view` | Bearer | reviews | 章存在、tab 合法 | 401/404/422/429 |
| `/api/legado/media/{book}/{file}`（回退镜像） | 无 | 无 | book 数字、filename 正则、已缓存；仅当 CDN 签名 URL 失效时才被回退引用 | 404 |
| `/api/auth/access/redeem` | 匿名 | 兑码限流 | 合法授权码 | 401/403/429 |
| `/api/auth/access/me` | Bearer/Cookie | — | 会话有效 | 401 / {false,null} |

---

## 5. 关键源码索引（本次核对依据）

**Hub 侧**
- `backend/app/api/subscribe.py`：search / explore / source 接入；
- `backend/app/api/legado.py`：book|toc|chapter|reviews|reviews/view|media 全部处理器与响应构件；
- `backend/app/core/legado_source.py`：书源 JSON、`_auth_runtime_js`、`_search_url_rule`、`_chapter_comment_url/data/action_rule`；
- `backend/app/services/library_books.py`：legado_book_detail / legado_toc / legado_chapter / build_search_injected_item；
- `backend/app/services/chapter_review_catalog.py`、aggregate_reviews.py、reading_reviews.py：评论结构、对齐、HTML 渲染；
- `backend/app/services/user_auth.py`：require_reading_user、Bearer 解析、401 文案；
- `backend/app/source_plugins/id_codec.py`：book/chapter id 编码。

**客户端（docs/apk/legado-X）**
- `app/model/webBook/SearchModel.kt`：搜索翻页（searchPage++、30s 单源超时）；
- `app/model/webBook/WebBook.kt`：searchBookAwait / getBookInfoAwait / getChapterListAwait / getContentAwait；
- `app/model/analyzeRule/AnalyzeUrl.kt`：type 分支、data: 解码、hex 返回（~417-433, 634-645, 222-286）、paramPattern（~768）；
- `app/model/ReadBook.kt`：loadContent / contentLoadFinish / loadChapterComment / promoteCurrentChapterComment；
- `app/model/chapterComment/*`：Loader / Repository / Payload(Parse) / ActionExecutor；
- `app/ui/book/search/SearchActivity.kt`（scrollToBottom）、`SearchViewModel.kt`（hasMore）。

---

_本文基于当前仓库代码整理；规则常量（_READER_RULE_VERSION / _READER_RULE_RELEASED_AT_MS）与评论显示预设会变化，以源码为准。_
