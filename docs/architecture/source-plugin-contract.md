# LegadoHub Source Plugin Contract

> **For agentic workers:** This contract defines the plugin API. Do not invent a different interface during implementation. If a site needs behavior not covered here, add a backward-compatible extension to this document first, then implement it.

**Contract version:** `1.0`

**Runtime owner:** LegadoHub core.

**Plugin owner:** Site-specific adapter code.

---

## Core Rule

A source plugin describes how one site or site family is adapted. It does not control the engine.

Plugins may:

- Build site-specific URLs.
- Parse HTML/JSON/API responses.
- Generate site-specific signatures or tokens.
- Decrypt chapter payloads.
- Describe authentication requirements.
- Describe site-family domain profiles and choose among them while parsing.
- Request controlled browser/manual-login assistance through `ctx`.

Plugins must not:

- Control source-level concurrency.
- Create unmanaged background threads.
- Create global HTTP sessions that bypass `ctx`.
- Own global retry/proxy/cache policy.
- Shape Reading/Legado aggregate-source JSON.
- Import or depend on `engine-jvm`, `app.legado_engine`, or `app.engine`.

## Directory Layout

```text
plugins/sources/<plugin_id>/
  metadata.yaml
  source.py
  README.md
  requirements.txt       # optional; private project, install if needed
  tests/
    smoke.yaml
  skills/
    SKILL.md             # optional plugin-specific adaptation notes
```

For Stage 1, dependencies may be installed when needed. Record added backend dependencies in `backend/requirements.txt`, frontend dependencies in `frontend/package.json`, or plugin-local dependencies in `plugins/sources/<plugin_id>/requirements.txt`.

## metadata.yaml

Required fields:

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

Required field rules:

- `contractVersion`: must be `"1.0"` for Stage 1.
- `id`: stable ASCII identifier, unique across all plugins.
- `name`: Chinese display name when available.
- `version`: plugin version.
- `type`: must be `source`.
- `domains`: domains this plugin is allowed or expected to access.
- `baseUrls`: starting URLs for this site or site family.
- `capabilities`: subset of `search`, `detail`, `toc`, `chapter`, `explore`, `auth`.
- `auth.mode`: one of `none`, `optional`, `required`, `manual`.
- `content.access`: one of `free`, `paid`, `mixed`, `unknown`.
- `tags`: operational hints.

Optional fields:

```yaml
priority: 50
enabled: true
language: zh-CN
rateLimit:
  perHostConcurrency: 1
  minIntervalMs: 800
proxy:
  mode: auto
  required: false
browser:
  mode: manual
  reason: login_or_verification
accessStrategy:
  search: search_engine
  detail: stealth_http
  toc: stealth_http
  chapter: stealth_http
searchEngine:
  providerOrder:
    - duckduckgo_html
    - bing_html
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

`accessStrategy` is the optional final runtime route for each source lifecycle
stage. Valid routes are `http`, `stealth_http`, `search_engine`, `browser`, and
`cf_challenge`. A finished source should declare the intended route instead of
keeping hidden permanent fallback chains.

`searchEngine` is optional Browser Bridge search-engine configuration. Browser
Bridge owns Bing/DuckDuckGo/other search-engine parsing; individual source
plugins should only map returned hits into source result objects.

## source.py Class

Each plugin exports a `Source` class.

Required class fields:

```python
class Source:
    id = "qidian"
    name = "起点中文网"
    contract_version = "1.0"
```

Lifecycle methods must be async when declared in metadata capabilities:

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

`explore` is the source discovery lifecycle. It covers Reading/Legado
`enabledExplore`, `exploreUrl`, and `ruleExplore` equivalents such as ranking
lists, category pages, completed-book lists, and new-book shelves. A plugin that
declares `explore` must provide both `explore_groups` and `explore`. The loader
validates this pair.

Optional auth methods:

```python
async def auth_status(self, ctx) -> dict:
    ...

async def prepare_login(self, ctx) -> dict:
    ...

async def after_login(self, ctx) -> dict:
    ...
