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
enabled: true
proxy:
  mode: auto        # never / auto / always
  required: false
browser:
  mode: none        # none / optional / required
  reason: ""
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
- `explore` is reserved for official/licensed sources such as 起点、七猫、番茄、QQ 阅读. Ordinary mirror or scraper sources must not declare ranking/category discovery.

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
            "wordCount": ctx.text(html, ".word-count"),
            "tocUrl": book_url,
            "authRequired": False,
            "extra": {
                "status": ctx.text(html, ".status"),
                "updateTime": ctx.text(html, ".update-time"),
            },
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
        parts = []
        current_url = chapter_url
        title = ""
        original_stem = self._chapter_stem(chapter_url)
        while current_url and len(parts) < 10:
            html = await ctx.fetch_text(current_url)
            if not title:
                title = ctx.text(html, "h1")
            content_html = ctx.html(html, "#content")
            content = self._clean_chapter_content(content_html)
            if content:
                parts.append(content)
            # Merge same-chapter pagination; stop before the next chapter
            next_href = ctx.attr(html, "#next_url", "href")
            if not next_href or self._chapter_stem(next_href) != original_stem:
                break
            current_url = ctx.urljoin(chapter_url, next_href)
        return {
            "sourceId": self.id,
            "title": title,
            "content": "\n\n".join(parts),
            "chapterUrl": chapter_url,
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _chapter_stem(self, url: str) -> str:
        path = url.split("?")[0].split("#")[0]
        if "_" in path:
            return path.rsplit("_", 1)[0]
        return path.rsplit(".", 1)[0] if "." in path else path

    def _clean_chapter_content(self, html: str) -> str:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "iframe", "ins", "center"]):
            tag.decompose()
        for div in soup.find_all("div"):
            text = div.get_text(strip=True)
            if len(text) < 80 and any(kw in text for kw in ["广告", "声明", "本章结束", "返回目录", "加入书签", "推荐", "最新网址", "章节内容缺失", "章节不存在"]):
                div.decompose()
        for br in soup.find_all("br"):
            br.replace_with("\n")
        paragraphs = []
        for p in soup.find_all("p"):
            text = p.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)
        if paragraphs:
            return "\n\n".join(paragraphs)
        text = soup.get_text("\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n\n".join(lines)
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

## Book Info Field Standard

`detail()` should return the same metadata surface that Reading/Legado consumes
through `ruleBookInfo`. Fill every field that the source page exposes:

- Required baseline: `sourceId`, `name`, `author`, `bookUrl`, `tocUrl`.
- Strongly preferred: `coverUrl`, `intro`, `kind`, `lastChapter`, `wordCount`.
- Put site-specific but useful metadata such as `status`, `updateTime`,
  `lastUpdateTime`, `rating`, or raw tags under `extra`.
- Clean SEO tails, duplicate labels, and site chrome before returning `intro`.
- Search results should use the same field names where available so Reading can
  render a useful list before the user enters the detail page.
- If the search page does not expose standard fields such as `lastChapter`,
  `author`, `coverUrl`, `intro`, `kind`, `wordCount`, or `updateTime`, the
  source plugin must complete them inside its own `search()` method by calling
  its own `detail()` parser for the first few stable candidates. Do not rely on
  the scheduler to fill these fields.
- Source-local detail enrichment should be bounded and non-destructive: only
  candidates with a stable `bookUrl`, short timeout, failure traced but not fatal,
  and only fill empty fields. Mark `extra.detailEnriched = true` when useful.

Recommended helper:

```python
from app.source_plugins.search_enrichment import enrich_search_items_from_detail

async def search(self, ctx, keyword: str, page: int):
    ...
    return await enrich_search_items_from_detail(self, ctx, items)
```

## Catalog Completeness Standard

`toc()` must return the complete catalog in normal reading order. Many mirrored
novel sites render only a static preview containing the first chapters and the
latest chapters, while the complete catalog is loaded by AJAX/API, pagination,
or a "load more" script. In that case:

- Prefer the complete AJAX/API/paginated catalog endpoint.
- If the complete catalog endpoint can be derived from the book URL, try it
  before fetching the static catalog page. Some sites challenge `/book/...`
  pages while leaving `/ajax_novels/chapterlist/...` usable.
- Use the static catalog only as a fallback when the complete endpoint fails.
- Deduplicate by chapter URL.
- Drop `#`, sorting buttons, related-book links, and latest-update blocks.
- Sort by explicit chapter number when the site can toggle normal/reverse order.
- Trace known limitations if the site exposes only a partial catalog.

Before writing selectors for `toc()` or `chapter()`, actively inspect the page
for JSON/AJAX/get endpoints. Common signals include script variables, network
paths containing `api`, `ajax`, `chapterlist`, `chapters`, `content`, `reader`,
or mobile/AMP endpoints. Prefer stable API/AJAX responses over HTML parsing for
complete catalogs and正文内容; use HTML parsing only as a documented fallback.
If endpoint probes return 404/500/challenge pages, keep the probe result in the
validation notes or `ctx.trace()` so the next adapter pass does not repeat blind
guesswork.

Repeated mirror frameworks often show the same traps:

- A "latest chapters" preview appears before the real catalog. Parse by section
  boundary, not just broad selectors such as `#list a`.
- Some HTML is shaped as `<a><dd>title</dd></a>` instead of `<dd><a>title</a></dd>`.
  Validate against live DOM before assuming the framework shape.
- Paginated catalogs may use sibling URLs such as `/book/123-2.html`, not child
  URLs such as `/book/123/123-2.html`. Follow the actual `下一页` link.
- Do not deduplicate catalogs only by chapter number. `番外`, `完结感言`, and other
  unnumbered chapters must be preserved.
- A chapter page may contain a short advertisement `<p>` plus real text nodes.
  Do not let "first `<p>` wins" logic discard the正文.
- If the origin page itself returns缺失、串章、混章正文, the plugin should trace or
  return empty for that chapter rather than caching obviously polluted text as
  valid content. A parser must not fabricate missing正文.

Do not add `explore`, ranking, category, hot-list, or completed-list capability
to ordinary sources. Those lifecycle methods are reserved for official/licensed
sources, because aggregate ranking and chapter metadata must come from official
sources once they are added.

## Chapter Content Standard

`chapter()` must return clean, readable plain text:

- Preserve paragraph boundaries through `<br>`, `<p>`, or block text extraction.
- Merge same-chapter pagination and stop before the next chapter.
- Remove title page markers such as `(1/2)`, `(2/3)`, `（第2页）`.
- Strip script/style/nav/header/footer, ad containers, download prompts,
  recommendation blocks, missing-chapter notices, and site slogans.
- Treat short ad-only content as invalid; do not cache or return it as a
  successful chapter.
- Prefer正文 API/AJAX/get endpoints when available; HTML selectors are the fallback.

## Fallback Strategy Standard

When a site search is blocked or unstable, keep degradation source-local and
predictable:

1. Normal source search through the declared access layer.
2. Browser-rendered search for the same site search URL if a challenge or
   JavaScript-rendered result page is detected.
3. Source-owned ranking/category/recent-update fallback.
4. External search-provider fallback only as the final declared bypass.

HTTP 200 can still be a challenge page. Check returned HTML for challenge
markers before treating a parse miss as an empty result.

Search pages also need a false-positive guard: if the response contains only
generic recommendations, hot books, or fallback navigation and does not contain
an explicit title hit for the queried keyword, return empty or continue to the
declared fallback. Do not treat a recommendation page as a successful search.

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
