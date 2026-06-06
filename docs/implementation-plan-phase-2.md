# Phase 2 Implementation Plan

> **For Kimi:** Implement this plan task-by-task. Do not skip validation. Do not commit or push unless the user explicitly asks.

**Goal:** Build the first real Legado source parsing MVP for LegadoHub: load a curated pool of 20 Legado sources, execute concurrent search with failure isolation, and complete at least one real search-to-content reading path through both API and Web debug UI.

**Architecture:** Use a small rule/runtime layer instead of hard-coding one website. Phase 2 should support only the minimum Legado syntax needed by the selected sources, but the execution model must already assume many sources: bounded concurrency, per-source timeout, structured errors, and source-level enable/disable. Web UI is a server-side debug surface, not a full management console.

**Tech Stack:** Python 3.12+, FastAPI, Uvicorn, SQLite, httpx, selectolax or BeautifulSoup4, lxml, jsonpath-ng if needed, pytest.

---

## Phase 2 Scope

Phase 2 must deliver:

- Load a curated candidate pool of 20 Legado source files from `data/sources/raw/by-site/legado/`.
- Run concurrent search across enabled sources with per-source timeout and error capture.
- Support optional proxy fallback: if a source fails because of access restriction or network failure, retry that source through a configured proxy and record proxy success state.
- Support user-forced proxy mode per source.
- Convert successful search results into stable LegadoHub book IDs.
- Fetch book detail, TOC, and one chapter content for at least one real source.
- Return real data from existing reading-facing endpoints:
  - `GET /api/legado/search`
  - `GET /api/legado/book/{book_id}`
  - `GET /api/legado/book/{book_id}/toc`
  - `GET /api/legado/chapter/{chapter_id}`
- Add a backend Web debug UI for search, book detail, TOC, and chapter content.
- Store enough SQLite cache/state to avoid losing selected result context between search, detail, toc, and content calls.

Phase 2 must not deliver:

- Full compatibility with every Legado rule syntax.
- Full Web management console.
- Full source governance/scoring dashboard.
- So Novel adapter.
- AI correction.
- Docker packaging.
- Loading all 2307 Legado site files by default.

## Curated Candidate Pool

Use these 20 source files as the initial Phase 2 candidate pool. Kimi must run a preflight against all 20 and may mark unreachable or unsupported ones as disabled in config, but must not silently delete them.

Primary candidates:

1. `data/sources/raw/by-site/legado/biquge365.net.json`
2. `data/sources/raw/by-site/legado/bbiquge8.net.json`
3. `data/sources/raw/by-site/legado/00xs.net.json`
4. `data/sources/raw/by-site/legado/bbiquge.cc.json`
5. `data/sources/raw/by-site/legado/bbiquge.com.json`
6. `data/sources/raw/by-site/legado/bbiquge.json`
7. `data/sources/raw/by-site/legado/biquges123.com.json`
8. `data/sources/raw/by-site/legado/xiybook.com.json`
9. `data/sources/raw/by-site/legado/23dushu.net.json`
10. `data/sources/raw/by-site/legado/siluwu.com.json`
11. `data/sources/raw/by-site/legado/m.siluke.cc.json`
12. `data/sources/raw/by-site/legado/m.kanshuba.org.json`
13. `data/sources/raw/by-site/legado/m.iquanben.net.json`
14. `data/sources/raw/by-site/legado/hetus1.com.json`
15. `data/sources/raw/by-site/legado/ibiquta.info.json`
16. `data/sources/raw/by-site/legado/qixinge.com.json`
17. `data/sources/raw/by-site/legado/drxsw.com.json`
18. `data/sources/raw/by-site/legado/ttd3.cn.json`
19. `data/sources/raw/by-site/legado/lwxstxt.com.json`
20. `data/sources/raw/by-site/legado/m.63shu.com.json`

If a duplicate candidate is found during implementation, replace the duplicate with the next source that passes the same static checks:

- Has `bookSourceName`, `bookSourceUrl`, `searchUrl`, `ruleSearch`, `ruleBookInfo`, `ruleToc`, and `ruleContent`.
- File size under 50 KB.
- Rule JSON does not require login, captcha, WebView-only execution, or large `@js` blocks for the main search path.
- Avoid adult-only sources as default enabled candidates.

