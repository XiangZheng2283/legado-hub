# Plugin Source Workflow

Use this workflow for LegadoHub-native Python source plugin creation.

## 1. Target Check

Start from one concrete target:

- Website home URL.
- Search result URL.
- Book detail URL.
- Chapter list URL.
- Chapter content URL.
- Existing Reading source JSON or So Novel rule used only as a reference.

Check live pages with evidence:

```powershell
curl.exe -I -L --connect-timeout 10 --max-time 15 "https://example.com"
curl.exe -L --connect-timeout 10 --max-time 15 "https://example.com" | Select-Object -First 40
```

Confirm:

- HTTP status and redirects.
- Charset: UTF-8, GBK, GB2312, Big5, etc.
- Mobile vs desktop layout differences.
- Whether search exists.
- Whether pages require cookies, headers, proxy, WebView-style JS, Cloudflare, login, or rate limits.

## 2. Metadata Module

Create `metadata.yaml` before writing parser code:

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

Use stable ASCII IDs. Use Chinese for display names when useful.

Follow `docs/architecture/source-plugin-contract.md`. Do not invent plugin fields during adaptation.

If the site needs a new Python dependency, install it and record it in `backend/requirements.txt` or plugin-local `requirements.txt`.

## 3. Search Module

Identify:

- Search method: GET, POST, JSON API, or unavailable.
- Query parameter name.
- Page parameter name.
- Result item selector or JSON path.
- Detail URL extraction.

Plugin shape:

```python
async def search(self, ctx, keyword: str, page: int):
    html = await ctx.fetch_text(
        self.search_url,
        params={"q": keyword, "page": page},
    )
    items = ctx.select(html, ".result-item")
    return [
        {
            "sourceId": self.id,
            "name": ctx.text(item, ".title"),
            "author": ctx.text(item, ".author"),
            "bookUrl": ctx.urljoin(self.base_url, ctx.attr(item, "a", "href")),
            "coverUrl": ctx.urljoin(self.base_url, ctx.attr(item, "img", "src")),
            "intro": ctx.text(item, ".intro"),
            "kind": ctx.text(item, ".kind"),
            "lastChapter": ctx.text(item, ".latest"),
        }
        for item in items
    ]
```

If search is unavailable, explicitly declare that in metadata or plugin capabilities instead of returning fake data.

## 4. Detail Module

Identify:

- Book name.
- Author.
- Cover.
- Intro.
- Latest chapter.
- TOC URL.

Plugin shape:

```python
async def detail(self, ctx, book_url: str):
    html = await ctx.fetch_text(book_url)
    return {
        "sourceId": self.id,
        "name": ctx.text(html, "h1"),
        "author": ctx.text(html, ".author").replace("作者：", "").strip(),
        "coverUrl": ctx.urljoin(book_url, ctx.attr(html, ".cover img", "src")),
        "intro": ctx.text(html, ".intro"),
        "lastChapter": ctx.text(html, ".latest"),
        "tocUrl": book_url,
        "authRequired": False,
    }
```

## 5. Toc Module

Identify:

- Chapter item selector.
- Chapter title selector.
- Chapter URL selector.
- Ordering.
- Multi-page TOC behavior.

Plugin shape:

```python
async def toc(self, ctx, book_url: str):
    html = await ctx.fetch_text(book_url)
    chapters = []
    for index, item in enumerate(ctx.select(html, "#list dd"), start=1):
        chapters.append({
            "sourceId": self.id,
            "index": index,
            "title": ctx.text(item, "a"),
            "chapterUrl": ctx.urljoin(book_url, ctx.attr(item, "a", "href")),
            "isVip": False,
            "isLocked": False,
        })
    return chapters
```

For multi-page TOC, fetch additional pages through `ctx.fetch_text` or a future `ctx.fetch_many`; do not create unmanaged threads or independent async clients.

## 6. Chapter Module

Identify:

- Main content selector.
- Ad nodes or text fragments.
- Next-page behavior.
- Encoding or decryption.

Plugin shape:

```python
async def chapter(self, ctx, chapter_url: str):
    html = await ctx.fetch_text(chapter_url)
    title = ctx.text(html, "h1")
    content = ctx.html(html, "#content")
    content = ctx.clean_html(content)
    return {
        "sourceId": self.id,
        "title": title,
        "content": content,
        "chapterUrl": chapter_url,
        "format": "text",
        "authRequired": False,
        "isPaid": False,
    }
```

For special sites, keep the special logic local but keep network access through `ctx`.

For official/login-based sites, implement `auth_status`, `prepare_login`, or `after_login` only through the contract hooks. Do not open browsers directly inside the plugin.

## 7. Smoke Fixture

Create `tests/smoke.yaml` for each plugin:

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

## 8. Final Delivery

Deliver:

- `metadata.yaml`
- `source.py`
- `tests/smoke.yaml`
- Validation evidence:
  - searched keyword
  - selected book URL
  - selected chapter URL
  - status and error evidence for any failure
  - known fragile selectors or anti-bot notes
