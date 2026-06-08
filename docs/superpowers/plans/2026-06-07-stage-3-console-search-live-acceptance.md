# Stage 3 Console Search Workbench And Live Acceptance

> Date: 2026-06-07
> Executor: Kimi
> Reviewer: Codex
> Branch: continue on current branch unless user explicitly creates a new one
> Primary design source: `docs/architecture/console-search-management-design.md`

## Goal

Build the next complete console/search stage around real source operation: structured search progress, grouped candidate results, one-click candidate verification, persistent live acceptance records, and a Reading Web inspired source workbench UI.

## Hard Boundaries

- Do not restore active legacy engine code from `docs/archive`.
- Do not reintroduce root-level old runtime folders such as `app/`, `engine-jvm/`, root `tests/`, root `scripts/`, or old root config files.
- The local Reading Web archive is reference-only:

```text
docs/archive/legacy-reading-engine/2026-06-07/data/upstreams/luoyacheng-legado/modules/web
```

- Active code must stay in the current clean layout:
  - `backend/`
  - `frontend/`
  - `plugins/`
  - `docs/`
- Console route remains `/console`.
- Console API remains `/api/console/*`.
- Do not restore `/admin` or `/api/admin/*`.
- Do not use `demo_*` plugin IDs.
- Source plugin scripts must not control global concurrency, timeout, proxy, retry, cache, or scheduling. Those remain runtime responsibilities.
- Install missing dependencies yourself when required, and commit lockfile changes if package manager creates them.

## Reference Extraction Requirement

Before implementing UI, inspect and summarize the local Reading Web source editor implementation:

- `SourceEditor.vue`: three-column source workbench.
- `ToolBar.vue`: vertical command strip and hotkeys.
- `SourceTabForm.vue`: grouped source fields.
- `SourceTabTools.vue`: JSON/debug/list/help tabs.
- `SourceDebug.vue`: keyword + WebSocket debug output flow.
- `SourceList.vue` and `SourceItem.vue`: filter, select, import/export, error highlighting, virtual list.
- `api.ts` and `api.md`: `searchBook`, `bookSourceDebug`, `saveBookSource`, `getChapterList`, `getBookContent`.

The console implementation should borrow the information architecture, not copy Vue/Element Plus code.

## Completion Requirements

Stage 3 is complete only when all items below are true:

- Backend tests pass.
- Frontend build passes.
- `/console` renders the upgraded React UI with no blank asset issue.
- A real live source check is executed through the backend service, not by a one-off manual script only.
- The live check performs:
  - search
  - candidate selection
  - detail when available
  - toc
  - chapter content fetch
- The verification report includes a concrete record with:
  - plugin id
  - keyword
  - search result count
  - selected book name
  - selected author if available
  - toc count
  - chapter title
  - content length
  - passed status
  - normalized error if failed
- At least one enabled plugin must pass live content validation with chapter content length greater than `500`.
- Search returning multiple books is treated as normal. The UI must group/rank candidates instead of reporting this as failure.
- Search progress must be visible as per-source status, not only a raw log.
- Fixture smoke and live acceptance must remain separate concepts.
- Any real source failures must be shown with actionable diagnostics.
- Final verification must be recorded under `docs/verification/`.

## Task 0 Baseline And Drift Gate

### Objective

Confirm the repository is still in the intended plugin-runtime shape before making changes.

### Steps

1. Check current branch and status.
2. Confirm active layout contains `backend/`, `frontend/`, `plugins/`, `docs/`.
3. Confirm no active import/reference to archived old engines:
   - `app.engine`
   - `app.legado_engine`
   - `LegadoEngineRunner`
   - `SourceRepository`
   - `engine-jvm`
4. Confirm `/admin` and `/api/admin` are not active routes.
5. Run current backend tests and frontend build before making behavior changes, unless dependency setup blocks this.

### Acceptance

- Baseline result is documented in the final Stage 3 verification report.
- Any pre-existing failure is recorded before modification.

## Task 1 Live Acceptance Domain Model

### Objective

Create first-class backend models for live source acceptance and candidate verification.

### Required Concepts

- `LiveCheckRequest`
  - `pluginId`
  - `keyword`
  - optional `candidateIndex`
  - optional `candidateId`
  - optional `chapterIndex`
  - optional timeout overrides controlled by backend only
- `LiveCheckResult`
  - `status`: `passed`, `failed`, `partial`, `timeout`, `cancelled`
  - `pluginId`
  - `keyword`
  - search summary
  - selected candidate
  - detail result
  - toc result
  - chapter result
  - diagnostics
  - timings
- `CandidateGroup`
  - normalized title
  - normalized author
  - score
  - score reasons
  - source/plugin items
- `CandidateVerificationResult`
  - candidate id
  - plugin id
  - detail/toc/chapter status
  - content length
  - preview
  - diagnostics

### Acceptance

- Unit tests cover pass, empty search, toc failure, chapter failure, timeout/exception normalization.
- Live acceptance model does not merge with fixture smoke model.

## Task 2 Persistence For Live Checks

### Objective

Persist live acceptance runs so the console can show history and last known real-source health.

### Implementation Notes

Add storage under backend's existing persistence layer. Suggested table:

```sql
plugin_live_checks (
  id,
  plugin_id,
  keyword,
  status,
  search_count,
  selected_name,
  selected_author,
  toc_count,
  chapter_title,
  content_length,
  result_json,
  error_json,
  created_at
)
```

Add repository methods:

- create/record live check
- list by plugin
- latest by plugin
- aggregate live check stats

### Acceptance

- Tests cover insert, list, latest, failed result storage, JSON fields.
- Existing plugin health repository remains compatible.

## Task 3 Backend Live Check Service

