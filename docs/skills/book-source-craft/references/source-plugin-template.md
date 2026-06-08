# Source Plugin Template

Use this as the starting point for LegadoHub-native Python source plugins.

## Directory Shape

```text
plugins/sources/example_plugin/
  metadata.yaml
  source.py
  README.md
  tests/
    smoke.yaml
```

## metadata.yaml

```yaml
contractVersion: "1.0"
id: example_plugin
name: 示例书源
version: 0.1.0
type: source
domains:
  - example.com
baseUrls:
  - https://example.com
capabilities:
  - search
  - detail
  - toc
  - chapter
auth:
  mode: none
  cookieDomains: []
content:
  access: free
tags:
  - html
  - no-login
```

Field rules:

- `id`: stable ASCII identifier, unique across plugins.
- `name`: display name shown in the console.
- `version`: plugin version, increment when behavior changes.
- `contractVersion`: must be `"1.0"` for Stage 1.
- `domains`: domains this plugin is expected to access.
- `baseUrls`: canonical site entry URLs.
- `capabilities`: supported lifecycle methods.
- `auth.mode`: `none`, `optional`, `required`, or `manual`.
- `content.access`: `free`, `paid`, `mixed`, or `unknown`.
- `tags`: operational hints such as `html`, `json-api`, `proxy`, `cloudflare`, `login`, `special`.

## source.py

```python
class Source:
    id = "example_plugin"
    name = "示例书源"
    contract_version = "1.0"
    base_url = "https://example.com"

    async def search(self, ctx, keyword: str, page: int):
        html = await ctx.fetch_text(
            f"{self.base_url}/search",
            params={"q": keyword, "page": page},
        )
        items = []
        for node in ctx.select(html, ".result-item"):
            items.append({
                "sourceId": self.id,
                "name": ctx.text(node, ".title"),
                "author": ctx.text(node, ".author"),
                "bookUrl": ctx.urljoin(self.base_url, ctx.attr(node, "a", "href")),
                "coverUrl": ctx.urljoin(self.base_url, ctx.attr(node, "img", "src")),
                "intro": ctx.text(node, ".intro"),
                "kind": ctx.text(node, ".kind"),
                "lastChapter": ctx.text(node, ".latest"),
            })
        return items

    async def detail(self, ctx, book_url: str):
        html = await ctx.fetch_text(book_url)
        return {
            "sourceId": self.id,
            "name": ctx.text(html, "h1"),
            "author": ctx.text(html, ".author").replace("作者：", "").strip(),
            "coverUrl": ctx.urljoin(book_url, ctx.attr(html, ".cover img", "src")),
            "intro": ctx.text(html, ".intro"),
            "kind": ctx.text(html, ".kind"),
            "lastChapter": ctx.text(html, ".latest"),
            "tocUrl": book_url,
            "authRequired": False,
        }

    async def toc(self, ctx, book_url: str):
        html = await ctx.fetch_text(book_url)
        chapters = []
        for index, node in enumerate(ctx.select(html, "#list dd"), start=1):
            chapters.append({
                "sourceId": self.id,
                "index": index,
                "title": ctx.text(node, "a"),
                "chapterUrl": ctx.urljoin(book_url, ctx.attr(node, "a", "href")),
                "isVip": False,
                "isLocked": False,
            })
        return chapters

    async def chapter(self, ctx, chapter_url: str):
        html = await ctx.fetch_text(chapter_url)
        return {
            "sourceId": self.id,
            "title": ctx.text(html, "h1"),
            "content": ctx.clean_html(ctx.html(html, "#content")),
            "chapterUrl": chapter_url,
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }
```

## tests/smoke.yaml

```yaml
keyword: 凡人修仙传
expect:
  search_min_items: 1
  detail_has:
    - name
    - author
    - tocUrl
  toc_min_chapters: 1
  chapter_min_chars: 200
```

## Special-Site Overrides

For special sites, keep custom logic inside the lifecycle method but keep network access through `ctx`.

```python
async def chapter(self, ctx, chapter_url: str):
    html = await ctx.fetch_text(chapter_url)
    token = self._extract_token(html)
    payload = self._decrypt_payload(html, token)
    return {
        "title": ctx.text(html, "h1"),
        "content": ctx.clean_text(payload),
        "chapterUrl": chapter_url,
    }
```

Do not start unmanaged threads, create global HTTP clients, or implement source-level concurrency in the plugin.

## Login/Auth Hooks

For official or login-based sources, declare auth in `metadata.yaml` and implement optional hooks.

```yaml
auth:
  mode: optional
  loginUrl: https://www.qidian.com
  accountRequiredFor:
    - paid_chapter
  cookieDomains:
    - qidian.com
content:
  access: mixed
  paid: supported_after_login
tags:
  - official
  - login
  - paid
```

```python
async def auth_status(self, ctx):
    cookie = ctx.cookies.get("qidian.com")
    return {
        "sourceId": self.id,
        "authenticated": bool(cookie),
        "accountName": "",
        "expiresAt": "",
        "message": "已检测到 Cookie" if cookie else "未登录",
        "requiredActions": [] if cookie else ["manual_login"],
    }

async def prepare_login(self, ctx):
    return {
        "sourceId": self.id,
        "mode": "manual_browser",
        "loginUrl": "https://www.qidian.com",
        "instructions": "在打开的浏览器中完成登录，然后回到后台点击检测登录状态。",
        "cookieDomains": ["qidian.com"],
    }
```

Locked chapters should return structured auth/payment fields instead of pretending parse failed.
