# LegadoHub Full Legado Backend Implementation Plan

> **Superseded on 2026-06-07:** This plan is now a historical reference for the pre-port Python backend direction. The active restart direction is `docs/architecture/plugin-source-runtime-restart-plan.md`: LegadoHub moves internal source execution to self-maintained Python source plugins.
>
> **For agentic workers:** This document is no longer the active architecture source of truth. Use it only to understand the previous backend plan and the assets that may still be retained.

**Goal:** Fully implement LegadoHub as a local Reading/Legado-compatible backend and Chinese operations console, covering source subscriptions, source management, single-source invocation, realtime search, discover/ranking, book detail, TOC, chapter reading, failure diagnosis, and verification.

**Architecture:** Use `aoaostar/legado` as the subscription/source-publish reference and `Luoyacheng/legado` as the native Reading rule semantics reference. Keep FastAPI + SQLite + server-rendered Chinese admin UI, but split rule execution into an independent Legado engine package with explicit capability reporting, runtime traces, and source-health feedback.

**Tech Stack:** Python 3.12, FastAPI, SQLite, httpx, lxml/cssselect, jsonpath-ng or equivalent internal JsonPath evaluator, regex, restricted JS runtime, server-rendered HTML, Playwright or in-app browser verification when a dev server is running.

---

## 0. Upstream References

### Local Mirrors

- `data/upstreams/aoaostar-legado`
  - Source: `https://github.com/aoaostar/legado`
  - Role: published source lists, subscription links, import URLs, counts, sync status samples.
  - Important files:
    - `README.md`
    - `index.html`
    - `sources/*.json`
    - `sources/*.zip`
- `data/upstreams/luoyacheng-legado`
  - Source: `https://github.com/Luoyacheng/legado`
  - Role: Reading/Legado native rule execution semantics.
  - Important files:
    - `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeRule.kt`
    - `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeUrl.kt`
    - `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByJSoup.kt`
    - `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByXPath.kt`
    - `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByJSonPath.kt`
    - `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByRegex.kt`
    - `app/src/main/java/io/legado/app/model/webBook/WebBook.kt`
    - `app/src/main/java/io/legado/app/model/webBook/BookList.kt`
    - `app/src/main/java/io/legado/app/model/webBook/BookInfo.kt`
    - `app/src/main/java/io/legado/app/model/webBook/BookChapterList.kt`
    - `app/src/main/java/io/legado/app/model/webBook/BookContent.kt`
    - `app/src/main/java/io/legado/app/help/JsExtensions.kt`
    - `app/src/main/java/io/legado/app/help/source/BookSourceExtensions.kt`
    - `app/src/main/java/io/legado/app/data/entities/BookSource.kt`
    - `app/src/main/java/io/legado/app/data/entities/rule/*.kt`

### Initial Finding

`aoaostar/legado` is not the Reading APP source-code implementation. It is a publishing repository for book sources, RSS sources, replace rules, reading configs, themes, and TTS sources. It still matters because it provides current direct import URLs such as:

- `https://legado.aoaostar.com/sources/b778fe6b.json` full book sources
- `https://legado.aoaostar.com/sources/71e56d4f.json` XIU2 sources
- `https://legado.aoaostar.com/sources/4dc410d1.json` pobing sources
- `https://legado.aoaostar.com/sources/e3e5d620.json` female-channel sources
- `https://legado.aoaostar.com/sources/e29e19ee.json` shidahuilang sources
- `https://legado.aoaostar.com/sources/2a1f129b.json` Coolapk Sanwu sources
- `https://legado.aoaostar.com/sources/3bb7b751.json` open Reading sources

These URLs must be normalized into project-managed source subscriptions, visible and syncable in the backend.

---

## 1. Capability Model

### Feature Areas

1. Source subscriptions
2. Source repository inventory
3. Source health and active pool governance
4. Independent Legado rule engine
5. Request building and HTTP runtime
6. Single-source test and trace
7. Realtime aggregate search
8. Discover/ranking/explore lists
9. Book detail and candidate merging
10. TOC and chapter reading
11. Cache, update tracking, and fallback
12. Chinese admin UI
13. API simulation and UI simulation verification

### Engine Capability Matrix