### Objective

Implement the real operational path:

```text
plugin.search -> select candidate -> plugin.detail -> plugin.toc -> plugin.chapter
```

### Behavior

- The service must use the existing plugin runtime context.
- Candidate selection defaults to the best ranked candidate, not necessarily exact match.
- Detail can be partial if the source does not provide every field, but toc and chapter content are required for pass.
- Passing live validation requires:
  - search count > 0
  - toc count > 0
  - chapter content length > 500
- Normalize common failures:
  - timeout
  - network error
  - parse empty
  - detail empty
  - toc empty
  - chapter empty
  - plugin exception

### Acceptance

- Tests use fixtures/mocks for deterministic behavior.
- At least one integration or CLI/API test can hit a real plugin path when network is available.
- The service returns a structured result suitable for console display.

## Task 4 Search Job Candidate Grouping And Progress Events

### Objective

Upgrade existing search jobs from raw events to operator-friendly state.

### Required Events

Keep existing events where present, then add or normalize:

- `summary`
- `source_start`
- `source_done`
- `source_empty`
- `source_timeout`
- `source_error`
- `result`
- `candidate_grouped`
- `candidate_verified`
- `content_verified`
- `batch_done`
- `done`

### Candidate Grouping

Group by normalized `name + author`, with fallback to normalized name. Preserve all raw candidate items.

Score signals:

- exact or close title match
- author match
- result has latest chapter
- source health
- live content validation
- latency

### Acceptance

- API exposes grouped candidates for a job.
- Event polling can reconstruct source progress.
- Tests cover multiple books with similar names and multiple sources returning same book.

## Task 5 Console API

### Objective

Expose complete backend management operations under `/api/console/*`.

### Required Endpoints

Add or complete:

```text
GET  /api/console/search-jobs/{job_id}/candidates
POST /api/console/search-jobs/{job_id}/candidates/{candidate_id}/verify
POST /api/console/plugins/{plugin_id}/live-check
GET  /api/console/plugins/{plugin_id}/live-checks
GET  /api/console/plugins/{plugin_id}/live-checks/latest
```

Optional if useful:

```text
GET /api/console/live-checks
GET /api/console/live-checks/stats
```

### Acceptance

- Tests cover success and failure responses.
- Route names use `console`, not `admin`.
- API responses include enough fields for UI progress, diagnostics, and report export.

## Task 6 Console UI Workbench Redesign

### Objective

Upgrade `/console` into a Reading Web inspired source operations workbench using the existing React/Vite/shadcn/ui stack.

### Required Layout

Create a dense operational layout inspired by local Reading Web:

```text
stable navigation | active work area | diagnostics/detail side panel
```

Required pages or panels:

- Dashboard summary.
- Plugin/source inventory.
- Plugin detail with capability tabs:
  - Overview
  - Auth/Cookies
  - Fixture Smoke
  - Live Check
  - Manifest/Source
  - Diagnostics
- Search workbench:
  - search controls
  - live progress strip directly below the search input
  - grouped book result list as the primary content
  - per-source progress table as a secondary expandable panel
  - grouped candidate result list
  - raw event/log panel
  - candidate verification drawer/dialog
- Verification history.

### UI Requirements

- Use shadcn/ui components already in the project.
- Use tables/rows for dense operational data.
- Use badges for source status, auth mode, fixture smoke, live check, timeout/error.
- Use tabs for plugin capability groups.
- Use drawer/dialog for candidate verification detail.
- Keep raw diagnostics visible but secondary to structured progress.
- Search results must be displayed as books first, with corresponding source/plugin rows under each book.
- A dynamic progress bar must appear below the search box or below the result list.
- The progress bar must show completed source count, total source count, elapsed time, and the currently queried source.
- When multiple sources run concurrently, show current sources as compact chips.
- Do not make the raw log the main search UI.
- Avoid marketing hero sections and large decorative card grids.
- No visible `/admin` wording.

### Acceptance

- `/console` renders correctly after `frontend` build and backend static serving.
- Browser verification captures the search workbench and plugin detail.
- Text does not overlap at desktop and common mobile widths.

## Task 7 Real Source Repair Pass

### Objective

Improve live reliability of current formal plugins.

### Current Known Live Status

Prior live check for keyword `凡人修仙传`:

- `22biqu_com`: passed content validation.
- `biquge365_net`: search returned results, detail/toc failed.
- `xbiqugu_la`: timeout.
- `xbiquzw_net`: timeout.
- `shuhaige_net`: empty search.

### Steps

1. Run live checks through the new backend endpoint.
2. Fix plugin selectors or URLs where low-risk and obvious.
3. Keep fixes scoped to plugin code and fixtures.
4. Do not weaken acceptance just to pass.

### Acceptance

- At minimum, `22biqu_com` still passes.
- Preferably at least 2 to 3 plugins pass live content validation.
- Failures for remaining plugins are persisted and visible with normalized diagnostics.

## Task 8 Verification Report

### Objective

Produce final evidence that Stage 3 works.

### Required Commands

Run and report:

```powershell
cd backend; python -m pytest tests -q
cd frontend; npm run build
git diff --check
```

Also run live acceptance through the implemented backend/API path and include exact result.

### Required Report

Create:

```text
docs/verification/stage-3-console-search-live-acceptance.md
```

The report must include:

- branch name
- baseline summary
- changed files summary
- backend tests result
- frontend build result
- browser verification result
- live acceptance record
- remaining failing sources and diagnostics
- confirmation that archived legacy code was not restored
- confirmation that `/admin` was not restored

## Final Handoff Format

Kimi's final response should include:

- current branch
- completed task checklist
- verification command results
- live source acceptance table
- console URL
- verification report path
- remaining known issues
