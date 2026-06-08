# Stage 2 Plugin Production And Reading Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not restore archived Reading/JVM/legacy engine code. Do not reintroduce `/admin` or `demo_*` naming.

**Goal:** Build the Stage 2 usability loop: source plugins can be produced, fixture-smoked, diagnosed, and exercised end-to-end through the Reading-compatible API and `/console`.

**Architecture:** Keep `backend/app/source_plugins/` as the only active source runtime. `plugins/sources/<plugin_id>/` contains site-specific Python adapters and fixtures; LegadoHub core owns fetch, timeout, proxy, cache, health, auth state, smoke execution, and Reading-compatible aggregate endpoints. The React console remains the operational surface at `/console`.

**Tech Stack:** Python 3.12, FastAPI, SQLite, asyncio, httpx, pytest, PyYAML, lxml/cssselect/BeautifulSoup, React 19, Vite, TypeScript, Tailwind CSS v4, shadcn/ui, TanStack Query.

---

## Current Baseline

Active root layout:

- `backend/`
- `frontend/`
- `plugins/`
- `docs/`
- `start.bat`

Current entry points:

- Console SPA: `/console`
- Console API: `/api/console/*`
- Reading-compatible source import: `/api/legado/source`
- Legacy `/admin` and `/api/admin/*`: must remain `404`

Current plugin IDs:

- `xbiqugu_la`
- `shuhaige_net`
- `biquge365_net`
- `xbiquzw_net`
- `22biqu_com`

Current verified baseline after Stage 1 repair:

```powershell
cd backend; python -m pytest tests -q; cd ..
# Expected current baseline: 103 passed, 1 warning

cd frontend; npm run build; cd ..
# Expected: build succeeds with Tailwind utilities generated
```

## Hard Constraints

- Do not import from `docs/archive/**`.
- Do not revive `app.engine`, `app.legado_engine`, `engine-jvm`, old `app.web`, or old `app.rules`.
- Do not add `/admin` compatibility routes or redirects.
- Do not rename formal plugin IDs back to `demo_*`.
- Do not let plugin scripts own concurrency, timeout, proxy, retry, global cache, Reading aggregate-source generation, or background scheduling.
- If dependencies are needed, install them and update the correct manifest:
  - backend Python: `backend/requirements.txt`
  - frontend: `frontend/package.json` and lockfile
  - plugin-local: `plugins/sources/<plugin_id>/requirements.txt`
- Keep tests fixture-first. Live network checks may exist, but they must not be required for normal `pytest`.

## Required Stage 2 Outcome

- Every shipped plugin has executable fixture-backed smoke coverage for `search`, `detail`, `toc`, and `chapter`.
- Console smoke endpoint uses plugin `tests/smoke.yaml` by default and records structured diagnostics.
- A developer can create a new plugin from a formal template with a script and get immediate validation feedback.
- Reading-compatible API has an automated end-to-end test: search -> book detail -> toc -> chapter content.
- Console has a visible "reading loop" or equivalent verification surface showing the above flow.
- Auth/login framework is concrete enough for official sources later: cookie storage API, auth status, login preparation, cookie clear, and console actions.
- Failure diagnosis is visible and structured: network, HTTP, parse empty, auth required, Cloudflare/browser required, timeout, and unexpected runtime error.
- Verification report is updated to current Stage 2 evidence, including frontend Tailwind/shadcn render verification.

---

## File Map

### Backend Runtime

- Modify: `backend/app/source_plugins/smoke.py`
  - Owns fixture-aware smoke execution and structured stage diagnostics.
- Modify: `backend/app/source_plugins/context.py`
  - Add any missing runtime helpers needed by fixture smoke or auth state.
- Modify: `backend/app/source_plugins/fetcher.py`
  - Keep network behavior core-owned; add typed diagnostics only if needed.
- Modify: `backend/app/source_plugins/models.py`
  - Add backward-compatible models/types for smoke fixtures and diagnostics if useful.
- Modify: `backend/app/source_plugins/loader.py`
  - Keep plugin loading strict and formal-ID oriented.
