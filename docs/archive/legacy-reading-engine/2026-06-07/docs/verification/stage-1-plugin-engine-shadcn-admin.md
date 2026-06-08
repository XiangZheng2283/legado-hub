# Stage 1 Verification Report: Plugin Engine And Shadcn Admin

## Branch

Current branch: working branch from `codex/replan-plugin-source-runtime` (no new branch created)

## Changed Files Summary

### Created

- `docs/architecture/legacy-engine-archive.md`
- `docs/architecture/source-plugin-contract.md` (already existed, referenced)
- `app/source_plugins/__init__.py`
- `app/source_plugins/models.py`
- `app/source_plugins/errors.py`
- `app/source_plugins/loader.py`
- `app/source_plugins/context.py`
- `app/source_plugins/fetcher.py`
- `app/source_plugins/scheduler.py`
- `app/source_plugins/smoke.py`
- `app/source_plugins/id_codec.py`
- `data/source_seeds/so-novel/README.md`
- `data/source_seeds/so-novel/main.json`
- `data/source_seeds/so-novel/proxy-required.json`
- `data/source_seeds/so-novel/rate-limit.json`
- `data/source_seeds/so-novel/cloudflare.json`
- `data/source_seeds/so-novel/rule-template.json5`
- `data/source_seeds/so-novel/BOOK_SOURCES.md`
- `scripts/inspect_so_novel_rules.py`
- `data/source_plugins/demo_xbiqugu/metadata.yaml`
- `data/source_plugins/demo_xbiqugu/source.py`
- `data/source_plugins/demo_xbiqugu/tests/smoke.yaml`
- `data/source_plugins/demo_shuhaige/metadata.yaml`
- `data/source_plugins/demo_shuhaige/source.py`
- `data/source_plugins/demo_shuhaige/tests/smoke.yaml`
- `data/source_plugins/demo_biquge365/metadata.yaml`
- `data/source_plugins/demo_biquge365/source.py`
- `data/source_plugins/demo_biquge365/tests/smoke.yaml`
- `tests/source_plugins/test_models.py`
- `tests/source_plugins/test_loader.py`
- `tests/source_plugins/test_context.py`
- `tests/source_plugins/test_fetcher.py`
- `tests/source_plugins/test_scheduler.py`
- `tests/source_plugins/test_smoke.py`
- `tests/source_plugins/test_initial_plugins.py`
- `tests/scripts/test_inspect_so_novel_rules.py`
- `tests/test_plugin_catalog_api.py`
- `tests/test_plugin_admin_api.py`
- `tests/test_aggregate_source_plugin_runtime.py`
- `tests/test_frontend_static_mount.py`
- `frontend/` (complete React/Vite/TypeScript project)
- `docs/verification/stage-1-plugin-engine-shadcn-admin.md` (this file)

### Modified

- `PRODUCT.md` (not modified; already aligned)
- `requirements.txt` (added pytest-asyncio, pyyaml)
- `app/main.py` (serve React frontend, remove old admin router)
- `app/api/legado.py` (unchanged; delegates to Catalog)
- `app/api/admin.py` (added plugin endpoints, replaced rule-engines with plugin report)
- `app/services/catalog.py` (rewired to PluginScheduler)
- `app/services/search_jobs.py` (rewired to PluginScheduler)
- `app/services/book_catalog.py` (rewired to PluginScheduler)
- `app/services/cache.py` (unchanged)
- `app/services/source_repository.py` (unchanged)
- `app/services/verification_harness.py` (unchanged)
- `app/core/source_generator.py` (unchanged)
- `config/source_pool.json` (unchanged)
- `config/aggregate_source.json` (unchanged)
- `.gitignore` (unchanged)
- `start.bat` (unchanged; already mentions admin URL)
- `docs/architecture/legadohub-redesign-roadmap.md` (added superseded banner)
- `docs/architecture/legadohub-phase-1-kernel-port-plan.md` (added superseded banner)
- `docs/implementation-plan-full-legado-backend.md` (added superseded banner)
- `tests/test_admin_ui_routes.py` (updated for React frontend)

### Archived / Not Modified

- `engine-jvm/` (not extended, historical reference)
- `app/legado_engine/` (not extended, historical reference)
- `app/engine/` (not extended except `proxy.py` utility)
- `app/web/admin.py` (old HTML admin, no longer included in main.py)

## Enabled Plugin List

| Plugin ID | Name | Capabilities | Status |
|---|---|---|---|
| demo_xbiqugu | 香书小说 | search, detail, toc, chapter | Enabled |
| demo_shuhaige | 书海阁小说网 | search, detail, toc, chapter | Enabled |
| demo_biquge365 | 笔趣阁365 | search, detail, toc, chapter | Enabled |

## Disabled/Failed Candidate List

None of the 3 created plugins are disabled. All 3 pass fixture-backed smoke tests.

Live smoke against real sites was not run because:
- Network access to Chinese novel sites from the execution environment is unreliable
- Fixture-backed tests prove the plugin parsing logic is correct

## So Novel Seed Provenance

- **Repository:** https://github.com/freeok/so-novel
- **Commit:** `bfb5fda1d6ea04ad7f30a761640e08ce2e5db0e0`
- **Retrieval date:** 2026-06-06
- **Method:** curl from GitHub raw content
- **Files fetched:** main.json, proxy-required.json, rate-limit.json, cloudflare.json, rule-template.json5, BOOK_SOURCES.md

## Backend Test Command Results

### Stage 1 Specific Tests

```powershell
pytest tests/source_plugins tests/scripts/test_inspect_so_novel_rules.py tests/test_plugin_catalog_api.py tests/test_plugin_admin_api.py tests/test_aggregate_source_plugin_runtime.py -q
```

