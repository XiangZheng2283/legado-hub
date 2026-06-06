# Phase 3 Implementation Plan

> **For Kimi:** Implement this plan task-by-task. Do not skip validation. Do not commit or push unless the user explicitly asks.

**Goal:** Upgrade LegadoHub from a Phase 2 MVP into a scalable source operations backend: a much more complete Legado rule parser, synchronized aggregate source configuration/progress, full Web backend console, default proxy support, multi-source aggregation, and update tracking.

**Architecture:** Keep FastAPI + SQLite as the local runtime, but split the parser into a capability-based engine with explicit unsupported-syntax reporting. Treat source execution as a job-driven system: source health, parser progress, proxy state, cache state, and update tasks must be persisted and visible in the Web backend. The Web backend is a product UI, not a marketing page.

**Tech Stack:** Python 3.12+, FastAPI, Uvicorn, SQLite, httpx, lxml/cssselect, BeautifulSoup4, jsonpath-ng, quickjs or js2py for sandboxed light JavaScript if feasible, pytest.

---

## Design Skill Requirements

Use these design skills for the Web backend:

- `impeccable`: primary UI design skill because this is a product/admin/dashboard surface.
- `taste-skill`: secondary anti-template design review only. Do not apply its landing-page assumptions to dashboard surfaces.

Design read:

```text
Reading this as: Simplified Chinese product admin/workbench UI for local source governance and parser debugging, with a quiet technical-operations language, leaning toward dense but readable dashboard patterns with visible structure, dividers, and disciplined whitespace.
```

Design rules:

- No landing page as the first screen. The first screen is the actual operations dashboard.
- No hero section, no marketing copy, no decorative card wall.
- All user-facing backend UI text must be Simplified Chinese by default. Keep code identifiers and API field names in English.
- Do not use emoji in visible UI text, status labels, buttons, navigation, table cells, empty states, or logs.
- Use dense but readable product UI: sidebar/top navigation, tables, filters, detail drawers/pages, status chips, logs, and batch actions.
- Do not make the backend too sparse or overly minimal. Keep operational context visible.
- Use dividers, table rules, section separators, grouped panels, and whitespace to create hierarchy and design quality.
- Prefer 1px borders, subtle neutral surfaces, consistent gutters, and clear alignment over decorative shadows or gradients.
- Show real states only. No fake success numbers or demo source rows.
- No color-only status. Every status chip needs a text label.
- Default to a restrained neutral palette with one accent. Avoid AI-purple gradients, glassmorphism, beige/cream themes, and ornamental motion.
- Motion is limited to state transitions, loading, row expansion, dialogs, and toasts. Respect reduced motion.
- Every primary workflow needs loading, empty, error, and partial-success states.
- Tables must support pagination, filtering, sorting, and horizontal overflow on narrow screens.
- Visible focus states and WCAG AA contrast are required.

`PRODUCT.md` is the design source of truth for users, purpose, anti-references, and principles.

## Phase 3 Scope

Phase 3 must deliver:

1. A more complete Legado rule parser.
2. Aggregate source configuration synchronization and progress tracking.
3. Full Web backend console.
4. Default proxy configuration:

```text
http://192.168.31.233:7890
```

5. Multi-source aggregation beyond the single working Phase 2 source.
6. Health checks, source status, proxy status, parser capability reporting, and update tasks.
7. Original Phase 3 goals: concurrent search, de-duplication, merging, ranking, book records, update tracking, scheduled chapter checks, and cache refresh.

Phase 3 must not deliver:

- Docker packaging.
- Full AI rewriting/correction.
- So Novel full adapter unless it is explicitly needed as a fallback task after Legado parser expansion.
- Public internet full-source crawling beyond the existing raw archive.

## Parser Engine Requirements

Refactor `app/engine/extractor.py` and `app/engine/legado_executor.py` into capability-focused modules:

- `app/engine/rule_parser.py`
- `app/engine/request_builder.py`
- `app/engine/selectors.py`
- `app/engine/jsonpath_extractor.py`
- `app/engine/regex_extractor.py`
- `app/engine/js_runtime.py`
- `app/engine/rule_pipeline.py`
- `app/engine/capabilities.py`