| Capability | Required Result |
|---|---|
| CSS/JSoup selectors | Independent selector module, native-like segment handling |
| XPath | Main execution path, not helper-only |
| JsonPath | Main execution path for JSON responses |
| Regex | Main execution path with group extraction |
| `||` fallback | Works for list and field extraction |
| `@` field operator | Text/html/href/src/attribute extraction |
| `##` replace rule | Regex replace support |
| `@js:` | Restricted transform execution or structured unsupported reason |
| `<js>` | Restricted transform execution or structured unsupported reason |
| `{{key}}`, `{{page}}` | Request and rule context variable replacement |
| `@get`, `@put` | Rule context storage |
| headers | Parsed from source-level and request-level config |
| cookies | Source-level cookie jar support |
| GET/POST/body | Request builder parity with Reading syntax |
| charset | UTF-8, GBK, GB2312, Big5 where declared |
| explore/ranking | `exploreUrl` parse, grouped lists, pagination |
| login-required | Detect and classify, not silently fail |
| WebView-required | Detect and classify as engine gap/runtime gap |

---

## 2. File Structure

### New or Reworked Backend Modules

- `app/legado_engine/__init__.py`
  - Engine package boundary. No admin/API dependencies.
- `app/legado_engine/models.py`
  - `LegadoSource`, `RequestSpec`, `RuleContext`, `TraceEvent`, `EngineResult`.
- `app/legado_engine/source_adapter.py`
  - Convert raw BookSource JSON to internal model.
- `app/legado_engine/request_builder.py`
  - Parse search/detail/toc/content/explore request specs.
- `app/legado_engine/http_runtime.py`
  - Fetch with charset, headers, cookie jar, proxy mode, trace.
- `app/legado_engine/analyzer.py`
  - Top-level execution pipeline matching Reading stages.
- `app/legado_engine/selectors.py`
  - CSS/JSoup-like selector chains.
- `app/legado_engine/xpath.py`
  - XPath extraction.
- `app/legado_engine/jsonpath.py`
  - JsonPath extraction.
- `app/legado_engine/regex.py`
  - Regex extraction.
- `app/legado_engine/js_runtime.py`
  - Restricted JavaScript transforms.
- `app/legado_engine/context.py`
  - `@put`, `@get`, variables, base URL, result state.
- `app/legado_engine/capabilities.py`
  - Static and runtime capability classification.
- `app/legado_engine/explore.py`
  - Ranking/discover/explore parsing.

### Services

- `app/services/source_subscriptions.py`
  - Expand current implementation with aoaostar direct subscriptions.
- `app/services/source_repository.py`
  - Keep canonical inventory, add source type, subscription ID, import origin, file-level errors.
- `app/services/source_health.py`
  - New focused health state and attempts service.
- `app/services/search_jobs.py`
  - Realtime search job/session state, SSE events, cancellation.
- `app/services/book_catalog.py`
  - Book detail, TOC, content, candidate fallback, reading state.
- `app/services/explore_catalog.py`
  - Rankings/discover lists from `exploreUrl`.
- `app/services/update_scheduler.py`
  - Manual and scheduled update checks.
- `app/services/verification_harness.py`
  - API/UI simulation data and reports.

### APIs

- `app/api/legado.py`
  - Reading-compatible source/search/book/toc/chapter endpoints.
- `app/api/admin.py`
  - Admin CRUD, realtime jobs, source tests, explore, books, scheduler, settings.

### Web UI

- `app/web/layout.py`
  - Shared Chinese admin shell.
- `app/web/components.py`
  - Tables, status tags, forms, trace timelines.
- `app/web/admin.py`
  - Route assembly. Split if file exceeds maintainable size.
- Admin pages:
  - `/admin`
  - `/admin/subscriptions`
  - `/admin/sources`
  - `/admin/sources/{source_id}`
  - `/admin/source-test`
  - `/admin/search`
  - `/admin/explore`
  - `/admin/books`
  - `/admin/books/{book_id}`
  - `/admin/reader`
  - `/admin/update-tasks`
  - `/admin/cache`
  - `/admin/settings`
  - `/admin/verification`

### Tests

- `tests/legado_engine/test_request_builder.py`
- `tests/legado_engine/test_selectors.py`
- `tests/legado_engine/test_jsonpath.py`
- `tests/legado_engine/test_xpath.py`
- `tests/legado_engine/test_regex.py`
- `tests/legado_engine/test_js_runtime.py`
- `tests/legado_engine/test_pipeline_search.py`
- `tests/legado_engine/test_pipeline_detail_toc_content.py`
- `tests/test_source_subscriptions.py`
- `tests/test_source_repository_inventory.py`
- `tests/test_single_source_test_api.py`
- `tests/test_realtime_search_api.py`
- `tests/test_explore_api.py`
- `tests/test_book_reader_api.py`
- `tests/test_admin_ui_routes.py`
- `tests/test_verification_harness.py`

---

## 3. Execution Phases

### Phase A: Upstream Decomposition And Requirements Lock

