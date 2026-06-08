# Kimi Stage 1 Rework Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. This repository has already archived old Reading/JVM/server-rendered console paths. Do not restore archived code into active paths.

**Goal:** Rework Stage 1 into a clean Python source-plugin runtime with 1 to 5 working So Novel-derived plugins and a complete React/Vite/shadcn/ui console.

**Architecture:** Active source execution must run through `backend/app/source_plugins/` and `plugins/sources/`. Reading/Legado remains only the aggregate output compatibility layer through `/api/legado/*`. Runtime health, attempts, smoke results, auth state, cache, proxy, timeout, and concurrency are owned by LegadoHub core, not plugin scripts.

**Tech Stack:** Python 3.12, FastAPI, SQLite, asyncio, httpx, pytest, PyYAML, React, Vite, TypeScript, Tailwind CSS, shadcn/ui, lucide-react, TanStack Query.

---

## Current Clean Boundary

Active paths:

- `backend/app/source_plugins/`
- `backend/app/services/plugin_health_repository.py`
- `backend/app/services/catalog.py`
- `backend/app/services/search_jobs.py`
- `backend/app/services/book_catalog.py`
- `backend/app/api/console.py`
- `backend/app/api/legado.py`
- `backend/app/core/source_generator.py`
- `plugins/sources/`
- `plugins/seeds/so-novel/`
- `frontend/`
- `docs/architecture/source-plugin-contract.md`
- `docs/architecture/plugin-source-runtime-restart-plan.md`

Archived paths:

- `docs/archive/legacy-reading-engine/2026-06-07/engine-jvm/`
- `docs/archive/legacy-reading-engine/2026-06-07/app/engine/`
- `docs/archive/legacy-reading-engine/2026-06-07/app/legado_engine/`
- `docs/archive/legacy-reading-engine/2026-06-07/app/web/`
- `docs/archive/legacy-reading-engine/2026-06-07/app/rules/`
- `docs/archive/legacy-reading-engine/2026-06-07/app/services/source_repository.py`
- `docs/archive/legacy-reading-engine/2026-06-07/app/services/verification_harness.py`
- `docs/archive/legacy-reading-engine/2026-06-07/docs/superpowers/plans/2026-06-07-stage-1-plugin-engine-shadcn-admin.md`

Do not import, copy, or revive archived runtime code. Archived files are reference-only.

## Required Rework Outcome

- Python plugin engine is complete enough for search, detail, toc, and chapter.
- 1 to 5 initial source plugins exist, seeded from `freeok/so-novel`.
- Every shipped plugin has metadata, source implementation, smoke fixture, and adaptation notes.
- Plugin scripts do not control global concurrency, timeout, proxy, cache, retry, or scheduling.
- Console API exposes plugin list/detail/reload/enable/smoke/auth/login/cookie operations, search jobs, cache, settings, aggregate source, and plugin health.
- React console is real shadcn/ui, not hand-written lookalike components. It must contain `components/ui/*` generated/adapted from shadcn/ui and Radix/shadcn dependencies in `frontend/package.json`.
- Frontend has distinct pages for dashboard, plugins, plugin detail, plugin auth/login, search jobs, books/reader, cache, settings, aggregate source, and verification/status.
- Aggregate Reading source remains thin and calls `/api/legado/*` backed by plugin runtime.

## Task 0: Confirm Clean Baseline

**Files:**

- Read: `docs/archive/legacy-reading-engine/2026-06-07/README.md`
- Read: `docs/architecture/repository-layout.md`
- Read: `docs/architecture/source-plugin-contract.md`
- Read: `docs/architecture/plugin-source-runtime-restart-plan.md`
- Read: `backend/app/source_plugins/`
- Read: `frontend/package.json`

- [ ] Run legacy active-reference scan:

```powershell
rg -n "app\.(engine|legado_engine|web)|from app\.(engine|legado_engine|web)|LegadoEngineRunner|SourceRepository|source_repository|app\.rules|source_health|source_attempts|source_runtime_state|engine-jvm" backend/app backend/tests backend/scripts docs -S -g "!docs/archive/**"
```

Expected: matches only in `archive/`, boundary docs, or explicit forbidden-path text. No active Python import may reference archived modules.

- [ ] Run current test baseline:

```powershell
cd backend; python -m pytest tests -q; cd ..
```

Expected: all active tests pass before rework begins.

## Task 1: Finish Plugin Health Store Cleanup

**Files:**

- Modify: `backend/app/storage/db.py`
- Modify: `backend/app/services/plugin_health_repository.py`
- Modify: `backend/tests/source_plugins/` or create `backend/tests/test_plugin_health_repository.py`

- [ ] Add tests that assert `plugin_health` and `plugin_attempts` are created, and no active code references `source_health`, `source_attempts`, or `source_repository`.
- [ ] Ensure `PluginHealthRepository.ensure_plugin`, `record_attempt`, `record_success`, `record_failure`, `get_plugins`, `get_plugin`, `get_attempts`, and `get_stats` are covered.
- [ ] Keep response compatibility aliases such as `sourceId` only where API clients still need them.

Verification:

```powershell
cd backend; python -m pytest tests/test_plugin_health_repository.py tests/test_plugin_console_api.py -q; cd ..
```

## Task 2: Rebuild Console API Around Plugins

