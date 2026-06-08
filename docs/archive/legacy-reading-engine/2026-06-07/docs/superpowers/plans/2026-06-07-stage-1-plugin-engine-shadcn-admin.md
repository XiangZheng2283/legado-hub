# Stage 1 Plugin Engine And Shadcn Admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. This is the Stage 1 execution source of truth. Keep exactly one task in progress at a time, verify before reporting completion, and do not commit/push unless the user explicitly asks.

**Goal:** Implement the full LegadoHub Python source-plugin calling engine, convert 1 to 5 initial source plugins from `freeok/so-novel`, and replace the old server-rendered admin surface with a complete React/Vite/TypeScript/shadcn/ui backend console.

**Architecture:** Preserve the existing Reading/Legado aggregate source provider as the external compatibility shell, but replace internal source execution with Python plugins controlled by LegadoHub scheduling, fetch, cache, proxy, timeout, and trace services. Archive or clearly isolate old Reading-rule/JVM-engine planning and code paths so new implementers cannot mistake them for the active runtime. Build a new SPA admin console backed by FastAPI admin APIs, using shadcn/ui components in a dense Chinese operations-console style.

**Tech Stack:** Python 3.12, FastAPI, SQLite, asyncio, httpx, pytest, PyYAML, BeautifulSoup/lxml selector helpers, React, Vite, TypeScript, Tailwind CSS, shadcn/ui, lucide-react, TanStack Query, Playwright or in-app browser verification.

---

## Stage 1 Scope

Stage 1 ships one coherent product slice:

1. Old engine direction is archived or isolated.
2. So Novel seed rules are inspected and classified.
3. Python source plugin contracts, loader, runtime context, scheduler, and smoke runner exist.
4. 1 to 5 source plugins run through the new engine.
5. Existing `/api/legado/source`, `/api/legado/search`, `/api/legado/book/{book_id}`, `/api/legado/book/{book_id}/toc`, and `/api/legado/chapter/{chapter_id}` keep Reading-compatible response shapes.
6. New admin APIs expose plugin state, source health, search jobs, cache, settings, generated aggregate source, and verification.
7. New shadcn/ui admin frontend replaces the static HTML console as the primary backend surface.
8. Verification proves API, plugin runtime, aggregate source generation, and frontend smoke flows.

Out of scope for Stage 1:

- Cloudflare/browser automation as a default runtime.
- Secure third-party plugin sandboxing.
- Full compatibility with Reading BookSource rules.
- Continuing `engine-jvm` as an active runtime.
- Bulk conversion of all So Novel sources.
- Working paid-content extraction from official sources such as 起点 or 番茄. Stage 1 must implement the contract and admin hooks for login/auth status, but official-source paid chapters may return structured auth/payment-required failures.

## Active Source Of Truth

Use these documents:

- `docs/architecture/plugin-source-runtime-restart-plan.md`
- `docs/architecture/source-plugin-contract.md`
- `docs/superpowers/plans/2026-06-07-stage-1-plugin-engine-shadcn-admin.md`
- `docs/skills/book-source-craft/SKILL.md`
- `docs/skills/book-source-craft/references/plugin-source-workflow.md`
- `docs/skills/book-source-craft/references/source-plugin-template.md`
- `PRODUCT.md`

Treat these as historical or reference only:

- `docs/architecture/legadohub-redesign-roadmap.md`
- `docs/architecture/legadohub-phase-1-kernel-port-plan.md`
- `docs/implementation-plan-full-legado-backend.md`
- `docs/upstream-legado-rule-semantics.md`
- `docs/verification/phase-1-direct-kernel-port.md`
- `engine-jvm/`
- `app/legado_engine/`
- `app/engine/`

Legacy code directories have already been moved under `archive/legacy-reading-engine/2026-06-07/`. Do not restore them into active paths.

## File Map

Create:

- `docs/architecture/legacy-engine-archive.md`
- `docs/architecture/source-plugin-contract.md`
- `data/source_seeds/so-novel/README.md`
- `scripts/inspect_so_novel_rules.py`
- `app/source_plugins/__init__.py`
- `app/source_plugins/models.py`
- `app/source_plugins/loader.py`
- `app/source_plugins/context.py`
- `app/source_plugins/fetcher.py`
- `app/source_plugins/scheduler.py`
- `app/source_plugins/smoke.py`
- `app/source_plugins/errors.py`
- `data/source_plugins/<plugin_id>/metadata.yaml`
- `data/source_plugins/<plugin_id>/source.py`
- `data/source_plugins/<plugin_id>/tests/smoke.yaml`
- `frontend/package.json`
- `frontend/index.html`
- `frontend/vite.config.ts`
- `frontend/tsconfig.json`
- `frontend/tsconfig.app.json`
- `frontend/components.json`
- `frontend/src/main.tsx`
- `frontend/src/App.tsx`
- `frontend/src/index.css`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/query.ts`
- `frontend/src/lib/utils.ts`
- `frontend/src/routes/*.tsx`
- `frontend/src/components/layout/*.tsx`
- `frontend/src/components/plugins/*.tsx`
- `frontend/src/components/search/*.tsx`
- `frontend/src/components/cache/*.tsx`
- `frontend/src/components/settings/*.tsx`
- `frontend/src/components/ui/*`
- `tests/source_plugins/*.py`
- `tests/scripts/test_inspect_so_novel_rules.py`
- `tests/test_plugin_admin_api.py`
- `tests/test_plugin_catalog_api.py`
- `tests/test_frontend_static_mount.py`

Modify:

- `PRODUCT.md`
- `requirements.txt`
- `app/main.py`
- `app/api/legado.py`
- `app/api/admin.py`
- `app/services/catalog.py`
- `app/services/search_jobs.py`
- `app/services/cache.py`
- `app/services/plugin_health_repository.py`
- `app/core/source_generator.py` only if the aggregate source endpoint contract changes.
- `config/source_pool.json`
- `config/aggregate_source.json`
- `.gitignore`
- `start.bat`

Avoid expanding:

- `engine-jvm/`
- `app/legado_engine/`
- `app/engine/`

## Task 0: Legacy Engine Convergence Gate

**Goal:** Ensure old Reading/JVM/self-written engine code cannot be mistaken for the active implementation path.

**Files:**

- Create: `docs/architecture/legacy-engine-archive.md`
- Modify: `docs/architecture/legadohub-redesign-roadmap.md`
- Modify: `docs/architecture/legadohub-phase-1-kernel-port-plan.md`
- Modify: `docs/implementation-plan-full-legado-backend.md`
- Modify: `app/services/catalog.py`
- Modify: `app/services/search_jobs.py`

**Steps:**

- [ ] Read all active-looking docs that mention `engine-jvm`, `app/legado_engine`, `app/engine`, `LegadoEngineRunner`, `Kotlin`, `JVM`, `Reading kernel`, or `AnalyzeRule`.
- [ ] Create `docs/architecture/legacy-engine-archive.md` with:
  - active direction: Python source plugin runtime
  - legacy code paths
  - legacy docs
  - allowed reference-only uses
  - forbidden Stage 1 uses
  - exact test command that proves no active catalog path imports `LegadoEngineRunner`
- [ ] Add a one-paragraph "Superseded / historical reference" banner to old implementation docs that still read as active.
- [ ] Search active Python code for runtime imports:

```powershell
rg -n "LegadoEngineRunner|app\\.legado_engine|app\\.engine|engine-jvm|AnalyzeRule|Kotlin|JVM" app tests docs -S
```

- [ ] Do not remove legacy directories yet. Replace active service imports only when Task 6 rewires catalog/search jobs.
- [ ] Add or update tests so `app/services/catalog.py` and `app/services/search_jobs.py` no longer instantiate `LegadoEngineRunner` after Task 6.

**Acceptance:**

- Old direction docs are visibly marked historical.
- New direction docs are linked.
- Legacy code is still available for reference, but no Stage 1 runtime task depends on it.

## Task 1: So Novel Seed Snapshot And Inspector

**Goal:** Use `freeok/so-novel` as the initial source seed without making So Novel rules the runtime format.

**Files:**

- Create: `data/source_seeds/so-novel/README.md`
- Create: `scripts/inspect_so_novel_rules.py`
- Create: `tests/scripts/test_inspect_so_novel_rules.py`

**Steps:**

- [ ] Create `data/source_seeds/so-novel/README.md` with upstream URL, files to copy, commit hash field, retrieval date field, and note: "input seed only, not runtime format."
- [ ] Fetch or copy these upstream files into `data/source_seeds/so-novel/`:
  - `BOOK_SOURCES.md`
  - `bundle/rules/main.json`
  - `bundle/rules/proxy-required.json`
  - `bundle/rules/rate-limit.json`
  - `bundle/rules/cloudflare.json`
  - `bundle/rules/rule-template.json5`
- [ ] Record the upstream commit hash if fetched from git. If downloaded manually, record retrieval date and source URLs.
- [ ] Write tests for a pure inspector function that accepts in-memory dictionaries/lists and returns:
  - total rule count
  - search-capable count
  - simple candidate list
  - proxy-required ids
  - rate-limit ids
  - cloudflare ids
  - no-search ids if available
- [ ] Implement `scripts/inspect_so_novel_rules.py`.
- [ ] Run:

```powershell
pytest tests/scripts/test_inspect_so_novel_rules.py -q
python scripts/inspect_so_novel_rules.py --main data/source_seeds/so-novel/main.json --proxy-required data/source_seeds/so-novel/proxy-required.json --rate-limit data/source_seeds/so-novel/rate-limit.json --cloudflare data/source_seeds/so-novel/cloudflare.json
```

**Acceptance:**

- Inspector prints a JSON summary.
- Simple candidates exclude Cloudflare-first entries.
- The output is deterministic and can be reviewed before plugin conversion.

## Task 2: Plugin Data Contract

**Goal:** Define the canonical plugin metadata and normalized output shapes.

**Files:**

- Create: `app/source_plugins/__init__.py`
- Create: `app/source_plugins/models.py`
- Create: `app/source_plugins/errors.py`
- Create: `tests/source_plugins/test_models.py`

**Models:**

- `PluginMetadata`
- `LoadedPlugin`
- `PluginHealth`
- `SearchResult`
- `BookDetail`
- `ChapterItem`
- `ChapterContent`
- `PluginFailure`
- `PluginValidationError`
- `PluginExecutionError`

**Rules:**

- Follow `docs/architecture/source-plugin-contract.md` exactly. Do not invent a new plugin interface.
- Metadata requires `contractVersion`, `id`, `name`, `version`, `type`, `domains`, `baseUrls`, `capabilities`, `auth`, `content`, and `tags`.
- Capabilities are limited to `search`, `detail`, `toc`, `chapter`, `explore`.
- Output dictionaries must include `sourceId`.
- URLs are opaque to Reading clients; LegadoHub may encode source ID and URL in IDs.
- Official/login-based source support is part of the contract:
  - `auth_status`
  - `prepare_login`
  - `after_login`
  - `AUTH_REQUIRED`
  - `LOGIN_REQUIRED`
  - `PAID_CONTENT_REQUIRED`
  - `authRequired`, `isVip`, `isLocked`, and `isPaid` output fields.

**Steps:**

- [ ] Write tests for valid metadata, invalid metadata, result serialization, and failure serialization.
- [ ] Write tests for `auth.mode` validation and official-source metadata examples.
- [ ] Write tests that paid/locked chapter metadata can serialize without being treated as parse failure.
- [ ] Implement model classes with no dependency on admin APIs or FastAPI.
- [ ] Run:

```powershell
pytest tests/source_plugins/test_models.py -q
```

**Acceptance:**

- Model tests pass.
- Models are importable without starting FastAPI.

## Task 3: Plugin Loader

**Goal:** Discover and validate Python source plugins from `data/source_plugins`.

**Files:**

- Create: `app/source_plugins/loader.py`
- Create: `tests/source_plugins/test_loader.py`

**Steps:**

- [ ] Write fixture plugin directories in pytest temp dirs.
- [ ] Test valid plugin load.
- [ ] Test missing `metadata.yaml` fails clearly.
- [ ] Test declared capability without method fails clearly.
- [ ] Test duplicate plugin ID fails clearly.
- [ ] Implement loader:
  - reads `metadata.yaml` with `yaml.safe_load`
  - imports `source.py` with isolated module name
  - instantiates `Source`
  - validates async lifecycle methods for declared capabilities
  - returns `LoadedPlugin`
- [ ] Run:

```powershell
pytest tests/source_plugins/test_loader.py -q
```

**Acceptance:**

- Loader reports precise validation errors.
- Loader does not import legacy Reading/JVM engine modules.

## Task 4: Runtime Context And Controlled Fetch

**Goal:** Give plugins flexible site logic while keeping network, timeout, proxy, cookie, cache, and trace under LegadoHub control.

**Files:**

- Create: `app/source_plugins/context.py`
- Create: `app/source_plugins/fetcher.py`
- Create: `tests/source_plugins/test_context.py`
- Create: `tests/source_plugins/test_fetcher.py`

**Context API:**

- `ctx.fetch_text(url, *, method="GET", params=None, data=None, json=None, headers=None, timeout=None)`
- `ctx.fetch_json(...)`
- `ctx.fetch_bytes(...)`
- `ctx.fetch_many(urls, *, limit=None)`
- `ctx.select(html_or_node, selector)`
- `ctx.text(html_or_node, selector=None)`
- `ctx.html(html_or_node, selector=None)`
- `ctx.attr(html_or_node, selector, name)`
- `ctx.urljoin(base, href)`
- `ctx.clean_html(html)`
- `ctx.clean_text(text)`
- `ctx.trace(stage, url="", message="", data=None)`
- `ctx.cookies.get(domain, name=None)`
- `ctx.cookies.set(domain, cookie)`
- `ctx.cookies.clear(domain=None)`
- `ctx.auth_status()`
- `ctx.request_manual_login(login_url, cookie_domains, message="")`

**Steps:**

- [ ] Write selector and URL utility tests with static HTML.
- [ ] Write fetch tests with injected fake HTTP client.
- [ ] Write cookie/auth context tests for manual-login request creation.
- [ ] Implement context helpers.
- [ ] Implement fetcher wrapper around existing project HTTP/proxy settings or `httpx.AsyncClient`.
- [ ] Ensure plugins cannot control source-level concurrency; `ctx.fetch_many` must route through controlled internal limits.
- [ ] Run:

```powershell
pytest tests/source_plugins/test_context.py tests/source_plugins/test_fetcher.py -q
```

**Acceptance:**

- Context tests pass.
- Fetch calls emit trace events.
- Fetch errors become structured `PluginFailure` candidates.
- Login/auth requests are represented as controlled runtime actions; plugins do not open browsers directly.

## Task 5: Plugin Scheduler

**Goal:** Execute plugins concurrently from LegadoHub core, not from plugin scripts.

**Files:**

- Create: `app/source_plugins/scheduler.py`
- Create: `tests/source_plugins/test_scheduler.py`
- Modify: `config/source_pool.json` only if config names need plugin-specific additions.

**Scheduler responsibilities:**

- Load enabled plugins.
- Apply `max_concurrency`.
- Apply `source_batch_size`.
- Apply `source_timeout_seconds`.
- Apply `overall_search_timeout_seconds`.
- Preserve partial success.
- Isolate plugin exceptions.
- Attach `sourceId` to every result.
- Record trace/failure evidence.

**Steps:**

- [ ] Write tests for concurrent successful search.
- [ ] Write tests for one plugin timing out while another succeeds.
- [ ] Write tests for plugin exception classification.
- [ ] Write tests for detail/toc/chapter direct calls by source ID.
- [ ] Implement scheduler methods:
  - `search(keyword, page)`
  - `detail(source_id, book_url)`
  - `toc(source_id, toc_url)`
  - `chapter(source_id, chapter_url)`
  - `smoke(plugin_id, keyword)`
- [ ] Run:

```powershell
pytest tests/source_plugins/test_scheduler.py -q
```

**Acceptance:**

- Scheduler tests pass.
- Plugins do not create or own source-level concurrency.

## Task 6: Catalog And Reading-Compatible API Rewire

**Goal:** Keep Reading/Legado external API stable while switching internal execution to plugins.

**Files:**

- Modify: `app/services/catalog.py`
- Modify: `app/services/search_jobs.py`
- Modify: `app/api/legado.py`
- Modify: `app/services/cache.py` if ID shapes require cache key adjustments.
- Create: `tests/test_plugin_catalog_api.py`

**Steps:**

- [ ] Write tests for `/api/legado/search`.
- [ ] Write tests for `/api/legado/book/{book_id}`.
- [ ] Write tests for `/api/legado/book/{book_id}/toc`.
- [ ] Write tests for `/api/legado/chapter/{chapter_id}`.
- [ ] Write tests for empty plugin pool and partial plugin failure.
- [ ] Rewire `Catalog` to use `PluginScheduler`.
- [ ] Rewire `SearchJobService` to emit plugin search progress.
- [ ] Ensure `book_id` and `chapter_id` can encode/decode `sourceId` and opaque URLs.
- [ ] Remove active imports of `LegadoEngineRunner` from catalog/search job paths.
- [ ] Run:

```powershell
pytest tests/test_plugin_catalog_api.py -q
rg -n "LegadoEngineRunner|app\\.legado_engine|app\\.engine" app/services app/api -S
```

**Acceptance:**

- Plugin-backed API tests pass.
- Search/detail/toc/chapter response shapes remain compatible with `app/core/source_generator.py`.
- `rg` shows no active service/API dependency on legacy engines, except documented archive/reference comments.

## Task 7: Smoke Runner

**Goal:** Validate each plugin without using the Reading app.

**Files:**

- Create: `app/source_plugins/smoke.py`
- Create: `tests/source_plugins/test_smoke.py`

**Smoke flow:**

1. Load plugin.
2. Search keyword.
3. Select first or configured result.
4. Run detail.
5. Run toc.
6. Select first or configured chapter.
7. Run chapter.
8. Assert minimum fields and content length.

**Steps:**

- [ ] Write smoke fixture tests with fake plugin and fake fetch.
- [ ] Implement smoke runner function.
- [ ] Implement CLI:

```powershell
python -m app.source_plugins.smoke data/source_plugins/<plugin_id> --keyword "凡人修仙传"
```

- [ ] Run:

```powershell
pytest tests/source_plugins/test_smoke.py -q
```

**Acceptance:**

- Smoke runner reports stage-specific failure evidence.
- CLI exits non-zero on failed smoke assertions.

## Task 8: Convert 1 To 5 So Novel Source Plugins

**Goal:** Produce real initial plugin inventory from `freeok/so-novel`.

**Files:**

- Create: `data/source_plugins/<plugin_id>/metadata.yaml`
- Create: `data/source_plugins/<plugin_id>/source.py`
- Create: `data/source_plugins/<plugin_id>/README.md`
- Create: `data/source_plugins/<plugin_id>/tests/smoke.yaml`
- Create: `tests/source_plugins/test_initial_plugins.py`

**Selection rules:**

- Minimum: 1 working plugin.
- Target: 3 working plugins.
- Maximum for Stage 1: 5 plugins.
- Prefer search-capable entries from `main.json`.
- Defer entries in `cloudflare.json`.
- Mark entries in `proxy-required.json` as proxy candidates.
- Mark entries in `rate-limit.json` for conservative scheduling.
- Do not pick login-heavy or browser-only sites for the first plugin.
- If one official/login source is selected for contract validation, it may stop at metadata/search/detail/toc plus structured `AUTH_REQUIRED` or `PAID_CONTENT_REQUIRED` for locked chapter content.

**Steps:**

- [ ] Run the So Novel inspector and save/review summary.
- [ ] Pick 1 to 5 candidate sources.
- [ ] For each plugin, create metadata and source implementation.
- [ ] For each plugin, add smoke fixture and adaptation note.
- [ ] Prefer template extraction if two selected sources share structure.
- [ ] Run fixture-backed tests:

```powershell
pytest tests/source_plugins/test_initial_plugins.py -q
```

- [ ] Run live smoke only for sources that are reachable from the local environment:

```powershell
python -m app.source_plugins.smoke data/source_plugins/<plugin_id> --keyword "凡人修仙传"
```

**Acceptance:**

- At least 1 plugin passes smoke.
- Up to 5 plugins are present if reliable candidates are available.
- Every plugin has metadata, source code, smoke fixture, and adaptation notes.
- Any failed candidate is documented and disabled, not presented as working.

## Task 9: Admin API For Plugin Operations

**Goal:** Provide complete backend APIs for the new shadcn/ui admin.

**Files:**

- Modify: `app/api/admin.py`
- Modify: `app/services/source_repository.py`
- Modify: `app/services/verification_harness.py`
- Create: `tests/test_plugin_admin_api.py`

**Endpoints:**

- `GET /api/admin/plugins`
- `GET /api/admin/plugins/{plugin_id}`
- `POST /api/admin/plugins/reload`
- `POST /api/admin/plugins/{plugin_id}/enable`
- `POST /api/admin/plugins/{plugin_id}/smoke`
- `GET /api/admin/plugins/{plugin_id}/auth`
- `POST /api/admin/plugins/{plugin_id}/login`
- `POST /api/admin/plugins/{plugin_id}/auth/check`
- `POST /api/admin/plugins/{plugin_id}/cookies/clear`
- `GET /api/admin/search-jobs/{job_id}`
- `POST /api/admin/search-jobs`
- `GET /api/admin/search-jobs/{job_id}/events`
- `GET /api/admin/cache`
- `DELETE /api/admin/cache`
- `GET /api/admin/settings`
- `POST /api/admin/settings`
- `GET /api/admin/aggregate-source`
- `POST /api/admin/aggregate-source/regenerate`
- `GET /api/admin/verification`

**Steps:**

- [ ] Write API tests for list/detail/reload/enable/smoke.
- [ ] Write API tests for auth status, manual-login preparation, auth check, and cookie clear.
- [ ] Write API tests for search job creation and event polling.
- [ ] Write API tests for aggregate-source regenerate.
- [ ] Implement endpoints using existing services where possible.
- [ ] Keep response payloads frontend-friendly: stable keys, explicit empty states, no fake data.
- [ ] Run:

```powershell
pytest tests/test_plugin_admin_api.py -q
```

**Acceptance:**

- Admin APIs return real plugin/runtime data.
- Disabled/empty/error states are explicit.
- Official/login source hooks are visible through API even if no paid chapter plugin is fully implemented.

## Task 10: Frontend Scaffold With React/Vite/shadcn/ui

**Goal:** Create the new admin frontend project.

**Files:**

- Create: `frontend/*`
- Modify: `app/main.py`
- Modify: `start.bat`
- Modify: `.gitignore`

**Setup rules:**

- Use React + TypeScript + Vite.
- Use shadcn/ui with Tailwind.
- Use lucide-react icons.
- Use TanStack Query for server state.
- Keep UI Chinese.
- Keep dense operations-console style from `PRODUCT.md`.
- Do not create a marketing landing page.

**Reference:** Official shadcn/ui Vite docs currently recommend `shadcn@latest` CLI for Vite setup and component addition. If the command changes, follow the official Vite page at implementation time.

**Steps:**

- [ ] Create `frontend` project.
- [ ] Install dependencies.
- [ ] Initialize shadcn/ui.
- [ ] Add required components:
  - button
  - card
  - table
  - tabs
  - badge
  - input
  - select
  - switch
  - dialog
  - sheet
  - dropdown-menu
  - tooltip
  - scroll-area
  - separator
  - skeleton
  - alert
  - toast/sonner if selected
- [ ] Add API client and query provider.
- [ ] Configure Vite proxy to FastAPI during development.
- [ ] Configure FastAPI static mount for production build output.
- [ ] Update `start.bat` to tell users both backend and frontend/admin URLs.
- [ ] Run:

```powershell
cd frontend
npm install
npm run build
cd ..
pytest tests/test_frontend_static_mount.py -q
```

**Acceptance:**

- Frontend builds.
- FastAPI can serve the built admin app or clearly documents dev-server mode.

## Task 11: New Admin UI Information Architecture

**Goal:** Build the complete first admin console shell and core pages.

**Files:**

- Create: `frontend/src/App.tsx`
- Create: `frontend/src/routes/*.tsx`
- Create: `frontend/src/components/layout/*.tsx`
- Create: `frontend/src/components/ui/*`
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/query.ts`

**Pages:**

- `/admin` dashboard
- `/admin/plugins`
- `/admin/plugins/:pluginId`
- `/admin/plugins/:pluginId/auth`
- `/admin/search`
- `/admin/jobs/:jobId`
- `/admin/books`
- `/admin/cache`
- `/admin/settings`
- `/admin/aggregate-source`
- `/admin/verification`

**Design direction:**

- Quiet, precise, capable.
- Dense Chinese operations console.
- Light neutral shell, restrained borders, strong table readability.
- Use status badges plus labels, not color-only status.
- No fake/demo content.
- No oversized hero, decorative gradients, or marketing copy.
- Use shadcn components for forms, tabs, tables, dialogs, switches, tooltips.
- Use lucide icons for navigation and tool buttons.

**Steps:**

- [ ] Build app shell with sidebar/topbar and responsive layout.
- [ ] Build dashboard with real summary cards from `/api/admin/status` or existing equivalent.
- [ ] Build plugins table with enable state, capabilities, domains, health, last smoke result.
- [ ] Build plugin detail page with metadata, stage traces, smoke action, failure evidence.
- [ ] Build plugin auth/login panel:
  - auth status
  - login mode
  - login URL action
  - check login status
  - clear cookies
  - paid/locked content notes
- [ ] Build search page with keyword input, source/plugin filters, job progress table, partial results.
- [ ] Build cache/settings/aggregate-source pages from real APIs.
- [ ] Add loading, empty, error, and partial-success states for every page.
- [ ] Run:

```powershell
cd frontend
npm run build
```

**Acceptance:**

- Every page renders without fake data.
- Text fits on desktop and mobile.
- UI follows shadcn/ui component patterns and operations-console style.
- Official/login source states are represented honestly as auth-required, login-required, paid-content-required, or unsupported; they are not shown as generic failures.

## Task 12: Browser Verification For Admin UI

**Goal:** Verify the new frontend through a browser, not only by build output.

**Files:**

- Create or modify: `tests/e2e/admin-smoke.spec.ts` if Playwright is introduced.
- Or document manual browser verification evidence in `docs/verification/stage-1-plugin-engine-shadcn-admin.md`.

**Steps:**

- [ ] Start backend.
- [ ] Start frontend dev server or serve built assets.
- [ ] Open admin dashboard in browser.
- [ ] Verify:
  - dashboard loads
  - plugins page loads
  - plugin detail page loads
  - search job can be started
  - cache page loads
  - settings page loads
  - aggregate source page can regenerate source
- [ ] Capture screenshots or record route/status evidence.

**Acceptance:**

- Browser verification evidence exists.
- Any visual overlap, unreadable table, fake content, or broken route is fixed before claiming completion.

## Task 13: Aggregate Source Compatibility

**Goal:** Preserve Reading/Legado import surface.

**Files:**

- Modify only if required: `app/core/source_generator.py`
- Modify only if required: `app/api/legado.py`
- Create: `tests/test_aggregate_source_plugin_runtime.py`

**Steps:**

- [ ] Test `/api/legado/source` returns one source object.
- [ ] Test generated source has search/book/toc/content rules pointing to LegadoHub endpoints.
- [ ] Test `/api/legado/search` returns plugin-backed results.
- [ ] Test detail/toc/chapter chain with a fixture plugin.
- [ ] Run:

```powershell
pytest tests/test_aggregate_source_plugin_runtime.py -q
python - <<'PY'
from app.core.source_generator import write_aggregate_source
print(write_aggregate_source())
PY
```

**Acceptance:**

- Aggregate source generation still works.
- Plugin runtime is invisible to Reading clients except through improved results and diagnostics.

## Task 14: Final Verification And Handoff Report

**Goal:** Produce a reviewable Stage 1 completion bundle.

**Files:**

- Create: `docs/verification/stage-1-plugin-engine-shadcn-admin.md`

**Steps:**

- [ ] Run backend tests:

```powershell
pytest tests/source_plugins tests/scripts/test_inspect_so_novel_rules.py tests/test_plugin_catalog_api.py tests/test_plugin_admin_api.py tests/test_aggregate_source_plugin_runtime.py -q
```

- [ ] Run broader test suite:

```powershell
pytest tests -q
```

- [ ] Run frontend checks:

```powershell
cd frontend
npm run build
cd ..
```

- [ ] Run whitespace check:

```powershell
git diff --check
```

- [ ] Run legacy import check:

```powershell
rg -n "LegadoEngineRunner|app\\.legado_engine|app\\.engine|engine-jvm|AnalyzeRule|Kotlin|JVM" app tests docs -S
```

- [ ] Write verification report with:
  - branch name
  - changed files
  - enabled plugins
  - disabled/failed plugin candidates
  - exact command outputs
  - frontend URL and browser verification evidence
  - known gaps

**Acceptance:**

- Report includes exact evidence, not assumptions.
- Any failed verification is named with command and failure text.
- Stage 1 is not called complete unless the required checks have fresh passing evidence or explicit documented exceptions.

## Kimi Execution Rules

Kimi must follow these rules:

- Work only in `C:\Home\Workspace\UGit\legado-hub`.
- Use the current branch or create a child branch from `codex/replan-plugin-source-runtime`.
- Do not push.
- Do not delete legacy directories without user approval.
- Do not revive the Reading/JVM engine path.
- Do not implement source-level concurrency inside plugins.
- Do not put fake/demo data in the admin UI.
- Keep aggregate source generation working.
- Install dependencies when needed and record them in `requirements.txt`, `frontend/package.json`, or plugin-local `requirements.txt`.
- Follow `docs/architecture/source-plugin-contract.md` exactly; do not invent plugin API shapes.
- Add auth/login hooks for official or login-based sources at the engine/API/UI level, even if Stage 1 plugins only return structured auth/payment-required results.
- Verify each task before moving to the next task.
- Stop and report if frontend dependency installation, So Novel seed retrieval, or live source access is blocked.

## Instruction Completion Requirements

Kimi may report this goal as complete only when every requirement in this section is satisfied. If any requirement is unmet, report `未完成` or `阻塞` and name the exact gap.

### Task Completion

- Tasks 0 through 14 in this plan are completed, or every unfinished item is listed in a blocker/deferred-items section with a concrete reason.
- Every completed task includes the verification command that was run and the actual result.
- Task 0, the legacy convergence gate, is not skipped.

### Legacy Convergence

- `docs/architecture/legacy-engine-archive.md` exists.
- Old JVM/Reading/self-written engine direction docs are marked as historical reference.
- Main API/service runtime paths no longer depend on `LegadoEngineRunner`, `app.legado_engine`, or `app.engine`.
- If legacy keyword search still has matches, each match is classified as historical doc, archive note, test fixture, or active dependency needing repair.

### Plugin Engine

- `app/source_plugins/` contains the complete runtime:
  - `models.py`
  - `errors.py`
  - `loader.py`
  - `context.py`
  - `fetcher.py`
  - `scheduler.py`
  - `smoke.py`
- Plugin metadata, lifecycle methods, context API, output shapes, auth hooks, and error codes follow `docs/architecture/source-plugin-contract.md`.
- Concurrency, timeout, proxy, cache, trace, retry policy, and failure classification are controlled by LegadoHub core, not plugin scripts.
- Plugin failures normalize to structured error codes.

### So Novel Initial Sources

- `freeok/so-novel` seed files are fetched or cached under `data/source_seeds/so-novel/`.
- Seed provenance is recorded, including upstream commit hash when available or retrieval date/source URLs otherwise.
- `scripts/inspect_so_novel_rules.py` exists and can summarize/classify the seed.
- Candidate plugins are selected from `main.json`, with `cloudflare`, `proxy-required`, and `rate-limit` classifications considered.
- 1 to 5 Python source plugins are generated.
- At least 1 plugin passes smoke validation.
- Failed or disabled candidates are documented with reasons and are not presented as working.

### Official/Login Source Extensibility

- Auth/login hooks are implemented in model, context, API, and admin UI surfaces.
- The system can represent:
  - login status
  - manual-login preparation
  - login-status check
  - cookie clearing
  - `AUTH_REQUIRED`
  - `LOGIN_REQUIRED`
  - `PAID_CONTENT_REQUIRED`
- Paid or locked chapters are not reported as generic parse failures.
- Stage 1 does not need to extract paid chapters from official sources, but it must expose the extension points for later 起点、番茄、七猫、QQ 阅读 support.

### Aggregate Source Compatibility

- `/api/legado/source` returns one aggregate source.
- `/api/legado/search` returns plugin-backed search results.
- `/api/legado/book/{book_id}` returns plugin-backed detail.
- `/api/legado/book/{book_id}/toc` returns plugin-backed TOC.
- `/api/legado/chapter/{chapter_id}` returns chapter content or structured auth/payment-required state.
- `generated/legadohub-source.json` can be regenerated.

### Shadcn Admin

- `frontend/` contains a complete React/Vite/TypeScript/shadcn/ui project.
- The new frontend is the primary admin surface, not the old server-rendered HTML UI.
- The admin UI has these pages:
  - Dashboard
  - Plugins
  - Plugin Detail
  - Plugin Auth/Login
  - Search Jobs
  - Books
  - Cache
  - Settings
  - Aggregate Source
  - Verification
- UI text is Chinese.
- UI uses real API data.
- No fake/demo UI is used to imply unavailable runtime state.
- Loading, empty, error, and partial-success states are handled.
- Frontend build and browser smoke verification are recorded.

### Dependencies

- Needed dependencies are installed by the executor.
- Python dependencies are recorded in `requirements.txt`.
- Frontend dependencies are recorded in `frontend/package.json`.
- Plugin-specific dependencies are recorded in plugin-local `requirements.txt` or README.
- Dependency installation failures are reported with exact command and error.

### Required Verification Commands

Run and record these commands before reporting completion:

```powershell
pytest tests/source_plugins tests/scripts/test_inspect_so_novel_rules.py tests/test_plugin_catalog_api.py tests/test_plugin_admin_api.py tests/test_aggregate_source_plugin_runtime.py -q
pytest tests -q
cd frontend; npm run build; cd ..
git diff --check
rg -n "LegadoEngineRunner|app\\.legado_engine|app\\.engine|engine-jvm|AnalyzeRule|Kotlin|JVM" app tests docs -S
```

If any required verification fails, the goal is not complete unless the failure is explicitly documented as an unrelated legacy/environment issue and the Stage 1-specific checks pass with evidence.

### Verification Report

Create `docs/verification/stage-1-plugin-engine-shadcn-admin.md` with:

- branch name
- changed files summary
- enabled plugin list
- disabled/failed candidate list
- So Novel seed provenance
- backend test command results
- frontend build result
- browser verification evidence
- legacy convergence check result
- dependency installation record
- known issues and deferred items

### Final Executor Output

When handing back to Codex for review, output only:

1. current branch
2. completed task list
3. key verification command results
4. generated plugin list
5. admin access URL or command
6. verification report path
7. unfinished/blocking items, or `无`
