# Console Search And Source Management Design

> Date: 2026-06-07
> Scope: LegadoHub `/console` backend management and Reading-compatible search operations.

## Current Functional Progress

### Completed

- Python source plugin runtime is active under `backend/app/source_plugins/`.
- 5 formal source plugins exist under `plugins/sources/`:
  - `xbiqugu_la`
  - `shuhaige_net`
  - `biquge365_net`
  - `xbiquzw_net`
  - `22biqu_com`
- Fixture-backed smoke exists for all 5 plugins:
  - `search`
  - `detail`
  - `toc`
  - `chapter`
- Reading-compatible API exists:
  - `/api/legado/source`
  - `/api/legado/search`
  - `/api/legado/book/{book_id}`
  - `/api/legado/book/{book_id}/toc`
  - `/api/legado/chapter/{chapter_id}`
- Console exists at `/console`.
- Console API exists under `/api/console/*`.
- Search job backend exists:
  - create search job
  - poll job status
  - poll incremental events
  - cancel job
  - per-source start/done/result events
  - batch summary events
- Plugin health storage exists:
  - enabled state
  - last smoke result
  - attempts
  - success/failure counters
- Auth/cookie framework exists for future official sources.
- `/admin` and `/api/admin/*` are not active routes.

### Verified

- Backend tests: `127 passed, 1 warning`.
- Frontend build succeeds.
- At least one real source, `22biqu_com`, can return chapter content for a live query.

### Not Yet Complete

- Live-source acceptance is not yet a formal gate.
- Real source checks are not persisted as first-class verification reports.
- Search UI currently shows events/logs, but not a polished operational progress board.
- Candidate books are not yet grouped and explained well enough.
- Detail/toc/chapter live validation is not exposed as a one-click console workflow.
- Failed real sources do not yet have enough remediation hints in the console.

## Reading Web And Source-Management Reference

### Primary Local Reference

Use the archived local upstream as the primary reference:

```text
docs/archive/legacy-reading-engine/2026-06-07/data/upstreams/luoyacheng-legado
```

The relevant Web module is:

```text
modules/web
```

Inspected source editor files:

- `modules/web/src/views/SourceEditor.vue`
- `modules/web/src/components/ToolBar.vue`
- `modules/web/src/components/SourceTabForm.vue`
- `modules/web/src/components/SourceTabTools.vue`
- `modules/web/src/components/SourceJson.vue`
- `modules/web/src/components/SourceDebug.vue`
- `modules/web/src/components/SourceList.vue`
- `modules/web/src/components/SourceItem.vue`
- `modules/web/src/components/SourceHelp.vue`
- `modules/web/src/store/sourceStore.ts`
- `modules/web/src/api/api.ts`
- `modules/web/src/config/bookSourceEditConfig.ts`
- `modules/web/src/assets/sourceeditor.css`
- `api.md`

Earlier references to external Web bookshelf projects are secondary only. They must not drive the console source-management design.

### Source Editor Layout

Reading Web's source editor is a full-height operational workbench:

```text
left editor form | middle command toolbar | right tool tabs
```

Observed structure:

- `SourceEditor.vue` owns a three-column `display: flex` layout with `height: 100vh` and hidden overflow.
- The left pane is `SourceTabForm`, driven by a field config object.
- The middle pane is `ToolBar`, a vertical command strip.
- The right pane is `SourceTabTools`, a tabbed utility area.
- The document title switches between `书源管理` and `订阅源管理`.

This is a better reference for LegadoHub than a generic dashboard. The console should be a source operations workbench where plugin metadata, live testing, source list, diagnostics, and help are visible without deep navigation.

### Source Form Model

`bookSourceEditConfig.ts` groups fields by capability:

- `基础`
- `搜索`
- `发现`
- `详情`
- `目录`
- `正文`

The base group includes operational extension points that map directly to LegadoHub plugin metadata:

- source type
- source URL/domain
- source name
- group/comment
- login URL
- login UI
- login check JS
- cover decode JS
- URL pattern
- request headers
- variable comments
- concurrent rate
- JS library