**Goal:** Extract Reading semantics into a traceable compatibility document.

- [ ] Read native analyzer files listed in section 0.
- [ ] Create `docs/upstream-legado-rule-semantics.md`.
- [ ] Document stage flows:
  - search
  - explore/ranking
  - book info
  - TOC
  - content
  - pre-update JS
  - source login/cookie/header behavior
- [ ] Document rule syntax support with examples from local aoaostar sources.
- [ ] Mark each syntax as:
  - implement now
  - emulate safely
  - classify as unsupported
  - future WebView/runtime extension

**No app behavior changes required.**

**Validation:**

- API simulation: none.
- UI simulation: none.
- Evidence: source file references and rule syntax examples in the document.

### Phase B: Independent Legado Engine Package

**Goal:** Move rule execution out of generic app code into `app/legado_engine`.

- [ ] Create engine models and adapter.
- [ ] Create request builder with Reading-style URL/body/header parsing.
- [ ] Create selector modules.
- [ ] Create rule context with `@put`, `@get`, variable replacement.
- [ ] Create pipeline for search/detail/toc/content/explore.
- [ ] Keep old `app/engine/*` as compatibility wrappers until migration is complete.

**API Simulation:**

- Call engine pipeline directly with mocked HTML/JSON.
- Assert search/detail/toc/content/explore output shapes.
- Assert trace events include rule path, request URL, extractor type, and errors.

**UI Simulation:**

- Add a temporary engine lab section in `/admin/source-test`.
- Use mocked source input to display rule trace and parsed sample.

### Phase C: Subscription System Complete

**Goal:** Make project-managed subscriptions the source import path.

- [ ] Replace current built-in list with aoaostar direct book-source subscriptions.
- [ ] Keep XIU2/Yiove/freeok entries with correct engine/type classification.
- [ ] Support subscription types:
  - direct bookSource JSON
  - aoaostar published source
  - Yiove collection index
  - repository reference
  - non-Legado reference
- [ ] Persist sync status, source count, file output, origin URL, and failure reason.
- [ ] Add backend actions:
  - add
  - edit
  - enable/disable
  - sync one
  - sync all
  - view last imported objects

**API Simulation:**

- Mock HTTP payloads from aoaostar source JSON.
- Verify subscription sync writes raw files and updates source inventory.

**UI Simulation:**

- Open subscriptions page.
- Add a fake direct JSON subscription.
- Click sync with mocked endpoint.
- Verify status row changes to success/failure.

### Phase D: Source Inventory, Health, And Single-Source Invocation

**Goal:** Treat every source object as an independently managed runtime source.

- [ ] Expand file-level and object-level records.
- [ ] Add source origin fields:
  - subscription ID
  - upstream URL
  - raw file path
  - source index
  - engine type
- [ ] Add preflight classification.
- [ ] Add single-source invocation API:
  - search
  - detail
  - toc
  - content
  - explore
- [ ] Persist direct/proxy attempt history.
- [ ] Persist hard failure disable reason.

**API Simulation:**

- Use fake source objects for each stage.
- Assert no-result does not disable a source.
- Assert unsupported required syntax disables only that source record.
- Assert proxy success marks proxy-needed.

**UI Simulation:**

- Source detail page:
  - run search test
  - inspect trace
  - force proxy
  - disable/re-enable
  - view raw source object

### Phase E: Realtime Search And Ranking

**Goal:** Backend search shows source calls, progress, partial results, and merged ranking live.

- [ ] Implement search job service, not only raw SSE generator.
- [ ] Support cancellation and job history.
- [ ] Emit events:
  - job created
  - batch started
  - source started
  - source result
  - source failure
  - merged result updated
  - batch complete
  - job complete
- [ ] Rank by exact title, fuzzy title, author, source health, metadata completeness, latency, proxy penalty.
- [ ] Preserve source candidates for each merged book.

**API Simulation:**

- Mock three sources:
  - success with exact title
  - success with same title/author
  - failure timeout
- Verify realtime events and final merged result.

**UI Simulation:**

- Search workbench shows:
  - progress counters
  - source call table
  - realtime result table
  - failure panel
  - merged candidates drawer/detail section

### Phase F: Explore And Ranking Lists

**Goal:** Support Reading-style `exploreUrl` as backend rankings/discover.

- [ ] Parse `exploreUrl` JSON/list syntax.
- [ ] Expose source explore groups.
- [ ] Execute selected explore item with pagination.
- [ ] Map explore results into book candidates.
- [ ] Add `/admin/explore`.

**API Simulation:**

- Use fake source with two explore categories.
- Verify category list and paged result list.

**UI Simulation:**