Required parser capabilities:

- CSS selector chains.
- XPath.
- JsonPath.
- Regex extraction.
- Text, HTML, href, src, content, attribute extraction.
- `{{key}}`, `{{page}}`, `{{baseUrl}}`, and URL parameter replacement.
- GET and POST.
- Request headers.
- Charset decoding: UTF-8, GBK, GB2312, Big5 when declared.
- Relative URL normalization.
- `replaceRegex`.
- Multi-branch fallback with `||`.
- Exclusion suffixes like `!0`, `!1`, and negative indexing where used by selected sources.
- Pagination for search, TOC, and content when explicit next-page rules exist.
- Basic `@js:` and `<js>...</js>` support for light transforms only.
- Structured unsupported-syntax reporting when a rule cannot be safely executed.

JavaScript rules:

- Prefer a restricted sandbox using `quickjs` if available and stable on Windows; otherwise use `js2py` only for simple expressions.
- Do not expose filesystem, shell, network, or environment variables to JS rules.
- JS execution must have timeouts and size limits.
- If a JS rule is too complex, return `unsupported rule syntax` with rule path and source ID.

## Source Repository and Active Pool

Phase 3 must use the local Legado by-site archive as the canonical source repository:

- Canonical repository path: `data/sources/raw/by-site/legado/`.
- Current repository size: 2307 `*.json` files.
- Do not create a separate hand-picked raw source directory for Phase 3.
- Keep `config/phase2_sources.json` only as Phase 2 history and as a temporary overlay for known enabled/disabled state, priority, proxy mode, and notes.
- Create `config/source_pool.json` as the active state/config overlay for repository sources.
- Runtime search must not fire all 2307 sources by default. It must search only enabled sources selected by preflight, health check, user choice, or existing overlay state.
- The Web backend must index and display the repository-level inventory, including disabled/unverified sources, with filtering, pagination, batch preflight, enable/disable actions, reason, and last check result.
- Enabled sources are promoted from repository inventory only after preflight or successful health check.
- Disabled sources stay visible in Web backend with reason and last check result.

Important parsing rule:

- A single file under `data/sources/raw/by-site/legado/` may contain one Legado source object or a list of multiple Legado source objects.
- The loader must not silently keep only the first object in a list.
- Each valid source object must become an independent internal source record.
- Internal source IDs must be stable and collision-safe, for example:
  - single-object file: `<site-slug>`
  - multi-object file: `<site-slug>#<index>` or `<site-slug>#<bookSourceName-slug>`
- Keep both `source_file_path` and `source_index` or `source_key` in source metadata so the Web backend can show which raw file and which object produced the source.
- If one object in a multi-source file fails to load or fails preflight, only that object/source record is disabled. Other source objects from the same file must remain testable and independently enableable.
- If a file-level JSON parse error occurs, mark the file as unavailable and show the file-level error in the Web backend.

Selection criteria:

- Required fields present.
- No login-required sources by default.
- No adult-only sources enabled by default.
- Prefer sources with reachable search endpoint, standard HTML, and complete search/detail/toc/content rules.

## Batch Execution, Failure Recording, and Single-Source Tests

Runtime source usage must be batched and stateful:

- Repository inventory can contain all sources from `data/sources/raw/by-site/legado/`.
- Active search must run in batches, not as one request fan-out over the full repository.
- Add configurable execution limits:
  - `source_batch_size`
  - `max_concurrency`
  - `source_timeout_seconds`
  - `overall_search_timeout_seconds`
  - `max_sources_per_search`
- The default search path should use only enabled sources. Unverified sources must be tested by preflight or explicit user action before joining the active pool.
- Batch order should be deterministic: enabled first, higher priority first, healthy/proxy-success sources before unknown or recently failed sources.
- Search response debug output must include batch count, attempted source count, success count, failure count, disabled count, timeout count, and partial-success status.

Failure handling:

- Every source call failure must be recorded with source ID, raw file path, source index/key, phase, URL, direct/proxy mode, status/error, latency, and timestamp.
- Failures that indicate an unusable source should automatically disable that specific source record and write the failure reason behind that source in the Web backend.
- A source should be disabled for hard failures such as load error, missing required rule, unsupported required syntax, repeated timeout, 403/429/451 after proxy fallback, invalid selector output, or parse failure that blocks search/detail/toc/content.
- A source should not be disabled only because one keyword returns no search results.
- Direct failure followed by proxy success should not disable the source. It should mark the source as proxy-needed or proxy-succeeded.
- Disabled sources remain visible and can be manually re-tested, re-enabled, or forced to proxy mode.

Backend single-source test:

- Add an API for testing one source without enabling the whole pool:
  - `POST /api/admin/sources/{source_id}/test`
- Test input should support keyword, page, stage scope, and proxy mode override.
- Minimum stage scope:
  - `search`
  - `detail`
  - `toc`
  - `content` when a book/chapter context is available
- Test output must show pass/fail, failure reason, direct/proxy attempt history, sample parsed results, parser capability gaps, and whether the source was disabled or re-enabled.
- The Web backend source detail page must expose a visible "测试书源" action and show the last test result.

## Default Proxy

Update active proxy config to:

```json
{
  "enabled": true,
  "url": "http://192.168.31.233:7890",
  "retry_on_failure": true,
  "failure_status_codes": [403, 429, 451, 502, 503, 504],
  "failure_error_keywords": ["timeout", "connection", "reset", "forbidden", "captcha", "blocked"]
}
```

Requirements:

- Users can edit global proxy URL in Web backend.
- Users can set per-source `proxy_mode`: `auto`, `always`, `never`.
- Direct failure followed by proxy success must persist `proxy_status = "proxy_succeeded"`.
- Sources that become usable through proxy must be marked visible as proxy-enabled, not silently treated as direct.
- Web UI must show direct and proxy attempt history.

## Aggregate Source Configuration Sync

Create a managed aggregate source config layer:

- `config/aggregate_source.json`
- `app/core/aggregate_config.py`
- `app/core/source_generator.py` should read aggregate config instead of hard-coded metadata.

`config/aggregate_source.json` fields:

```json
{
  "name": "LegadoHub 聚合",
  "version": "0.3.0",
  "group": "聚合,LegadoHub",
  "enabled": true,
  "base_url_mode": "request_host",
  "generated_path": "generated/legadohub-source.json",
  "last_generated_at": "",
  "parser_progress": {
    "configured_sources": 0,
    "enabled_sources": 0,
    "healthy_sources": 0,
    "proxy_sources": 0,
    "unsupported_sources": 0
  }
}
```

Requirements:

- `/api/legado/source` still dynamically uses request Host for LAN import.
- Web backend can regenerate `generated/legadohub-source.json`.
- Web backend shows aggregate source version, generated path, last generated time, and parser/source progress.
- Updating source pool, proxy config, or aggregate metadata must update progress metadata.
- Add API:
  - `GET /api/admin/aggregate-source`
  - `POST /api/admin/aggregate-source/regenerate`
  - `GET /api/admin/progress`

## SQLite Extensions

Extend `app/storage/db.py` idempotently:

- `source_health`
  - `source_id TEXT PRIMARY KEY`
  - `enabled INTEGER`
  - `health_status TEXT`
  - `last_check_at TEXT`
  - `last_success_at TEXT`
  - `success_count INTEGER`
  - `failure_count INTEGER`
  - `avg_latency_ms INTEGER`
  - `last_error TEXT`
  - `parser_capabilities_json TEXT`
- `source_attempts`
  - `id INTEGER PRIMARY KEY AUTOINCREMENT`
  - `source_id TEXT`
  - `stage TEXT`
  - `url TEXT`
  - `direct_status TEXT`
  - `proxy_status TEXT`
  - `proxy_used INTEGER`
  - `latency_ms INTEGER`
  - `error TEXT`
  - `created_at TEXT`