- Modify: `backend/app/source_plugins/scheduler.py`
  - Ensure search/detail/toc/chapter and smoke errors normalize consistently.

### Backend Services And API

- Modify: `backend/app/api/console.py`
  - Expose fixture smoke, diagnostics, auth/cookie controls, and reading-loop verification.
- Modify: `backend/app/api/legado.py`
  - Keep Reading-compatible API thin and backed by plugin runtime.
- Modify: `backend/app/services/catalog.py`
  - Ensure end-to-end flow can be tested with encoded IDs and fixture plugins.
- Modify: `backend/app/services/plugin_health_repository.py`
  - Store smoke results and diagnostic summaries.
- Modify: `backend/app/storage/db.py`
  - Add minimal schema extension only if needed; keep migration backward-compatible.

### Scripts And Templates

- Create: `backend/scripts/create_source_plugin.py`
  - Generates a formal plugin directory from a plugin ID, name, domain, base URL, and optional seed.
- Create: `backend/scripts/validate_source_plugin.py`
  - Validates metadata, source class, capabilities, smoke fixture shape, and forbidden runtime behavior.
- Create: `plugins/templates/source_plugin/metadata.yaml`
- Create: `plugins/templates/source_plugin/source.py`
- Create: `plugins/templates/source_plugin/tests/smoke.yaml`
- Create: `plugins/templates/source_plugin/README.md`
- Create: `docs/skills/book-source-craft/references/stage-2-plugin-production.md`
  - AI adaptation checklist and plugin authoring workflow.

### Plugins

- Modify: `plugins/sources/*/tests/smoke.yaml`
  - Make all 5 current plugins fixture-backed and complete for search/detail/toc/chapter.
- Modify: `plugins/sources/*/README.md`
  - Record source domain, selectors, fixture URLs, known risks, and auth/proxy status.
- Modify: `plugins/sources/*/source.py`
  - Fix parsers if fixture smoke reveals gaps.

### Frontend

- Modify: `frontend/src/routes/VerificationPage.tsx`
  - Show reading-loop verification and smoke details.
- Modify: `frontend/src/routes/PluginDetail.tsx`
  - Show smoke fixture status, diagnostics, auth/cookie controls, and recent failures.
- Modify: `frontend/src/routes/Plugins.tsx`
  - Show plugin health, last smoke result, enabled state, auth mode.
- Modify: `frontend/src/lib/api.ts`
  - Add typed API calls for new Stage 2 endpoints.
- Modify if needed: `frontend/src/components/ui/*`
  - Reuse existing shadcn/ui components; do not add fake marketing UI.

### Tests

- Create/Modify: `backend/tests/source_plugins/test_fixture_smoke_runner.py`
- Create/Modify: `backend/tests/source_plugins/test_initial_plugins.py`
- Create: `backend/tests/scripts/test_create_source_plugin.py`
- Create: `backend/tests/scripts/test_validate_source_plugin.py`
- Create: `backend/tests/test_reading_loop_api.py`
- Modify: `backend/tests/test_plugin_console_api.py`
- Modify: `backend/tests/test_frontend_static_mount.py`

### Documentation

- Modify: `docs/architecture/source-plugin-contract.md`
- Create: `docs/verification/stage-2-plugin-production-reading-loop.md`
- Modify: `docs/verification/kimi-stage-1-rework.md`
  - Correct stale numbers from Stage 1: current backend test count is 103 after frontend static/Tailwind regression tests.

---

## Task 0: Baseline And Report Correction

**Files:**

- Read: `backend/app/main.py`
- Read: `frontend/vite.config.ts`
- Read: `frontend/src/index.css`
- Modify: `docs/verification/kimi-stage-1-rework.md`
- Create: `docs/verification/stage-2-plugin-production-reading-loop.md`

- [ ] Run current baseline:

```powershell
cd backend; python -m pytest tests -q; cd ..
cd frontend; npm run build; cd ..
git diff --check
```

Expected:

- Backend tests pass. Current known count after Stage 1 repair is `103 passed, 1 warning`.
- Frontend build succeeds.
- No Tailwind `@tailwind utilities` warning.
- `git diff --check` has no whitespace errors.