- Select source.
- Select category.
- Click load next page.
- Open book from explore result.

### Phase G: Book Detail, TOC, Chapter Reader, And Fallback

**Goal:** Backend can be used as a reader, not only a search proxy.

- [ ] Book detail page shows merged metadata and source candidates.
- [ ] TOC fetch stores chapter list and detects changes.
- [ ] Chapter fetch stores content and trace.
- [ ] Reader UI shows chapter content, source, previous/next controls, fallback source action.
- [ ] Fallback source attempts are visible and persisted.

**API Simulation:**

- Search -> detail -> toc -> chapter with fake source.
- Chapter failure -> fallback source success.

**UI Simulation:**

- Search for a book.
- Open book detail.
- Open TOC.
- Open chapter.
- Click next chapter.
- Trigger fallback and inspect trace.

### Phase H: Update Tracking And Cache

**Goal:** Accessed books can be tracked and checked manually/scheduled.

- [ ] Update task state model.
- [ ] Manual run API.
- [ ] Scheduled loop with conservative interval.
- [ ] Cache inspection and clearing by type.
- [ ] UI for update tasks and cache.

**API Simulation:**

- Create book record.
- Enable tracking.
- Mock TOC with one new chapter.
- Verify update task result.

**UI Simulation:**

- Toggle tracking on a book.
- Click run now.
- View last result.
- Clear selected cache entry.

### Phase I: Verification Harness And Browser QA

**Goal:** Every core feature has repeatable API and UI simulation evidence.

- [ ] Add verification harness that can run without external network.
- [ ] Add fake source server or mocked fetch layer for API simulations.
- [ ] Add browser click-path scripts for admin pages.
- [ ] Store reports under `docs/verification/`.
- [ ] Add final acceptance report.

**API Simulation Matrix:**

| Feature | API |
|---|---|
| subscriptions | list/add/sync/sync-all |
| sources | list/detail/enable/proxy/test |
| search | start job/events/final result |
| explore | list groups/load category |
| book | detail/toc/chapter |
| reader | chapter navigation/fallback |
| update | enable/run/list |
| cache | counts/inspect/clear |
| settings | save/load |

**UI Simulation Matrix:**

| Page | Click Path |
|---|---|
| dashboard | open and verify real counts |
| subscriptions | add fake subscription, sync, inspect status |
| sources | filter, open detail, run single-source test |
| search | run realtime search, inspect source progress |
| explore | select category, open book |
| book detail | load TOC, enable tracking |
| reader | open chapter, next/previous |
| update tasks | run now, inspect result |
| cache | view counts, clear selected |
| settings | change proxy/batch settings and save |

---

## 4. Current Risk Register

1. Current tests can accidentally invoke large source pools and real network. Future tests must default to fake source repositories and mocked HTTP.
2. `app/web/admin.py` is already large. UI work should split layout/components before adding many pages.
3. Current parser has helper-level XPath/JsonPath but not full main-path parity.
4. JavaScript support is the hardest compatibility area. Implement safe transforms first and classify complex JS honestly.
5. WebView/login-required sources should be detected and labeled; full WebView emulation is out of the first full backend milestone unless absolutely required.
6. `aoaostar/legado` direct source JSON may contain thousands of objects; sync and indexing must be batch-safe.
7. Source names may contain symbols. Pass source-provided names through unchanged. System-owned UI copy should avoid decorative emoji.

---

## 5. Immediate Execution Order

1. Write `docs/upstream-legado-rule-semantics.md`.
2. Split current admin layout into `layout.py` and `components.py` to prevent uncontrolled UI file growth.
3. Create `app/legado_engine` package and migrate selector/request parsing behind compatibility wrappers.
4. Expand subscription built-ins from `aoaostar/legado`.
5. Add fake-source verification harness to stop regression tests from using real network by default.
6. Implement job-based realtime search on top of the engine package.
7. Add explore/ranking API and UI.
8. Add reader UI and fallback traces.
9. Add update/cache UI completion.
10. Run API and UI simulation suite, then only run broad regression once it is made deterministic.

---

## 6. Commands

Do not run broad tests until the fake-source verification harness is in place.

Useful targeted commands:

```powershell
Get-ChildItem -Force data\upstreams\aoaostar-legado
Get-ChildItem -Force data\upstreams\luoyacheng-legado
rg "class Analyze|AnalyzeRule|AnalyzeUrl|ruleSearch|ruleToc|ruleContent" data\upstreams\luoyacheng-legado\app\src\main\java -n --glob *.kt
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765
```

API smoke should use the verification harness first. Live-network smoke is a separate acceptance step, not the default regression gate.

