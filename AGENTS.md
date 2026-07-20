# AGENTS.md

Repo-specific guidance for OpenCode sessions working in `legado-hub`.
Keep the root clean; see `docs/architecture/repository-layout.md` for the boundary rules.

## Stack

- **backend/**: FastAPI runtime with a public/reader entrypoint on `8765` and an admin entrypoint on `8766`. The deployment entrypoint is `python -m app.server`; `app.main:app` is the combined compatibility/test app. Run commands from `backend/`.
- **frontend/**: React 19 + Vite + shadcn/ui console. The same built dist is served on both ports, while `/api/auth/entrypoint` selects the reader-only or administrator login/UI surface. Vite proxies to `8765` by default; set `VITE_LEGADOHUB_ENTRYPOINT=admin` to proxy to `8766`.
- **plugins/**: source plugins loaded at runtime by `app/source_plugins/loader.py`, which recursively scans `plugins/sources/**/metadata.yaml`.

## First-time setup / dev run

`start.bat` (Windows) is the canonical bootstrap: it creates `.venv`, installs `backend/requirements.txt`, runs `python -m playwright install chromium`, builds the frontend, then starts uvicorn. Manual equivalent:

```
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
.venv/Scripts/python.exe -m playwright install chromium
cd frontend && npm install && npm run build
cd ../backend && ../.venv/Scripts/python.exe -m app.server --host 0.0.0.0 --public-port 8765 --admin-port 8766
```

On first startup the lifespan handler initializes the SQLite DB at `backend/data/app.db` and **prints a default `admin` password** to stdout; change it after first login.

## Commands

Backend (run from `backend/`):
- Run server: `python -m app.server --host 0.0.0.0 --public-port 8765 --admin-port 8766`
- Tests: `pytest` (config lives in `backend/pytest.ini`; `asyncio_mode = auto`)
- Single test: `pytest ../dev-assets/tests/test_shared_book_storage.py`
- Maintenance scripts: `python scripts/create_source_plugin.py`, `python scripts/validate_source_plugin.py` (these are the only scripts that belong in `backend/scripts/`; put probes/benchmarks in `dev-assets/`)

Frontend (run from `frontend/`):
- Dev server: `npm run dev`
- Build: `npm run build` (runs `tsc -b` then `vite build`)
- Lint: `npm run lint`
- Tests: `npx vitest` (jsdom; no `test` script defined; config is inside `vite.config.ts` via the `vitest/config` import)

There is no command-order contract beyond: build frontend before running the server in Docker/production, since the backend serves `frontend/dist`.

## Validation cadence

- Do not run the full test suite after every small code edit.
- For a small task, finish the complete scoped change first, then run the relevant tests once as a batch.
- For a large task, split the work into explicit phases and run the phase-relevant tests once at the end of each phase.
- Focused syntax checks or a single regression test are allowed while diagnosing a concrete failure; they do not replace the phase gate.
- Before any commit, push, release, or claim that implementation is ready to commit, run the canonical full verification once with `verify.ps1`.
- Never claim a phase or task passed without reporting the actual commands and results from its scheduled validation gate.

## Tests are split between repo and local-only `dev-assets/`

This is the most likely thing to trip you up:

- `dev-assets/` is **gitignored**. Only a small allow-list of test files plus `dev-assets/tests/conftest.py` are committed (see the `!dev-assets/tests/...` block in `.gitignore`).
- `backend/pytest.ini` points `testpaths` to `../dev-assets/tests` and `--ignore`s many files there.
- `dev-assets/tests/conftest.py` *also* `pytest_ignore_collect`s a second set of files (live-acceptance, official-auth, source-plugin-fixture tests, etc.) because those depend on local-only assets.
- Net effect: a fresh checkout runs only the committed subset. Do not assume a test file you see referenced exists in the repo; do not rely on `dev-assets/tests/source_plugins/`, `official_auth/`, or any `test_*` listed in the ignore blocks.
- `dev_assets_test_loader.py` at the repo root contains a **hardcoded absolute path** `C:\Home\Workspace\UGit\legado-hub\...`; it breaks if the repo is relocated. Prefer importing test helpers through normal `pytest`/`pythonpath` rather than extending that loader.

## Plugin contract

- Each plugin is a directory under `plugins/sources/` (subdirs `official/`, `thirdparty/` are scanned recursively) containing `metadata.yaml` + `source.py`.
- `source.py` must export a `Source` class with **async** methods matching each `capability` declared in metadata (`search`, `detail`, `toc`, `chapter`, `chapter_reviews`, `explore`, `auth`; `explore` requires `explore_groups` + `explore`).
- `plugins/sources/official/` is gitignored — don't commit official plugins.
- Docker images must not contain `plugins/sources/official/`; Compose mounts that host directory read-only so operators can place official plugins after deployment.
- Docker images keep bundled third-party plugins under `/opt/legadohub/plugins/thirdparty`. The optional `docker-compose.plugins.yml` bind mount targets `/app/plugins/sources/thirdparty` directly and must be writable by `LEGADOHUB_APP_UID/GID`; the entrypoint copies the bundled set only when that directory is empty. Once populated, the host directory is authoritative and is never overwritten on startup.
- Official Qidian plugins are authored in the sibling repo `C:\Home\Workspace\UGit\QDFCCKK`; edit `source-plugin/WEB-plugin` or `source-plugin/APP-plugin` there first, then run `python sync-to-legado-hub.py --variant WEB-plugin` or `python sync-to-legado-hub.py --variant APP-plugin`. Do not hand-edit synced files under `plugins/sources/official/qidian_com_*` except for emergency inspection.
- Authoritative contract: `docs/architecture/source-plugin-contract.md` (+ `.zh-CN.md`). Template scaffold: `plugins/templates/source_plugin/`.
- Plugins must not own global concurrency/timeout/proxy/retry/cache/scheduling policy — those are backend runtime responsibilities.
- For writing new plugins, start at `docs/skills/book-source-craft/README.md`.

## Config and runtime data (mostly gitignored)

All paths centralized in `backend/app/config.py`:
- Unified runtime config: `backend/config/app_config.json`
- Per-plugin cookies: `backend/config/cookies/<plugin_id>.json` (host-store; legacy in-plugin `Cookie.json` is auto-migrated on startup)
- Runtime data under `backend/data/`: `app.db`, `browser_profiles/`, `novels/`, `lexicons/`, `cache/`, etc.
- Generated Legado aggregate output: `backend/generated/`

Do not commit DBs, cookies, `app_config.json`, or anything under `backend/data/` or `backend/runtime/`.

## Browser / Playwright (Source Access Bridge)

Controlled by env (see `.env.example`):
- `LEGADOHUB_BROWSER_ENABLED` (1/0)
- `LEGADOHUB_BROWSER_PROVIDER`: `chromium` (embedded, requires `playwright install chromium`) or `browserless` (remote; set `LEGADOHUB_BROWSERLESS_WS` + optional `_TOKEN`)
- `LEGADOHUB_BROWSER_PUBLIC_BASE_URL`, `LEGADOHUB_BROWSER_PROFILE_ROOT`, `LEGADOHUB_BROWSER_CONNECT_TIMEOUT_MS`, `LEGADOHUB_BROWSER_ACTION_TIMEOUT_MS`

Docker builds use `node:22` frontend stage + `python:3.12-slim` runtime with `playwright install --with-deps chromium`; backend state remains in the container writable layer and is lost when the container is replaced or removed. `docker-compose.yml` exposes reader port `8765` and admin port `8766`. The admin host binding defaults to `0.0.0.0` by product decision; deployment operators own its firewall, forwarding, TLS, and management-network restrictions.

## Conventions

- Default shell guidance here is PowerShell on Windows, but `start.bat` is a `.bat` entrypoint (CRLF, `@echo off`); don't rewrite it as PowerShell.
- Source files use LF; Windows batch uses CRLF.
- Frontend uses `@` alias to `frontend/src` (see `vite.config.ts`); ESLint allows `any` and disables `react-refresh/only-export-components` under `src/components/ui/**`.
- No CI workflows are defined in this repo; verification is local (`pytest`, `npm run lint`, `npm run build`).