LegadoHub should preserve this capability grouping in the plugin detail page. Do not flatten plugin metadata, auth settings, rules, fixtures, and live checks into one table.

### Right Tool Tabs

`SourceTabTools.vue` defines four tabs:

- `编辑源`: raw JSON edit/import/export surface through `SourceJson`.
- `调试源`: source debug surface through `SourceDebug`.
- `源列表`: searchable, selectable source list through `SourceList`.
- `帮助信息`: source-making links and syntax notes through `SourceHelp`.

LegadoHub translation:

- `编辑源` -> plugin manifest/source view, contract summary, generated fixture status.
- `调试源` -> live source check and structured search/detail/toc/chapter trace.
- `源列表` -> plugin/source inventory with enable, auth, health, smoke, and live-check actions.
- `帮助信息` -> local plugin authoring guide and source template rules.

### Source List Behavior

`SourceList.vue` is not a passive table. It supports:

- keyword filtering with a search input.
- local JSON import from `.json` and `.txt`.
- export of filtered or selected sources.
- selected delete.
- clear all.
- virtual scrolling for large source collections.

`SourceItem.vue` shows each source as a selectable row with:

- display name.
- edit action.
- red error state when save/push failed.
- edit highlight for the current source.

LegadoHub should keep the same operational affordances:

- fast plugin filtering.
- bulk selection.
- bulk enable/disable.
- bulk smoke.
- bulk live check.
- export/import plugin manifests or source packages.
- visible failed-save or failed-validation state.

### Toolbar Behavior

`ToolBar.vue` exposes direct source operations:

- push source.
- pull source.
- generate source JSON.
- edit source from JSON.
- clear form.
- undo.
- redo.
- debug source.
- save source.
- configurable hotkeys.

LegadoHub does not need to copy the exact buttons, but it should keep the idea of a stable command strip for high-frequency source work:

- Save plugin.
- Reload plugins.
- Run fixture smoke.
- Run live check.
- Start search.
- Verify selected candidate.
- Clear cookies.
- Export report.

### Debug And Search Flow

`SourceDebug.vue` shows the core flow:

1. Accept a keyword, defaulting to the current source's `ruleSearch.checkKeyWord`.
2. Save the current source first.
3. Open a WebSocket debug session.
4. Append streamed debug lines into a read-only textarea.
5. Mark debug finished on socket close.

`api.ts` defines the WebSocket contracts:

- `searchBook`: sends `{ key }`, receives batches of searched books.
- `bookSourceDebug`: sends `{ tag, key }`, receives debug text events.
- `rssSourceDebug`: sends `{ tag, key }`, receives debug text events.

`api.md` confirms the same Web API:

- `saveBookSource`
- `saveBookSources`
- `getBookSource?url=xxx`
- `getBookSources`
- `deleteBookSources`
- `bookSourceDebug`
- `searchBook`
- `saveBook`
- `getChapterList`
- `getBookContent`

LegadoHub should improve this by using structured events instead of only text logs. The UI still needs a raw log pane, but the backend must emit durable structured progress events for source start, result, empty, timeout, error, candidate grouping, candidate verification, and final summary.

### Design Translation For LegadoHub

LegadoHub should not copy Reading Web's Element Plus UI literally because the current console uses React, Vite, Tailwind, and shadcn/ui. It should copy the information architecture:

- Use a workbench layout, not a marketing dashboard.
- Keep plugin/source inventory and debug output one click away from editing.
- Prefer dense rows and tabs over large card piles.
- Keep source/plugin actions stable and close to the active source.
- Show raw JSON/source data as a first-class tab for advanced operators.
- Keep live debug output visible while also showing structured progress and result status.
- Treat multiple search results as normal, then group, score, and verify candidates.

### Source Search Lessons

The local Reading Web module confirms two separate source workflows:

- `searchBook`: multi-source online book search.
- `bookSourceDebug`: single-source debug by `tag` and `key`.

LegadoHub should model both:

- Search jobs: query many enabled plugins and produce grouped candidate books.
- Live source checks: query one plugin and prove search -> detail -> toc -> chapter content works.

Relevant concepts to adopt:

- Multiple candidate books are normal.
- Exact title match is a score signal, not the only valid outcome.
- Author match should be optional but visible.
- Candidate verification should load detail, toc, and sample chapter content.
- Each plugin needs visible fixture smoke, live check, auth, cookie, timeout, and last-error state.
- Search results should be sorted by candidate score, plugin health, content validation result, and latency/failure history.

## Product Principle

Search returning multiple books is normal.

The console must not treat multiple results as a failure. It should help the operator answer:

- Which sources were queried?
- Which sources are still running?
- Which sources failed, timed out, or returned empty?
- Which candidate books are likely the intended book?
- Which candidate has a valid detail page, toc, and readable chapter content?
- Which plugin needs repair?

## Search Management Model

### Search Job Lifecycle

```text
created -> running -> completed
                 \-> cancelled
                 \-> partial_completed
```

`partial_completed` should be explicit when at least one source returns results but some sources fail or time out.

### Event Types

Keep current events and make them user-facing:

- `summary`: source count, batch count, timeout config.
- `source_start`: a source entered execution.
- `source_done`: a source finished with success/error/timeout/empty.
- `result`: one candidate book returned.
- `batch_done`: one source batch completed.
- `overall_timeout`: global timeout reached.
- `done`: job completed.

Recommended additions:

- `source_empty`: source responded but no books matched.
- `candidate_grouped`: backend grouped duplicate/similar candidates.
- `candidate_verified`: detail/toc/chapter check result for a candidate.
- `content_verified`: chapter content returned and length checked.

## Console Search Page Design

The search page should be an operational workspace, not a plain log viewer.

Primary interaction:

```text
keyword input -> live progress strip -> book result list with source rows
```

The user should see searched books first. Source progress and diagnostics support the search result list; they should not replace it.

### Top Bar

Controls:

- Keyword input.
- Page number.
- Source limit.
- Toggle: enabled sources only.
- Toggle: include unstable sources.
- Button: start search.
- Button: cancel running job.

Directly below the search controls, show a live progress strip:

```text
[progress bar 12/35 sources] currently querying: 22biqu_com · 笔趣阁22 · 1.2s
```

Progress strip fields:

- Total sources.
- Completed sources.
- Current source name.
- Current plugin ID.
- Current batch index when batching is used.
- Successful sources.
- Empty sources.
- Failed sources.
- Timeout sources.
- Elapsed time.

Behavior:

- The progress bar advances by completed source count, not by result count.
- The current source label updates as each source starts.
- Multiple concurrent sources can be shown as compact chips.
- The strip remains visible while the result list grows.
- On completion, the strip becomes a final summary.

### Source Progress Panel

Display source progress as a secondary expandable panel or side panel, not the primary result surface. Rows use stable statuses:

```text
source name | plugin id | status | result count | latency | error code | action
```

Status values:

- pending
- running
- success
- empty
- timeout
- failed
- disabled

Row actions:

- Open plugin detail.
- Run fixture smoke.
- Run live single-source check.
- Disable source.
- Clear cookies.

### Candidate Results Panel

The main list displays searched books and their corresponding sources.

Default row shape:

```text
book title | author | latest chapter | matched sources | best status | action
```

Each book row expands to show source items:

```text
source name | plugin id | raw title | raw author | latency | verification | action
```

Results should be grouped by normalized `name + author`, not treated as one flat list.

Candidate group fields:

- Display title.
- Author.
- Match score.
- Source count.
- Best source.
- Latest chapter.
- Categories/kind.
- Whether detail/toc/chapter validation passed.

Candidate item fields:

- Source name.
- Plugin ID.
- Raw title.
- Raw author.
- Book URL.
- Score reason.
- Last chapter.
- Latency.

Expected behavior:

- Multiple books are shown as candidates.
- Similar titles are not hidden.
- Exact matches rank higher.
- Result explanation is visible.
- Each book shows which sources returned it.
- Each source item remains individually verifiable.
- User can click a candidate and verify detail/toc/chapter.

### Candidate Verification Drawer

When selecting a candidate:

1. Fetch detail.
2. Fetch toc.
3. Fetch first readable chapter.
4. Show title, author, chapter count, first chapter title, content length, preview.