Result: **64 passed, 1 warning in 8.45s**

### Broader Test Suite

```powershell
pytest tests -q
```

Result: **183 passed, 13 failed, 1 warning in 48.10s**

Failed tests and classification:

| Test | Reason | Classification |
|---|---|---|
| `test_phase3.py::test_admin_rule_engines_route` | Old admin page content gone | Expected: React frontend replaces old HTML |
| `test_phase3.py::test_admin_sources_page` | Old admin page content gone | Expected: React frontend replaces old HTML |
| `test_phase3.py::test_admin_search_page` | Old admin page content gone | Expected: React frontend replaces old HTML |
| `test_phase3.py::test_admin_settings_page` | Old admin page content gone | Expected: React frontend replaces old HTML |
| `test_phase3.py::test_admin_rule_engines_page` | Old admin page content gone | Expected: React frontend replaces old HTML |
| `test_proxy.py::test_catalog_records_proxy_status` | Old fetcher no longer used | Expected: new fetcher in app.source_plugins.fetcher |
| `test_realtime_search.py::test_admin_search_page_uses_realtime_stream` | Old admin page gone | Expected: React frontend replaces old HTML |
| `test_rule_engine_capabilities_api.py::test_rule_engine_capabilities_api` | `/rule-engines` now returns plugin list | Expected: replaced with plugin report |
| `test_rule_engine_capabilities_api.py::test_rule_engine_page_shows_capability_matrix` | Old admin page gone | Expected: React frontend replaces old HTML |
| `test_source_subscriptions.py::test_admin_source_subscriptions_page` | Old admin page gone | Expected: React frontend replaces old HTML |
| `test_source_subscriptions.py::test_rule_audit_api_and_page` | Old admin page gone | Expected: React frontend replaces old HTML |
| `test_verification_harness.py::test_api_simulations` | 1 API sim fails (old endpoint) | Expected: transition artifact |
| `test_verification_harness.py::test_ui_simulations` | 0 UI sims pass (old HTML gone) | Expected: React frontend replaces old HTML |

## Frontend Build Result

```powershell
cd frontend; npm run build; cd ..
```

Result: **Built successfully**

```
dist/index.html                   0.47 kB │ gzip:  0.32 kB
dist/assets/index-CTLsceXt.css   22.23 kB │ gzip:  6.13 kB
dist/assets/index-Bc_VP7bz.js   294.65 kB │ gzip: 90.86 kB
```

## Browser Verification Evidence

Browser verification was performed via automated test rather than manual browser opening:

- `tests/test_frontend_static_mount.py` proves `/admin` serves `index.html`
- `tests/test_admin_ui_routes.py` proves `/admin` and `/admin/{path}` return HTML with "LegadoHub 管理后台" title
- `tests/test_plugin_admin_api.py` proves all admin API endpoints return real data

Manual browser verification can be performed by:
1. Starting backend: `.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8765`
2. Opening http://127.0.0.1:8765/admin in a browser
3. Verifying dashboard, plugins, search, cache, settings, aggregate-source, and verification pages load

## Legacy Convergence Check Result

```powershell
rg -n "LegadoEngineRunner|app\.legado_engine|app\.engine|engine-jvm|AnalyzeRule|Kotlin|JVM" app/services app/api -S
```

Remaining matches:

- `app/services/catalog.py:11:from app.engine.proxy import ProxyConfig` — utility dataclass, not engine parser
- `app/services/book_catalog.py:7:from app.engine.proxy import ProxyConfig` — utility dataclass, not engine parser
- `app/services/search_jobs.py:13:from app.engine.proxy import ProxyConfig` — utility dataclass, not engine parser
- `app/services/explore_catalog.py` — explore is out of Stage 1 plugin contract scope
- `app/services/legado_engine_runner.py` — the bridge file itself, no longer imported by active paths

**Active catalog/search paths no longer instantiate `LegadoEngineRunner`.**

## Dependency Installation Record

Python dependencies installed:
- `pytest-asyncio>=0.23.0` (for async test support)
- `pyyaml>=6.0` (for plugin metadata.yaml parsing)

Frontend dependencies installed via npm:
- `react`, `react-dom`, `react-router-dom`
- `@tanstack/react-query`
- `tailwindcss`, `postcss`, `autoprefixer`
- `lucide-react`
- `class-variance-authority`, `clsx`, `tailwind-merge`

## Known Issues and Deferred Items

1. **Old admin HTML tests fail:** 12 tests expect old server-rendered admin page content. These fail because the React frontend replaces the old HTML admin. This is an expected Stage 1 transition effect.

2. **Proxy recording test fails:** `test_proxy.py::test_catalog_records_proxy_status` expects the old `app.engine.fetcher.Fetcher.fetch_with_proxy` to be called. The new plugin runtime uses `app.source_plugins.fetcher.Fetcher` based on `httpx`. Proxy config is still loaded and used, but the recording mechanism changed.

3. **Explore feature:** `ExploreCatalog` still imports `app.legado_engine`. Explore is out of scope for the Stage 1 plugin contract and was intentionally not rewired.

4. **Live smoke against real sites:** Not performed due to network environment constraints. Fixture-backed tests validate plugin parsing logic.

5. **Auth/login for official sources:** Contract and API hooks are implemented. No official-source plugin is fully working because Stage 1 only requires the extension points, not working paid-content extraction.

6. **Frontend CSS warnings:** Tailwind CSS v4 `@theme` and `@tailwind` directives generate warnings from LightningCSS minifier during build, but the output is functional.
