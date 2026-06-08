# Stage 3 Console Search And Live Acceptance

Date: 2026-06-07
Branch: `codex/replan-plugin-source-runtime`
Goal: `/console` search workbench, structured search progress, candidate verification, and live acceptance for the current five formal source plugins.

## Scope

- Kept the active repository layout under `backend/`, `frontend/`, `plugins/`, and `docs/`.
- Did not restore the archived legacy Reading/JVM engine.
- Did not restore `/admin` or `/api/admin/*`.
- Kept formal plugin IDs: `22biqu_com`, `biquge365_net`, `xbiqugu_la`, `xbiquzw_net`, `shuhaige_net`.
- Implemented backend live acceptance through console API endpoints, not one-off external scripts.

## Backend Capabilities

- Search jobs now expose candidate groups through:
  - `GET /api/console/search-jobs/{job_id}/candidates`
  - `POST /api/console/search-jobs/{job_id}/candidates/{candidate_id}/verify`
- Plugin live checks now expose:
  - `POST /api/console/plugins/{plugin_id}/live-check`
  - `GET /api/console/plugins/{plugin_id}/live-checks`
  - `GET /api/console/plugins/{plugin_id}/live-checks/latest`
  - `GET /api/console/live-checks`
- Search events include structured source states:
  - `source_start`
  - `source_done`
  - `source_empty`
  - `source_timeout`
  - `source_error`
  - `candidate_grouped`
- Runtime phase is now `plugin-runtime-stage-3`.
- Source runtime timeout was aligned to real network behavior:
  - `source_timeout_seconds`: 15
  - `overall_search_timeout_seconds`: 45

## Console UI

The `/console/search` page is now the primary search workbench:

- User enters a keyword in one search box.
- Results are shown as a book candidate list.
- Each candidate row shows title, author, latest chapter, source count, score, and verification action.
- Expanding a row shows the matching source/plugin rows.
- The progress strip shows completed source count, success/failure count, elapsed time, current active source, and a progress bar.
- After completion, the current-source area displays `已完成` instead of stale source names.

Screenshots:

- `docs/verification/stage-3-console-search.png`
- `docs/verification/stage-3-console-search-live-final.png`

## Real Console Search Evidence

Browser automation opened:

`http://127.0.0.1:8765/console/search`

Search keyword:

`凡人修仙传`

Observed result:

- Page title: `LegadoHub 控制台`
- Static assets loaded without failed requests.
- Runtime label: `Plugin Runtime Stage 3`
- Search status: `completed`
- Source progress: `5/5 书源`
- Success count: `成功 5`
- Failure count: `失败 0`
- Candidate count: `31 本`
- Progress current state after completion: `已完成`
- The candidate verification dialog returned chapter content with non-zero body length.

The first exact-title candidate grouped four matching sources. `biquge365_net` returned a same-title candidate with a different author field, so it appears as a separate candidate. This is expected because multiple returned books/candidates are valid behavior.

## Live Acceptance Evidence

The following checks were executed through:

`POST /api/console/plugins/{plugin_id}/live-check`

Keyword:

`凡人修仙传`

| Plugin ID | Status | Search Count | Selected | Author | TOC Count | Chapter | Content Length |
| --- | --- | ---: | --- | --- | ---: | --- | ---: |
| `22biqu_com` | passed | 15 | 凡人修仙传 | 忘语 | 200 | 第1章 山边小村 | 2823 |
| `biquge365_net` | passed | 7 | 凡人修仙传 | 烽火连天_ | 5 | 序章 仙之大陆 | 6123 |
| `xbiqugu_la` | passed | 15 | 凡人修仙传 | 忘语 | 63 | 第1章 山边小村 | 1557 |
| `xbiquzw_net` | passed | 15 | 凡人修仙传 | 忘语 | 63 | 第1章 山边小村 | 1557 |
| `shuhaige_net` | passed | 10 | 从杂役娶妻开始建立长生家族 |  | 51 | 第一百二十四章 七夕大会，暴爽结局！ | 556 |

Notes:

- `xbiquzw_net` currently uses a parser-compatible live fallback because the original seed domains were not reachable during repair. Keep the formal plugin ID; replace the fallback domain later when a stable `xbiquzw` domain is found.
- `shuhaige_net` search may return recommendation-like candidates, but live acceptance confirms that the returned candidate can fetch TOC and chapter content through the plugin runtime.

## Verification Commands

Backend:

```powershell
cd backend
python -m pytest tests -q
```

Result:

`130 passed, 1 warning in 43.77s`

Frontend lint:

```powershell
cd frontend
npm run lint
```

Result:

`eslint .` completed with exit code 0 and no lint output.

Frontend build:

```powershell
cd frontend
npm run build
```

Result:

- `dist/index.html`
- `dist/assets/index-B2No4I98.js`
- `dist/assets/index-PcGMtB_b.css`
- build completed successfully

Whitespace check:

```powershell
git diff --check
```

Result:

No output, exit code 0.

Static console asset check:

```powershell
Invoke-WebRequest http://127.0.0.1:8765/console
```

Result:

- `/console`: 200
- `/assets/index-B2No4I98.js`: 200
- `/assets/index-PcGMtB_b.css`: 200

## Current Feature Progress

Completed:

- Plugin runtime is the active source execution path.
- Five formal source plugins are present and live-checkable.
- `/console` is the only active backend UI route.
- `/api/console/*` is the active console API namespace.
- Search jobs have structured progress and candidate grouping.
- The console search page displays book candidates first, with source rows as details.
- Candidate verification can fetch TOC and chapter content from the backend runtime.
- The frontend is built from real React/Vite/shadcn-style components and passes lint/build.

Next recommended stage:

Stage 4 should focus on search quality and management depth: source reliability scoring, per-source retry/proxy policy visibility, richer candidate merge rules, persisted search job history, plugin auth/login workflows for正版书源, and a dedicated source health dashboard.