- [ ] Verify frontend render regression is covered:

```powershell
cd backend; python -m pytest tests/test_frontend_static_mount.py -q; cd ..
```

Expected: `6 passed` or more. This test suite must include:

- `/console` returns HTML.
- `/assets/*.js` and `/assets/*.css` referenced by `/console` return `200`.
- CSS contains `.flex`, `.grid`, and `.p-6`.
- CSS does not contain raw `@tailwind utilities`.
- `/admin` returns `404`.

- [ ] Update `docs/verification/kimi-stage-1-rework.md`:

Required content:

```markdown
## Stage 1 Post-Repair Notes

- Backend test baseline is now `103 passed, 1 warning` after static frontend and Tailwind regression tests were added.
- Tailwind CSS v4 is wired through `@tailwindcss/vite`.
- `/console` serves JS, CSS, favicon, and renders a real sidebar/dashboard UI.
- `/admin` and `/api/admin/status` remain 404.
```

- [ ] Create `docs/verification/stage-2-plugin-production-reading-loop.md` with placeholder sections filled with initial baseline evidence:

```markdown
# Stage 2 Plugin Production And Reading Loop Verification

> Generated: 2026-06-07

## Baseline

- Backend tests:
- Frontend build:
- Console render:
- Legacy route status:

## Fixture Smoke

## Plugin Creation Tooling

## Reading Loop

## Auth And Diagnostics

## Final Verification
```

## Task 1: Define Fixture Smoke YAML Contract

**Files:**

- Modify: `docs/architecture/source-plugin-contract.md`
- Create/Modify: `backend/tests/source_plugins/test_fixture_smoke_runner.py`
- Modify: `plugins/templates/source_plugin/tests/smoke.yaml`

- [ ] Add this fixture smoke contract to `docs/architecture/source-plugin-contract.md` after the `source.py Class` section:

```markdown
## Smoke Fixture Contract

Each plugin should provide `tests/smoke.yaml`.

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

Fixture files live next to the YAML under `plugins/sources/<plugin_id>/tests/fixtures/`.

Normal CI/test smoke must use fixtures and must not require live network. Live checks may be added as a separate manual command.
```

- [ ] Write failing tests in `backend/tests/source_plugins/test_fixture_smoke_runner.py`.

Expected test names:

```python
def test_load_smoke_yaml_contract(tmp_path): ...
@pytest.mark.asyncio
async def test_run_fixture_smoke_passes_without_network(tmp_path): ...
@pytest.mark.asyncio
async def test_run_fixture_smoke_reports_stage_failure(tmp_path): ...
def test_fixture_smoke_requires_all_four_stages(tmp_path): ...
```

Assertions:

- YAML must include `keyword`, `fixtures.search`, `fixtures.detail`, `fixtures.toc`, `fixtures.chapter`, and `expect`.
- Missing stages produce `pass: False` with code `SMOKE_CONTRACT_ERROR`.
- Fixture smoke must call plugin code using a fixture fetcher, not real `httpx`.
- Passing result includes `stages.search/detail/toc/chapter.status == "ok"`.

Verification:

```powershell
cd backend; python -m pytest tests/source_plugins/test_fixture_smoke_runner.py -q; cd ..
```

Expected before implementation: failing tests that identify missing fixture smoke behavior.

## Task 2: Implement Fixture-Aware Smoke Runner

**Files:**

- Modify: `backend/app/source_plugins/smoke.py`
- Modify: `backend/app/source_plugins/context.py` if needed
- Modify: `backend/tests/source_plugins/test_fixture_smoke_runner.py`

- [ ] Implement functions in `backend/app/source_plugins/smoke.py`:

Required public functions:

```python
def load_smoke_spec(plugin_dir: Path) -> dict:
    ...

async def run_fixture_smoke(plugin: LoadedPlugin, plugin_dir: Path) -> dict:
    ...
```

Expected result shape:

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

Failure result shape:

```python
{
    "pluginId": "xbiqugu_la",
    "mode": "fixture",
    "pass": False,
    "stages": {
        "search": {"status": "error", "code": "PARSE_EMPTY", "message": "..."},
    },
    "errors": [
        {"stage": "search", "code": "PARSE_EMPTY", "message": "..."}
    ],
    "diagnostics": [
        {"stage": "search", "hint": "selector returned no results"}
    ],
}
```

- [ ] Implement an internal fixture fetcher that maps request URLs to fixture file contents.

Rules:

- `fetch_text(url)` returns fixture text when `url` exactly matches a configured fixture URL.
- If a plugin calls an unknown URL, raise an error with code `SMOKE_FIXTURE_MISSING`.
- `fetch_json` parses returned fixture text as JSON.
- `fetch_bytes` returns fixture bytes.
- `fetch_many` maps every URL through the same fixture map.

- [ ] Re-run:

```powershell
cd backend; python -m pytest tests/source_plugins/test_fixture_smoke_runner.py -q; cd ..
```

Expected: all fixture smoke runner tests pass.

## Task 3: Convert All 5 Existing Plugins To Complete Fixture Smoke

**Files:**

- Modify: `plugins/sources/xbiqugu_la/tests/smoke.yaml`
- Create/Modify: `plugins/sources/xbiqugu_la/tests/fixtures/*`
- Modify: `plugins/sources/shuhaige_net/tests/smoke.yaml`
- Create/Modify: `plugins/sources/shuhaige_net/tests/fixtures/*`
- Modify: `plugins/sources/biquge365_net/tests/smoke.yaml`
- Create/Modify: `plugins/sources/biquge365_net/tests/fixtures/*`
- Modify: `plugins/sources/xbiquzw_net/tests/smoke.yaml`
- Create/Modify: `plugins/sources/xbiquzw_net/tests/fixtures/*`
- Modify: `plugins/sources/22biqu_com/tests/smoke.yaml`
- Create/Modify: `plugins/sources/22biqu_com/tests/fixtures/*`
- Modify: `backend/tests/source_plugins/test_initial_plugins.py`

- [ ] For each plugin, ensure fixture files cover:

```text
search.html or search.json
detail.html or detail.json
toc.html or toc.json
chapter.html or chapter.json
```

- [ ] For each plugin, smoke expectations must assert:

```yaml
expect:
  search:
    minResults: 1
  detail:
    hasName: true
    hasAuthor: true
    hasTocUrl: true
  toc:
    minChapters: 1
  chapter:
    minContentLength: 20
```

- [ ] Add tests in `backend/tests/source_plugins/test_initial_plugins.py`:

Required behavior:

- Load all 5 formal plugin IDs.
- For each plugin, call `run_fixture_smoke`.
- Assert `result["pass"] is True`.
- Assert no plugin directory begins with `demo_`.
- Assert each plugin has `README.md`, `metadata.yaml`, `source.py`, and `tests/smoke.yaml`.

Verification:

```powershell
cd backend; python -m pytest tests/source_plugins/test_initial_plugins.py tests/source_plugins/test_fixture_smoke_runner.py -q; cd ..
```

Expected: all 5 plugins pass fixture smoke without network.

## Task 4: Wire Console Smoke Endpoint To Fixture Smoke And Health Store

**Files:**

- Modify: `backend/app/api/console.py`
- Modify: `backend/app/services/plugin_health_repository.py`
- Modify: `backend/tests/test_plugin_console_api.py`

- [ ] Change `POST /api/console/plugins/{plugin_id}/smoke` default mode to fixture smoke.

Request:

```json
{
  "mode": "fixture"
}
```

Default when payload is missing: `fixture`.

Optional manual live mode:

```json
{
  "mode": "live",
  "keyword": "凡人修仙传"
}
```

Live mode may call existing live smoke, but tests must not require network.

- [ ] Store smoke result through `PluginHealthRepository.update_test_result`.

Expected API result includes:

```json
{
  "pluginId": "xbiqugu_la",
  "mode": "fixture",
  "pass": true,
  "stages": {},
  "errors": [],
  "diagnostics": []
}
```

- [ ] Add API tests:

```python
def test_plugin_smoke_defaults_to_fixture_mode(): ...
def test_plugin_smoke_updates_health_last_test_result(): ...
def test_plugin_smoke_unknown_plugin_returns_error(): ...
```

Verification:

```powershell
cd backend; python -m pytest tests/test_plugin_console_api.py tests/source_plugins/test_fixture_smoke_runner.py -q; cd ..
```

## Task 5: Add Plugin Creation And Validation Scripts

**Files:**

- Create: `backend/scripts/create_source_plugin.py`
- Create: `backend/scripts/validate_source_plugin.py`
- Create: `backend/tests/scripts/test_create_source_plugin.py`
- Create: `backend/tests/scripts/test_validate_source_plugin.py`
- Create: `plugins/templates/source_plugin/metadata.yaml`
- Create: `plugins/templates/source_plugin/source.py`
- Create: `plugins/templates/source_plugin/tests/smoke.yaml`
- Create: `plugins/templates/source_plugin/README.md`

- [ ] Implement `create_source_plugin.py`.

Command contract:

```powershell
cd backend
python scripts/create_source_plugin.py --id example_com --name 示例书源 --domain example.com --base-url https://example.com
```

Expected:

- Creates `../plugins/sources/example_com/`.
- Writes metadata with `id: example_com`, `name: 示例书源`, `domains: [example.com]`, `baseUrls: [https://example.com]`.
- Writes `source.py` with `Source.id = "example_com"`.
- Writes `tests/smoke.yaml`.
- Writes `README.md`.
- Refuses IDs that do not match `^[a-z0-9][a-z0-9_]*$`.
- Refuses IDs beginning with `demo_`.
- Refuses overwrite unless `--force` is passed.

- [ ] Implement `validate_source_plugin.py`.

Command contract:

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/xbiqugu_la
```

Expected checks:

- Required files exist.
- `metadata.yaml` contract version is `1.0`.
- metadata `id` matches directory name and `Source.id`.
- capabilities are valid subset.
- `tests/smoke.yaml` exists and has all four stages.
- `source.py` does not contain forbidden strings:
  - `requests.`
  - `httpx.`
  - `threading`
  - `asyncio.create_task`
  - `engine-jvm`
  - `app.legado_engine`
  - `app.engine`
  - `demo_`

- [ ] Add tests for both scripts.

Verification:

```powershell
cd backend; python -m pytest tests/scripts/test_create_source_plugin.py tests/scripts/test_validate_source_plugin.py -q; cd ..
```

## Task 6: Build Reading-Compatible End-To-End Fixture Loop

**Files:**

- Create: `backend/tests/test_reading_loop_api.py`
- Modify: `backend/app/services/catalog.py` if needed
- Modify: `backend/app/api/legado.py` if needed
- Modify: `backend/app/source_plugins/id_codec.py` if needed

- [ ] Add a fixture-backed test that exercises:

```text
/api/legado/source
/api/legado/search?keyword=凡人修仙传&page=1
/api/legado/book/{book_id}
/api/legado/book/{book_id}/toc
/api/legado/chapter/{chapter_id}
```

- [ ] The test must use fixture plugin behavior and must not require live network.

Acceptable approaches:

- monkeypatch `PluginScheduler` to load a fixture plugin, or
- configure a test plugin directory, or
- use one existing plugin with fixture fetcher injected through a test hook.

Expected assertions:

- Source import endpoint returns at least one source object.
- Search returns at least one item with encoded `bookUrl`.
- Detail returns `name`, `author`, `tocUrl`.
- TOC returns at least one chapter with encoded chapter URL.
- Chapter returns content length > 20.

Verification:

```powershell
cd backend; python -m pytest tests/test_reading_loop_api.py -q; cd ..
```

## Task 7: Add Auth/Cookie State Framework For Future Official Sources

**Files:**

- Modify: `backend/app/storage/db.py`
- Create/Modify: `backend/app/services/plugin_auth_repository.py`
- Modify: `backend/app/source_plugins/context.py`
- Modify: `backend/app/api/console.py`
- Create: `backend/tests/test_plugin_auth_repository.py`
- Modify: `backend/tests/test_plugin_console_api.py`

- [ ] Add `plugin_auth_state` table if missing:

```sql
CREATE TABLE IF NOT EXISTS plugin_auth_state (
    plugin_id TEXT PRIMARY KEY,
    auth_status TEXT DEFAULT 'unknown',
    account_name TEXT,
    cookie_json TEXT,
    expires_at TEXT,
    last_checked_at TEXT,
    last_error TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);