## Configuration

Create `config/phase2_sources.json`:

```json
{
  "max_concurrency": 6,
  "source_timeout_seconds": 8,
  "overall_search_timeout_seconds": 15,
  "default_user_agent": "Mozilla/5.0 (Linux; Android 12; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36",
  "proxy": {
    "enabled": false,
    "url": "",
    "retry_on_failure": true,
    "failure_status_codes": [403, 429, 451, 502, 503, 504],
    "failure_error_keywords": ["timeout", "connection", "reset", "forbidden", "captcha", "blocked"]
  },
  "sources": [
    {
      "id": "biquge365-net",
      "path": "data/sources/raw/by-site/legado/biquge365.net.json",
      "enabled": true,
      "priority": 100,
      "proxy_mode": "auto"
    }
  ]
}
```

The final file must contain 20 unique entries. `id` must be stable, ASCII, and safe for URLs.

`proxy_mode` values:

- `auto`: default. First request without proxy; if access fails and global proxy is configured, retry once through proxy.
- `always`: user-forced proxy. Always use proxy for this source.
- `never`: never use proxy for this source, even if global proxy is configured.

Proxy URL examples:

- `http://127.0.0.1:7890`
- `socks5://127.0.0.1:7890`

Do not hard-code a proxy URL. Empty proxy config must keep normal direct access behavior unchanged.

## File Map

Create:

- `app/rules/__init__.py`
- `app/rules/models.py`
- `app/rules/legado_loader.py`
- `app/rules/legado_adapter.py`
- `app/engine/__init__.py`
- `app/engine/fetcher.py`
- `app/engine/extractor.py`
- `app/engine/legado_executor.py`
- `app/services/__init__.py`
- `app/services/source_pool.py`
- `app/services/catalog.py`
- `app/services/cache.py`
- `app/web/__init__.py`
- `app/web/debug.py`
- `config/phase2_sources.json`
- `tests/test_phase2_sources.py`
- `tests/test_extractor.py`
- `tests/test_legado_executor.py`
- `tests/test_catalog_api.py`
- `docs/phase-2-verification.md`

Modify:

- `requirements.txt`
- `app/main.py`
- `app/api/legado.py`
- `app/storage/db.py`
- `docs/project-plan.md`

## Data Contracts

Use these internal response shapes. Field names must remain stable because the aggregate source and Web UI depend on them.

Search response:

```json
{
  "implemented": true,
  "keyword": "凡人修仙传",
  "page": 1,
  "items": [
    {
      "bookId": "source-id:encoded-book-url",
      "name": "凡人修仙传",
      "author": "忘语",
      "coverUrl": "",
      "intro": "",
      "kind": "",
      "lastChapter": "",
      "wordCount": "",
      "bookUrl": "https://example.com/book/1/",
      "sourceId": "biquge365-net",
      "sourceName": "笔趣阁",
      "score": 100
    }
  ],
  "debug": {
    "sourceCount": 20,
    "successCount": 3,
    "errorCount": 17,
    "elapsedMs": 1234,
    "errors": [
      {
        "sourceId": "source-id",
        "stage": "search",
        "url": "https://example.com/search",
        "proxyUsed": false,
        "error": "timeout"
      }
    ]
  }
}
```

Book detail response:

```json
{
  "implemented": true,
  "data": {
    "bookId": "source-id:encoded-book-url",
    "name": "",
    "author": "",
    "coverUrl": "",
    "intro": "",
    "kind": "",
    "lastChapter": "",
    "wordCount": "",
    "tocUrl": "",
    "sourceId": "",
    "sourceName": ""
  },
  "debug": {}
}
```

TOC response:

```json
{
  "implemented": true,
  "bookId": "",
  "chapters": [
    {
      "chapterId": "source-id:encoded-chapter-url",
      "title": "",
      "chapterUrl": "",
      "updateTime": "",
      "sourceId": ""
    }
  ],
  "debug": {}
}
```

Chapter response:

```json
{
  "implemented": true,
  "chapterId": "",
  "title": "",
  "content": "",
  "debug": {}
}
```

## Parser MVP Rules

Implement only these rule capabilities in Phase 2:

- URL template replacement for `{{key}}`, `{{page}}`, and relative URLs against `bookSourceUrl`.
- Request specs in Legado strings like `url,{ "method": "POST", "body": "...", "charset": "gbk" }`.
- GET and POST.
- Request charset decoding for UTF-8 and GBK.
- CSS selector extraction.
- XPath extraction.
- Basic text extraction, attribute extraction, and absolute URL normalization.
- Basic list extraction for `ruleSearch.bookList` and `ruleToc.chapterList`.
- Basic `replaceRegex` cleanup for content.

If a source requires unsupported syntax, return a structured debug error:

```json
{
  "sourceId": "source-id",
  "stage": "search",
  "url": "",
  "error": "unsupported rule syntax: @js"
}
```

Do not pretend unsupported sources succeeded.

## Concurrency Model

`app/services/catalog.py` must run search through a bounded worker model:

- Use `asyncio` plus `httpx.AsyncClient`.
- Default `max_concurrency` is 6.
- Each source gets `source_timeout_seconds`.
- Overall search should stop at `overall_search_timeout_seconds`.
- Failure in one source must not fail the whole search.
- If `proxy_mode` is `auto`, proxy retry must happen inside the same source worker and still respect that source's timeout budget.
- If `proxy_mode` is `always`, direct access must be skipped and debug output must include `proxyUsed: true`.
- If proxy retry succeeds after direct failure, the source result must include `proxyUsed: true`, and source state must record that proxy succeeded.
- Results should be returned as they are collected, sorted by:
  1. exact keyword match in `name`
  2. source priority
  3. non-empty author / lastChapter / intro

This model is required now so Phase 3 can scale to many sources without rewriting the API layer.

## Proxy Fallback

Create a small proxy decision layer inside `app/engine/fetcher.py` or a focused helper module:

- Inputs:
  - source ID
  - source `proxy_mode`
  - global proxy config
  - request stage: `search`, `book`, `toc`, or `content`
- Behavior:
  - `never`: one direct attempt only.
  - `always`: one proxy attempt only.
  - `auto`: one direct attempt, then one proxy attempt only when the direct attempt fails with a configured failure status code or network/access error.
- Output:
  - response body and metadata when successful.
  - structured error when both direct and proxy attempts fail.
  - metadata fields: `proxyUsed`, `attempts`, `directError`, `proxyError`.

Source state rules:

- When proxy retry succeeds for a source, persist `proxy_status = "proxy_succeeded"`.
- When proxy is user-forced, persist `proxy_status = "forced_proxy"`.
- When direct access succeeds, persist `proxy_status = "direct_ok"`.
- When direct and proxy both fail, persist `proxy_status = "proxy_failed"` if proxy was attempted, otherwise `proxy_status = "direct_failed"`.

The Web debug UI must show each source's current proxy status and whether a given request used proxy.

## SQLite Cache

Extend initialization in `app/storage/db.py` with idempotent tables:

- `search_cache`
  - `keyword TEXT`
  - `page INTEGER`
  - `response_json TEXT`
  - `created_at TEXT`
- `book_cache`
  - `book_id TEXT PRIMARY KEY`
  - `source_id TEXT`
  - `book_url TEXT`
  - `response_json TEXT`
  - `created_at TEXT`
- `toc_cache`
  - `book_id TEXT PRIMARY KEY`
  - `response_json TEXT`
  - `created_at TEXT`
- `chapter_cache`
  - `chapter_id TEXT PRIMARY KEY`
  - `source_id TEXT`
  - `chapter_url TEXT`
  - `response_json TEXT`
  - `created_at TEXT`
- `source_runtime_state`
  - `source_id TEXT PRIMARY KEY`
  - `proxy_mode TEXT`
  - `proxy_status TEXT`
  - `last_direct_error TEXT`
  - `last_proxy_error TEXT`
  - `last_success_via_proxy INTEGER`
  - `updated_at TEXT`

Cache TTL may be simple in Phase 2:

- Search: 10 minutes.
- Book detail: 1 day.
- TOC: 1 hour.
- Chapter: 7 days.

## API Integration

Modify `app/api/legado.py`:

- `/api/legado/search` must call the catalog search service and return real data.
- `/api/legado/book/{book_id}` must fetch detail using cached source context.
- `/api/legado/book/{book_id}/toc` must fetch TOC using cached book context.
- `/api/legado/chapter/{chapter_id}` must fetch chapter content using cached chapter context.
- Keep `implemented: true` only when a route is wired to the real service path.

Update aggregate source rules if needed so Reading/Legado can consume the new response shapes.

## Web Debug UI

Add routes in `app/web/debug.py`:

- `GET /debug`
- `GET /debug/search?keyword=...`
- `GET /debug/book/{book_id}`
- `GET /debug/book/{book_id}/toc`
- `GET /debug/chapter/{chapter_id}`

Use simple server-rendered HTML returned by FastAPI. Do not add a frontend build chain.

The UI must show:

- Search input.
- Search results table.
- Source name and source ID.
- Proxy mode and proxy status for each source result.
- Links to detail, TOC, and content.
- Debug summary: elapsed time, success count, error count.
- Per-source errors with source ID, stage, URL, proxy-used flag, and message.

## Validation Commands

Kimi must run:

```powershell
python -m pip install -r requirements.txt
python -m pytest tests -v
python -c "from app.storage.db import initialize_database; print(initialize_database())"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8765
```

Proxy behavior tests must be included in automated tests. At minimum:

- A source with `proxy_mode: "never"` does not use proxy.
- A source with `proxy_mode: "always"` uses proxy on the first attempt.
- A source with `proxy_mode: "auto"` retries through proxy after a simulated 403/timeout.
- When proxy retry succeeds, runtime state records `proxy_status = "proxy_succeeded"`.

In a second terminal:

```powershell
@'
import json
from urllib.parse import quote
from urllib.request import urlopen

base = "http://127.0.0.1:8765"

with urlopen(base + "/api/legado/search?keyword=" + quote("凡人修仙传") + "&page=1", timeout=30) as response:
    search = json.loads(response.read().decode("utf-8"))
print("search implemented:", search.get("implemented"))
print("items:", len(search.get("items", [])))
print("debug:", search.get("debug", {}))
assert search.get("implemented") is True
assert search.get("items")

book_id = search["items"][0]["bookId"]
with urlopen(base + "/api/legado/book/" + quote(book_id, safe=""), timeout=30) as response:
    book = json.loads(response.read().decode("utf-8"))
print("book:", book.get("data", {}).get("name"))
assert book.get("implemented") is True

with urlopen(base + "/api/legado/book/" + quote(book_id, safe="") + "/toc", timeout=30) as response:
    toc = json.loads(response.read().decode("utf-8"))
print("chapters:", len(toc.get("chapters", [])))
assert toc.get("implemented") is True
assert toc.get("chapters")

chapter_id = toc["chapters"][0]["chapterId"]
with urlopen(base + "/api/legado/chapter/" + quote(chapter_id, safe=""), timeout=30) as response:
    chapter = json.loads(response.read().decode("utf-8"))
print("chapter:", chapter.get("title"), len(chapter.get("content", "")))
assert chapter.get("implemented") is True
assert chapter.get("content")
'@ | python -
```

Also validate:

```powershell
python docs/skills/book-source-craft/scripts/inspect_legado_source.py generated/legadohub-source.json
```

Manual checks:

- Open `http://127.0.0.1:8765/debug`.
- Search for a known title.
- Open the first result.
- Open TOC.
- Open a chapter.
- Import the LAN source URL in Reading/Legado and verify at least one book can reach chapter content.

## Final Phase 2 Acceptance Report

Kimi must report:

1. Full file change list.
2. Dependency changes.
3. The final 20 configured candidate source IDs and paths.
4. Which sources passed preflight and which were disabled, with reasons.
5. Exact commands run.
6. Test results.
7. API smoke output for search, book, TOC, and chapter.
8. Web debug UI manual verification result.
9. Reading/Legado import and chapter-content verification result.
10. Proxy config used for validation, or explicit statement that proxy URL was not configured.
11. Proxy behavior test results, including at least one simulated auto-fallback success.
12. Runtime proxy status examples from Web debug UI or API debug output.
13. Unsupported syntax list found during Phase 2.
14. Known limitations and recommended Phase 3 follow-up.

Codex will review against this plan and decide whether Phase 2 is accepted.