```

Do not require official-source login in Stage 1 plugins unless the user explicitly selects that plugin for login support. Stage 1 should define the contract and console UI hooks for login.

## Smoke Fixture Contract

Each plugin should provide `tests/smoke.yaml`. Normal test and console smoke runs use local fixture files by default; live-network checks must be opt-in.

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

Fixture files live under `tests/fixtures/` inside the plugin directory. URLs in `fixtures.*.url` must match the URLs requested by the plugin parser exactly. The fixture runner replaces network fetch with fixture fetch, but the plugin still calls only `ctx.fetch_text`, `ctx.fetch_json`, or `ctx.fetch_bytes`.

Smoke result shape:

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

Fixture smoke errors use normal plugin error codes plus:

- `SMOKE_CONTRACT_ERROR`: fixture output does not match the declared expectation.
- `SMOKE_FIXTURE_MISSING`: smoke spec or fixture files are missing or malformed.

## Standard Data Shapes

Search result:

```python
{
    "sourceId": "qidian",
    "name": "书名",
    "author": "作者",
    "bookUrl": "https://...",
    "coverUrl": "https://...",
    "intro": "简介",
    "kind": "分类/状态/来源",
    "lastChapter": "最新章节",
    "wordCount": "123万字",
    "score": 0.0,
    "extra": {},
}
```

Explore group:

```python
{
    "sourceId": "qidian",
    "groupId": "rank_all",
    "title": "总排行榜",
    "url": "https://...",
    "kind": "rank",          # rank/category/full/new/other
    "pageable": True,
    "profile": "mobile",     # optional domain profile id
    "extra": {},
}
```

Explore item:

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

Explore items intentionally reuse the search-result shape where possible so the
same detail/toc/chapter reader verification can run after either discovery or
search.

Book detail:

```python
{
    "sourceId": "qidian",
    "name": "书名",
    "author": "作者",
    "bookUrl": "https://...",
    "coverUrl": "https://...",
    "intro": "简介",
    "kind": "分类/状态/来源",
    "lastChapter": "最新章节",
    "wordCount": "123万字",
    "tocUrl": "https://...",
    "authRequired": False,
    "extra": {},
}
```

TOC item:

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

Chapter content:

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

Auth status:

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

Login preparation:

```python
{
    "sourceId": "qidian",
    "mode": "manual_browser",
    "loginUrl": "https://www.qidian.com",
    "instructions": "在打开的浏览器中完成登录，然后回到后台点击检测登录状态。",
    "cookieDomains": ["qidian.com"],
}
```

## Runtime Context API

Network:

```python
await ctx.fetch_text(url, method="GET", params=None, data=None, json=None, headers=None, timeout=None, impersonate=None, browser=False, wait_ms=2500)
await ctx.fetch_json(url, method="GET", params=None, data=None, json=None, headers=None, timeout=None, impersonate=None)
await ctx.fetch_bytes(url, method="GET", params=None, data=None, json=None, headers=None, timeout=None, impersonate=None)
await ctx.fetch_many(requests, limit=None)
```

`impersonate` is an optional runtime-controlled browser fingerprint hint for
special sites. It currently uses the backend Fetcher implementation and may
require `curl_cffi`. Plugins may request it, but they still must not create
their own HTTP/proxy sessions.

`browser=True` requests a runtime-owned headless browser fetch. This is for
sites where cookies alone are insufficient and the response depends on a real
browser context, such as Aegis-style verification. Runtime owns Playwright
process creation, proxy, timeout, temporary browser profile cleanup, and
challenge classification. Plugins may request browser fetching but must not
launch Playwright, store browser profiles, or override concurrency/retry policy.

Parsing:

```python
ctx.select(html_or_node, selector)
ctx.text(html_or_node, selector=None)
ctx.html(html_or_node, selector=None)
ctx.attr(html_or_node, selector, name)
ctx.json_path(data, path)
ctx.regex(text, pattern, group=1, default="")
```

Utilities:

```python
ctx.urljoin(base, href)
ctx.clean_html(html)
ctx.clean_text(text)
ctx.decode_text(content_bytes, charset=None)
ctx.trace(stage, url="", message="", data=None)
ctx.cache_get(key)
ctx.cache_set(key, value, ttl_seconds)
```

Auth/session:

```python
ctx.cookies.get(domain, name=None)
ctx.cookies.set(domain, cookie)
ctx.cookies.clear(domain=None)
await ctx.auth_status()
await ctx.request_manual_login(login_url, cookie_domains, message="")
```

Browser/manual-login support is a controlled runtime feature. Plugins may request it, but the console/backend decides how to present and execute it.

## Error Codes

Plugins should raise or return structured failures that core normalizes to:

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

Do not hide auth or payment requirements as parse failures.

## Official And Login-Based Sources

Official sources such as 起点、番茄、七猫、QQ 阅读 may require login, cookies, anti-bot checks, paid-chapter access, or mobile/API signatures.

The plugin contract supports them through:

- `auth` metadata.
- `auth_status`.
- `prepare_login`.
- `after_login`.
- `ctx.cookies`.
- `ctx.request_manual_login`.
- `authRequired`, `isVip`, `isLocked`, and `isPaid` output fields.
- console UI actions for "打开登录", "检测登录状态", "清除 Cookie", "重试章节".

### Browser Challenge Sessions

Cloudflare and similar browser challenges are recoverable runtime states, not
ordinary parser failures. When `ctx.fetch_text/json/bytes` or plugin code raises
`CLOUDFLARE_REQUIRED` / `BROWSER_REQUIRED`, the scheduler must create a browser
challenge session and expose it in:

- `debug.errors[].extra.browserChallenge`
- `debug.browserChallenges[]`
- console search job `source_done` / `source_error` events
- Reading-compatible aggregate API responses under `/api/legado/*`

The standard challenge shape is:

```json
{
  "sessionId": "uuid",
  "sourceId": "69shuba_com",
  "sourceName": "69书吧",
  "type": "cloudflare",
  "reason": "CLOUDFLARE_REQUIRED",
  "stage": "search",
  "status": "pending",
  "openUrl": "https://www.69shuba.com",
  "cookieDomains": ["69shuba.com", "www.69shuba.com"],
  "actions": {
    "submitCookies": "/api/console/browser-challenges/{sessionId}/cookies",
    "status": "/api/console/browser-challenges/{sessionId}",
    "openBrowser": "/api/console/browser-challenges/{sessionId}/browser/open",
    "browserStatus": "/api/console/browser-challenges/{sessionId}/browser/status",
    "importBrowserCookies": "/api/console/browser-challenges/{sessionId}/browser/import-cookies",
    "retryLiveCheck": "/api/console/browser-challenges/{sessionId}/retry-live-check",
    "retryHint": "完成验证并提交 Cookie 后，重新发起搜索、详情、目录或正文请求。"
  }
}
```

Runtime owns the browser challenge lifecycle. A plugin may declare
`browser.mode: required` and may raise the structured error, but it must not own
browser process control, retry scheduling, concurrency, timeout, proxy, cache, or
cookie persistence policy. After a user completes verification in a real
browser, the console or compatible client submits browser cookies to
`POST /api/console/browser-challenges/{sessionId}/cookies`. Runtime stores those
cookies in `PluginAuthRepository`; subsequent calls for that plugin receive the
stored cookies automatically.

For local console usage, runtime may also launch a controlled visible browser
helper through `POST /api/console/browser-challenges/{sessionId}/browser/open`.
The helper is outside the plugin sandbox: it opens the challenge URL in a real
browser, periodically writes browser cookies to a local challenge file, and the
console imports those cookies through
`POST /api/console/browser-challenges/{sessionId}/browser/import-cookies`. This
keeps browser control, cookie persistence, and post-verification retry owned by
LegadoHub core rather than by source plugins.

When the runtime source pool proxy is enabled, the helper browser must use the
same proxy server. This keeps proxy policy centralized in runtime and avoids
special sites such as `twkan.com` or `69shuba.com` silently switching between
different network paths during browser verification.

Some sites require browser context for normal reads, not only for manual
challenge recovery. For these, metadata may declare `browser.mode: required`,
and plugin code may use `ctx.fetch_text(..., browser=True)`. Runtime gives these
sources a separate `browser_source_timeout_seconds` budget while ordinary HTTP
sources keep the normal `source_timeout_seconds` budget.

Stage 1 requirement:

- Implement the contract and console UI hooks.
- Do not require working paid-content extraction from official sources.
- If an official source plugin is created, it may support search/detail/toc for free metadata first and return `AUTH_REQUIRED` or `PAID_CONTENT_REQUIRED` for locked chapters.

## Multi-Domain And Proxy Source Rules

A plugin represents one site family, not necessarily one hostname. It may keep
multiple mirror or historical domains in one plugin when the parsing rules are
substantially identical and the plugin can safely fall back from one base URL to
another.

Rules:

- If a single domain/profile cannot be reached, the plugin may try another
  declared domain profile for the same lifecycle method.
- Fallback is local to site-specific URL construction and parsing. Global
  concurrency, timeout, retry, proxy, cache, and health scoring remain runtime
  responsibilities.
- If mobile and desktop domains have substantially different DOM/API shapes,
  prefer separate plugins or clearly separated internal profiles. Do not mix two
  unrelated parser shapes in one hard-to-maintain method.
- If two domains share a brand but have different verification behavior and DOM,
  such as `www.69shuba.com` and `69shuba.tw`, they should be separate plugins
  rather than one multi-domain plugin.
- `metadata.proxy.required: true` marks sources that should normally use the
  runtime proxy path. Plugins still call only `ctx.fetch_*`; they must not create
  their own proxy clients.
- `metadata.proxy.mode` may be `auto`, `always`, or `never`. Runtime code decides
  how to honor it with the configured proxy URL.

The live acceptance path for sources with `explore` is:

1. `explore_groups`
2. `explore` to pick a discovered/ranked book
3. `detail`
4. `toc`
5. `chapter`
6. `search` using the discovered book name
7. repeat `detail -> toc -> chapter` from the search candidate

## Compatibility Strategy

The contract is versioned.

- Stage 1 accepts only `contractVersion: "1.0"`.
- Future engines can add optional fields.
- Existing fields must not be renamed without a migration.
- New lifecycle methods must be optional.
- Old plugins should keep working when new capabilities are added.

The aggregate Reading/Legado source remains a compatibility shell. It should not expose plugin internals directly.

## Dependency Policy

This is a private project. If a plugin or frontend task needs a dependency, install it and record it.

Rules:

- Backend Python dependencies go in `backend/requirements.txt`.
- Frontend dependencies go in `frontend/package.json`.
- Prefer shared runtime dependencies over per-plugin duplication.
- If a plugin needs a special dependency, add `requirements.txt` in the plugin directory and document it in the plugin README.
- Report dependency installation failures with the exact command and error.