**Files:**

- Modify: `backend/app/api/console.py`
- Modify: `backend/app/services/catalog.py`
- Modify: `backend/app/services/search_jobs.py`
- Modify: `backend/tests/test_plugin_console_api.py`
- Modify: `backend/tests/test_single_source_test_api.py`

- [ ] Prefer `/api/console/plugins/*` for active plugin operations.
- [ ] Keep `/api/console/sources/*` only as a temporary legacy alias that returns `legacyAlias: true`.
- [ ] Make `/api/console/status` return `pluginStats` as the primary field and `sourceStats` as compatibility alias.
- [ ] Replace stubbed legacy verification with plugin runtime checks or mark it clearly as `archived: true` until a real plugin verifier is implemented.

Verification:

```powershell
cd backend; python -m pytest tests/test_plugin_console_api.py tests/test_single_source_test_api.py tests/test_realtime_search_api.py -q; cd ..
```

## Task 3: Audit And Repair Existing Plugins

**Files:**

- Modify: `plugins/sources/*/metadata.yaml`
- Modify: `plugins/sources/*/source.py`
- Modify: `plugins/sources/*/tests/smoke.yaml`
- Modify: `backend/tests/source_plugins/test_initial_plugins.py`

- [ ] For each plugin, verify metadata follows `docs/architecture/source-plugin-contract.md`.
- [ ] Confirm each plugin has clear `auth`, `rate_limit`, `proxy`, and `content` metadata fields.
- [ ] Run smoke for search, detail, toc, and chapter using fixture-backed tests.
- [ ] Disable or mark any unreliable plugin instead of claiming it works.

Verification:

```powershell
cd backend; python -m pytest tests/source_plugins -q; cd ..
```

## Task 4: Convert So Novel Seeds Into 1 To 5 Plugins

**Files:**

- Read: `plugins/seeds/so-novel/`
- Modify: `backend/scripts/inspect_so_novel_rules.py`
- Create/Modify: `plugins/sources/<plugin_id>/`
- Modify: `backend/tests/source_plugins/test_initial_plugins.py`

- [ ] Use `freeok/so-novel` seed data already captured in `plugins/seeds/so-novel/`.
- [ ] Pick 1 to 5 maintainable sources with full search/detail/toc/chapter coverage.
- [ ] For each source, write plugin code manually in Python, not a generic Reading/So Novel interpreter.
- [ ] Keep special-site handling inside the plugin, but use `ctx.fetch`, `ctx.cookies`, `ctx.trace`, and shared helpers for network/runtime behavior.

Verification:

```powershell
cd backend; python -m pytest tests/source_plugins tests/scripts/test_inspect_so_novel_rules.py -q; cd ..
```

## Task 5: Replace Frontend With Real shadcn/ui

**Files:**

- Modify: `frontend/package.json`
- Modify: `frontend/components.json`
- Create/Modify: `frontend/src/components/ui/*`
- Modify: `frontend/src/routes/*`
- Modify: `frontend/src/components/layout/*`
- Modify: `backend/tests/test_frontend_static_mount.py`

- [ ] Install missing frontend dependencies if needed.
- [ ] Ensure `frontend/package.json` includes real shadcn/Radix dependencies used by generated UI components.
- [ ] Build shadcn/ui components under `frontend/src/components/ui/`.
- [ ] Keep the design dense, Chinese, operational, and data-first.
- [ ] Do not create landing pages, fake demo metrics, or marketing copy.
- [ ] Add routes for plugin detail and plugin auth/login management.

Verification:

```powershell
cd frontend; npm run build; cd ..
cd backend; python -m pytest tests/test_frontend_static_mount.py -q; cd ..
```

## Task 6: Browser Verification

**Files:**

- Modify if needed: `frontend/src/*`
- Modify if needed: `backend/app/main.py`
- Create/Modify: `docs/verification/kimi-stage-1-rework.md`

- [ ] Start backend:

```powershell
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

- [ ] Open `http://127.0.0.1:8765/console`.
- [ ] Verify dashboard, plugin list, plugin detail, auth/login controls, search job page, cache/settings, aggregate source, and status/verification pages render.
- [ ] Check no text overlap and no blank page.
- [ ] Record screenshots or written evidence in `docs/verification/kimi-stage-1-rework.md`.

## Task 7: Final Verification

Run all commands:

```powershell
cd backend; python -m pytest tests -q; cd ..
cd frontend; npm run build; cd ..
rg -n "app\.(engine|legado_engine|web)|from app\.(engine|legado_engine|web)|LegadoEngineRunner|SourceRepository|source_repository|app\.rules|source_health|source_attempts|source_runtime_state|engine-jvm" backend/app backend/tests backend/scripts docs -S -g "!docs/archive/**"
git diff --check
```

Expected:

- Active tests pass.
- Frontend builds.
- Legacy scan has no active runtime references.
- Any remaining matches are either archive paths or explicit forbidden-path documentation.
- `git diff --check` has no whitespace errors.

## One-Line Goal

Rework Stage 1 on the cleaned LegadoHub branch: finish the Python source-plugin runtime, 1-5 So Novel-derived plugins, real shadcn/ui console, plugin health/auth/smoke APIs, and verified aggregate Reading compatibility without restoring archived legacy engine code.