- `book_records`
  - `book_id TEXT PRIMARY KEY`
  - `name TEXT`
  - `author TEXT`
  - `merged_sources_json TEXT`
  - `selected_source_id TEXT`
  - `last_chapter TEXT`
  - `last_seen_at TEXT`
  - `created_at TEXT`
- `update_tasks`
  - extend existing table if needed with `book_id`, `enabled`, `interval_minutes`, `last_run_at`, `next_run_at`, `last_result_json`
- `aggregate_progress`
  - `key TEXT PRIMARY KEY`
  - `value_json TEXT`
  - `updated_at TEXT`
- `admin_settings`
  - `key TEXT PRIMARY KEY`
  - `value_json TEXT`
  - `updated_at TEXT`

## Aggregation And Ranking

Search must support multiple enabled sources:

- bounded concurrency
- per-source timeout
- overall timeout
- proxy fallback
- cache hits
- partial success
- structured per-source errors

Merge results:

- Normalize book name and author.
- Merge same-name same-author candidates.
- Preserve source candidates under `sources`.
- Keep selected best candidate.
- Rank by:
  1. exact keyword match
  2. title similarity
  3. author match
  4. source health score
  5. metadata completeness
  6. latency
  7. proxy penalty if configured

Response must include both merged and source-level data so Reading can open a stable book URL while Web backend can inspect all candidates.

## Update Tracking

Implement original Phase 3追更 goals:

- When a user opens a book detail or TOC, create or update `book_records`.
- Allow Web backend to enable/disable update tracking per book.
- Add scheduled check loop that can run while app is active.
- Check TOC for tracked books at configured interval.
- Detect new chapters by comparing cached TOC with latest TOC.
- Cache new chapter metadata; optionally prefetch content if enabled.
- Show last check result and next check time in Web backend.

Add API:

- `GET /api/admin/books`
- `GET /api/admin/books/{book_id}`
- `POST /api/admin/books/{book_id}/tracking`
- `GET /api/admin/update-tasks`
- `POST /api/admin/update-tasks/{book_id}/run`

## Full Web Backend Console

Replace the Phase 2 debug-only experience with a full backend console while keeping `/debug` as a compatibility alias.

Routes:

- `/admin`
- `/admin/sources`
- `/admin/sources/{source_id}`
- `/admin/search`
- `/admin/books`
- `/admin/books/{book_id}`
- `/admin/update-tasks`
- `/admin/cache`
- `/admin/settings`
- `/admin/aggregate-source`
- `/debug` redirects or links to `/admin/search`

Recommended implementation:

- Continue server-rendered FastAPI HTML for Phase 3 unless Kimi judges a frontend build chain is necessary.
- If adding a frontend build chain, document why and keep it minimal.
- Use shared templates/components:
  - `app/web/layout.py`
  - `app/web/components.py`
  - `app/web/admin.py`

Core screens:

1. Dashboard
   - source totals
   - healthy/degraded/disabled/proxy counts
   - parser progress
   - recent failures
   - update task summary
2. Sources
   - table with filters: enabled, health, proxy status, parser capability, failure reason
   - batch actions: health check selected, enable, disable, set proxy mode
3. Source detail
   - raw source summary
   - parser capabilities
   - recent attempts
   - search/detail/toc/content test buttons
   - direct/proxy attempt timeline
4. Search workbench
   - query input
   - merged results
   - source candidates
   - ranking explanation
   - error panel
5. Book detail
   - merged metadata
   - source candidates
   - TOC
   - tracking toggle
6. Update tasks
   - tracked books
   - next run
   - last result
   - run now
7. Cache
   - search/book/toc/chapter cache counts
   - clear selected cache type
   - inspect cache entry
8. Settings
   - default proxy URL
   - concurrency and timeout settings
   - aggregate source metadata

UI acceptance:

- Every table has empty state, loading state, error state, and partial-success state.
- No fake data.
- Keyboard focus visible.
- Mobile/narrow screen does not overlap or truncate controls.
- Status colors paired with text labels.
- The console must show actual configured proxy URL `http://192.168.31.233:7890`.
- All visible labels, navigation items, table headers, empty states, errors, button text, and settings copy are Simplified Chinese.
- No emoji appears anywhere in the Web backend UI.
- Pages use clear section dividers, row separators, and enough whitespace to feel designed without hiding operational density.
- The UI is not an extreme minimalist portfolio style; it is an operations console with calm structure.

## Tests

Add or extend tests:

- Parser:
  - CSS selector chain
  - XPath
  - JsonPath
  - regex
  - fallback `||`
  - exclusion `!0`
  - `replaceRegex`
  - simple JS transform allowed
  - complex JS unsupported with structured error
- Proxy:
  - default proxy config is enabled and URL is `http://192.168.31.233:7890`
  - auto fallback real decision path
  - source status persists proxy success
- Aggregation:
  - same name + author merge
  - ranking explanation
  - partial source failure does not fail whole search
- Aggregate source:
  - config-driven name/version/group
  - request Host dynamic base URL
  - progress metadata updates
- Update tracking:
  - book record created on open
  - update task can be enabled
  - TOC diff detects new chapter
- Web admin:
  - core routes return 200
  - sources page includes proxy URL/status
  - aggregate source page includes generation progress
  - settings page can save proxy mode/settings

## Validation Commands

Kimi must run:

```powershell
python -m pip install -r requirements.txt
python -m pytest tests -v
python -c "from app.storage.db import initialize_database; print(initialize_database())"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8765
```

API smoke:

```powershell
@'
import json
from urllib.parse import quote
from urllib.request import urlopen

base = "http://127.0.0.1:8765"

def get(path):
    with urlopen(base + path, timeout=60) as response:
        body = response.read().decode("utf-8")
        print(path, response.status, body[:240].replace("\n", "\\n"))
        assert response.status == 200
        return json.loads(body)

progress = get("/api/admin/progress")
assert "parser" in progress or "aggregate" in progress

search = get("/api/legado/search?keyword=" + quote("凡人修仙传") + "&page=1")
assert search.get("implemented") is True
assert search.get("items")

book_id = search["items"][0]["bookId"]
book = get("/api/legado/book/" + quote(book_id, safe=""))
toc = get("/api/legado/book/" + quote(book_id, safe="") + "/toc")
assert toc.get("chapters")
chapter_id = toc["chapters"][0]["chapterId"]
chapter = get("/api/legado/chapter/" + quote(chapter_id, safe=""))
assert chapter.get("content")

admin_sources = get("/api/admin/sources")
assert admin_sources.get("items")
'@ | python -
```

Web manual smoke:

- `http://127.0.0.1:8765/admin`
- `http://127.0.0.1:8765/admin/sources`
- `http://127.0.0.1:8765/admin/search`
- `http://127.0.0.1:8765/admin/books`
- `http://127.0.0.1:8765/admin/update-tasks`
- `http://127.0.0.1:8765/admin/cache`
- `http://127.0.0.1:8765/admin/settings`
- `http://127.0.0.1:8765/admin/aggregate-source`

Reading/Legado smoke:

- Start via `start.bat`.
- Import LAN URL printed by script.
- Search a known title.
- Open book detail.
- Open TOC.
- Open first chapter.
- Confirm chapter text renders.

## Final Phase 3 Acceptance Report

Kimi must report:

1. Full file change list.
2. Dependency changes.
3. Parser capability matrix: supported, partially supported, unsupported.
4. Active source pool count, enabled count, healthy count, proxy-success count.
5. Default proxy config and at least one real or simulated proxy fallback validation.
6. Aggregate source config and progress sync output.
7. Search aggregation smoke output with merged candidates.
8. Update tracking smoke output.
9. Web admin manual verification with page list and screenshots if possible.
10. Chinese UI verification: navigation, forms, buttons, tables, empty/error states, and settings pages are in Simplified Chinese.
11. No-emoji UI verification.
12. Reading/Legado import and chapter-content verification result.
13. Exact commands run.
14. Test results.
15. Known limitations and Phase 4 recommendations.

Codex will review against this plan and decide whether Phase 3 is accepted.