```

- [ ] Implement repository methods:

```python
set_cookies(plugin_id: str, cookies: dict) -> None
get_cookies(plugin_id: str) -> dict
clear_cookies(plugin_id: str) -> None
update_status(plugin_id: str, status: dict) -> None
get_status(plugin_id: str) -> dict
```

- [ ] Wire API:

```text
GET  /api/console/plugins/{plugin_id}/auth
POST /api/console/plugins/{plugin_id}/login
POST /api/console/plugins/{plugin_id}/auth/check
POST /api/console/plugins/{plugin_id}/cookies/clear
```

Expected behavior:

- For `auth.mode: none`, status returns `authenticated: false`, `requiredActions: []`, and `mode: none`.
- For plugins with `prepare_login`, login endpoint returns the plugin result.
- Cookie clear empties stored cookie state and returns `cleared: true`.
- No browser automation is required in Stage 2; this is framework only.

Verification:

```powershell
cd backend; python -m pytest tests/test_plugin_auth_repository.py tests/test_plugin_console_api.py -q; cd ..
```

## Task 8: Improve Console Plugin Detail And Verification Pages

**Files:**

- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/routes/PluginDetail.tsx`
- Modify: `frontend/src/routes/Plugins.tsx`
- Modify: `frontend/src/routes/VerificationPage.tsx`
- Modify if needed: `frontend/src/components/ui/*`

- [ ] Plugin list page must show:

```text
Plugin ID
Chinese display name
Enabled state
Capabilities
Auth mode
Last smoke status
Last error
```

- [ ] Plugin detail page must show:

```text
Metadata
Capabilities
Domains/base URLs
Auth status
Smoke fixture action
Smoke stage results
Diagnostics/errors
Cookie clear action
```

- [ ] Verification page must show:

```text
Frontend build/static status note
Plugin fixture smoke status
Reading loop status
Legacy route status (/admin 404, /api/admin/status 404)
```

- [ ] Do not add fake metrics. If data is unavailable, show real empty state.

Verification:

```powershell
cd frontend; npm run build; cd ..
cd backend; python -m pytest tests/test_frontend_static_mount.py -q; cd ..
```

Manual/browser verification:

- Start backend.
- Open `/console`.
- Visit Plugins, Plugin Detail, Verification.
- Confirm no raw text-only UI, no missing CSS, no overlapping text.

## Task 9: Add Diagnostic Normalization

**Files:**

- Modify: `backend/app/source_plugins/errors.py`
- Modify: `backend/app/source_plugins/scheduler.py`
- Modify: `backend/app/source_plugins/smoke.py`
- Create/Modify: `backend/tests/source_plugins/test_diagnostics.py`

- [ ] Normalize failure codes:

```text
FETCH_NETWORK_ERROR
FETCH_HTTP_4XX
FETCH_HTTP_5XX
PLUGIN_TIMEOUT
PARSE_EMPTY
PARSE_ERROR
AUTH_REQUIRED
LOGIN_REQUIRED
PAID_CONTENT_REQUIRED
BROWSER_REQUIRED
CLOUDFLARE_REQUIRED
RATE_LIMITED
PLUGIN_RUNTIME_ERROR
SMOKE_CONTRACT_ERROR
SMOKE_FIXTURE_MISSING
```

- [ ] Every failure should include:

```python
{
    "stage": "search",
    "sourceId": "xbiqugu_la",
    "code": "PARSE_EMPTY",
    "message": "...",
    "url": "...",
    "hint": "检查 search selector 或 fixture HTML 是否变化",
}
```

- [ ] Add tests that trigger:

- missing fixture URL -> `SMOKE_FIXTURE_MISSING`
- empty search result -> `PARSE_EMPTY`
- timeout -> `PLUGIN_TIMEOUT`
- plugin exception -> `PLUGIN_RUNTIME_ERROR`

Verification:

```powershell
cd backend; python -m pytest tests/source_plugins/test_diagnostics.py tests/source_plugins/test_fixture_smoke_runner.py -q; cd ..
```

## Task 10: Documentation And AI Plugin Authoring Skill

**Files:**

- Create: `docs/skills/book-source-craft/references/stage-2-plugin-production.md`
- Modify: `docs/skills/book-source-craft/SKILL.md`
- Modify: `docs/architecture/source-plugin-contract.md`
- Modify: `docs/verification/stage-2-plugin-production-reading-loop.md`

- [ ] Document plugin authoring workflow:

```text
1. Pick source domain and formal plugin ID.
2. Run create_source_plugin.py.
3. Capture search/detail/toc/chapter fixture HTML or JSON.
4. Implement source.py using ctx only.
5. Run validate_source_plugin.py.
6. Run fixture smoke.
7. Open /console plugin detail and run smoke.
8. If live source is unstable, keep fixture smoke passing and document live risk.
```

- [ ] Document AI adaptation prompt template:

```text
Adapt <domain> into a LegadoHub source plugin.
Use plugin contract 1.0.
Do not use requests/httpx directly.
Use ctx.fetch_text/json, ctx.select, ctx.clean_html, ctx.urljoin.
Write fixture smoke for search/detail/toc/chapter.
Return parse diagnostics for empty selectors.
```

- [ ] Update verification report with actual command outputs and known warnings.

## Task 11: Final Verification Gate

Run all commands:

```powershell
cd backend; python -m pytest tests -q; cd ..
cd frontend; npm run build; cd ..
cd backend; python scripts/validate_source_plugin.py --plugin ../plugins/sources/xbiqugu_la; cd ..
cd backend; python scripts/validate_source_plugin.py --plugin ../plugins/sources/shuhaige_net; cd ..
cd backend; python scripts/validate_source_plugin.py --plugin ../plugins/sources/biquge365_net; cd ..
cd backend; python scripts/validate_source_plugin.py --plugin ../plugins/sources/xbiquzw_net; cd ..
cd backend; python scripts/validate_source_plugin.py --plugin ../plugins/sources/22biqu_com; cd ..
rg -n "demo_(xbiqugu|shuhaige|biquge365|xbiquzw|22biqu)|console_and_admin|legacy_compat|APIRouter\\(prefix=\""/api/admin\""\\)|@app\\.get\\(\""/admin|<Route path=\""/admin|http://127\\.0\\.0\\.1:8765/admin|管理后台|Admin API|Admin Console|admin console" backend frontend plugins docs start.bat -S -g "!docs/archive/**" -g "!frontend/dist/**" -g "!backend/data/**"
rg -n "app\\.(engine|legado_engine|web)|from app\\.(engine|legado_engine|web)|LegadoEngineRunner|SourceRepository|source_repository|app\\.rules|source_health|source_attempts|source_runtime_state|engine-jvm" backend/app backend/tests backend/scripts docs -S -g "!docs/archive/**"
git diff --check
```

Expected:

- Backend tests pass.
- Frontend builds.
- All 5 plugin validations pass.
- Residue scans have no active runtime matches. Intentional forbidden-string assertions in tests are acceptable only if clearly named as assertions.
- `/admin` and `/api/admin/status` remain 404.
- `/console` renders a real UI with generated Tailwind utilities.
- `git diff --check` passes.

## Completion Report Requirements

The final handoff report must include:

- Current branch.
- Exact test/build commands and results.
- List of plugin IDs and fixture smoke status.
- Reading-loop result summary.
- Auth/cookie framework status.
- Console pages verified.
- Known limitations and next recommended stage.
- Updated verification report path.

## One-Line Goal

Implement Stage 2 for LegadoHub: fixture-backed plugin smoke, plugin creation/validation tooling, Reading API end-to-end loop, auth/cookie framework, console diagnostics, and updated verification without restoring legacy engines, `/admin`, or `demo_*` naming.
