# Stage 2 Plugin Production And Reading Loop Verification

> Generated: 2026-06-07

## Baseline

- Backend tests: `cd backend; python -m pytest tests -q` -> `103 passed, 1 warning`
- Frontend build: `cd frontend; npm run build` -> build succeeded, generated CSS/JS assets
- Console render: covered by `backend/tests/test_frontend_static_mount.py` -> `6 passed, 1 warning`
- Legacy route status: `/admin` and `/api/admin/status` covered as `404`
- Whitespace check: `git diff --check` -> passed

## Fixture Smoke

- Added fixture-backed smoke contract to `docs/architecture/source-plugin-contract.md`.
- Added `load_smoke_spec()` and `run_fixture_smoke()` in `backend/app/source_plugins/smoke.py`.
- All 5 formal plugins now include `tests/smoke.yaml` plus search/detail/toc/chapter fixture files.
- Verification: `cd backend; python -m pytest tests/source_plugins/test_initial_plugins.py tests/source_plugins/test_fixture_smoke_runner.py tests/test_plugin_console_api.py -q` -> `28 passed, 1 warning`

## Plugin Creation Tooling

- Added `backend/scripts/create_source_plugin.py`.
- Added `backend/scripts/validate_source_plugin.py`.
- Added source plugin template under `plugins/templates/source_plugin/`.
- Verification: `cd backend; python -m pytest tests/scripts/test_create_source_plugin.py tests/scripts/test_validate_source_plugin.py -q` -> `6 passed`
- All 5 current plugins validate through CLI: `OK`

## Reading Loop

- Added fixture-backed end-to-end Reading-compatible API test.
- Covered `/api/legado/source`, `/api/legado/search`, `/api/legado/book/{book_id}`, `/api/legado/book/{book_id}/toc`, and `/api/legado/chapter/{chapter_id}`.
- Verification: `cd backend; python -m pytest tests/test_reading_loop_api.py -q` -> `1 passed, 1 warning`

## Auth And Diagnostics

- Added `plugin_auth_state` table.
- Added `backend/app/services/plugin_auth_repository.py`.
- Wired persisted cookies into `PluginContext` and `PluginScheduler`.
- Console auth endpoints return `mode`, cookie state, and clear persisted cookies.
- Added normalized diagnostics with `sourceId`, `stage`, `code`, `message`, `url`, `hint`, and `extra`.
- Verification: `cd backend; python -m pytest tests/test_plugin_auth_repository.py tests/test_plugin_console_api.py -q` -> `15 passed, 1 warning`
- Verification: `cd backend; python -m pytest tests/source_plugins/test_diagnostics.py tests/source_plugins/test_fixture_smoke_runner.py -q` -> `8 passed`

## Console UI

- Plugin list shows auth mode, last smoke status, and last error.
- Plugin detail shows metadata, auth status, smoke fixture stages, and diagnostics.
- Verification page shows Reading API loop endpoints and plugin smoke summary.
- Verification: `cd frontend; npm run build` -> build succeeded

## Final Verification

- Backend full test: `cd backend; python -m pytest tests -q` -> `127 passed, 1 warning`
- Frontend build: `cd frontend; npm run build` -> build succeeded
- Plugin validation:
  - `xbiqugu_la` -> `OK`
  - `shuhaige_net` -> `OK`
  - `biquge365_net` -> `OK`
  - `xbiquzw_net` -> `OK`
  - `22biqu_com` -> `OK`
- Browser verification: Edge headless loaded `http://127.0.0.1:8765/console`, rendered the React sidebar, Tailwind utility classes, and `Plugin Runtime Stage 2`.
- Residue scan: active runtime has no `/admin` route or `demo_*` plugin naming. Matches are limited to planning/docs/test assertions that explicitly document forbidden legacy patterns.
- Legacy engine scan: active backend runtime does not import old engine modules. Matches are limited to archive/architecture/planning documentation and validator forbidden-string lists.
- Whitespace check: `git diff --check` -> passed

## Known Warnings

- FastAPI TestClient emits `StarletteDeprecationWarning` for the current `httpx` integration. This is pre-existing and does not fail tests.