Success criteria:

```text
detail.name is not empty
detail.author is not empty when site provides it
toc has at least 1 chapter
chapter.content length > 500 for live validation
```

This is the acceptance step that proves the source can actually return readable content.

## Backend API Design

### Existing Endpoints To Keep

- `POST /api/console/search-jobs`
- `GET /api/console/search-jobs/{job_id}`
- `GET /api/console/search-jobs/{job_id}/events`
- `POST /api/console/search-jobs/{job_id}/cancel`
- `GET /api/console/search/stream`

### Recommended New Endpoints

```text
POST /api/console/search-jobs/{job_id}/candidates/{candidate_id}/verify
GET  /api/console/search-jobs/{job_id}/candidates
POST /api/console/plugins/{plugin_id}/live-check
GET  /api/console/plugins/{plugin_id}/live-checks
```

### Candidate Verify Response

```json
{
  "candidateId": "sha256...",
  "sourceId": "22biqu_com",
  "status": "passed",
  "detail": {
    "name": "凡人修仙传之五行灵根开始",
    "author": "佚名",
    "tocUrl": "..."
  },
  "toc": {
    "chapterCount": 200,
    "firstTitle": "第1章 碎星岛"
  },
  "chapter": {
    "title": "第1章 碎星岛",
    "contentLength": 2369,
    "preview": "..."
  },
  "diagnostics": []
}
```

### Live Source Acceptance Response

```json
{
  "pluginId": "22biqu_com",
  "keyword": "凡人修仙传",
  "passed": true,
  "search": {
    "count": 15,
    "firstName": "凡人修仙传之五行灵根开始",
    "exactMatchCount": 0
  },
  "detail": {
    "name": "",
    "author": "",
    "passed": false
  },
  "toc": {
    "count": 200,
    "passed": true
  },
  "chapter": {
    "title": "第1章 碎星岛",
    "contentLength": 2369,
    "passed": true
  },
  "errors": []
}
```

Important: live acceptance can pass with non-exact search results if the selected candidate returns valid readable content. Exact match should be a scoring signal, not a hard requirement unless the user explicitly requests an exact book.

## Backend Persistence

Add a live verification table:

```sql
CREATE TABLE IF NOT EXISTS plugin_live_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin_id TEXT NOT NULL,
    keyword TEXT NOT NULL,
    status TEXT NOT NULL,
    search_count INTEGER DEFAULT 0,
    selected_name TEXT,
    selected_author TEXT,
    toc_count INTEGER DEFAULT 0,
    chapter_title TEXT,
    content_length INTEGER DEFAULT 0,
    result_json TEXT,
    error_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

This separates fixture smoke from live availability:

- Fixture smoke answers: parser contract still works on saved samples.
- Live check answers: source is reachable and returns readable content now.

## Visual Direction

The console should be quiet, dense, and operational.

Use:

- Tables for source progress and candidate results.
- Badges for status and error codes.
- Compact cards for summary metrics.
- Drawer/dialog for candidate verification.
- Monospace only for raw diagnostics.

Avoid:

- Marketing-style hero blocks.
- Large decorative cards.
- Fake metrics.
- Treating logs as the primary interface.

## Acceptance Standard Going Forward

Every stage completion report involving source functionality must include at least one live-source acceptance record:

```text
plugin id:
keyword:
search result count:
selected book name:
selected author:
toc count:
chapter title:
content length:
passed:
error:
```

Minimum pass:

- Search returns at least one candidate.
- A selected candidate can fetch toc.
- A selected chapter returns content length greater than 500.
- Failures are recorded with normalized diagnostics.

Recommended pass:

- At least 3 enabled plugins pass live acceptance for common keywords.
- At least 1 plugin passes exact-title validation for a known book.

## Next Implementation Stage

Stage 3 should focus on:

1. Add live acceptance backend service and persistence.
2. Add candidate grouping and scoring explanation.
3. Upgrade search page from event log to progress board.
4. Add candidate verification drawer.
5. Repair live plugins until at least 3 real sources pass content validation.
6. Make live acceptance part of final verification reports.
