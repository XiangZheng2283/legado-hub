# Plugin Source Runtime Implementation Plan

> **Superseded for execution:** Use `docs/superpowers/plans/2026-06-07-stage-1-plugin-engine-shadcn-admin.md` for Stage 1 implementation. This earlier plan remains as a smaller reference for backend plugin-runtime decomposition.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not commit unless the user explicitly authorizes commits in the current session.

**Goal:** Build a LegadoHub-native Python source plugin runtime while preserving the existing Reading/Legado aggregate source API.

**Architecture:** Add a focused `app/source_plugins/` package for metadata, normalized models, plugin loading, runtime context, smoke validation, and scheduler execution. Rewire existing catalog/search job orchestration to call plugin execution while keeping cache, proxy, timeout, trace, and aggregate source output under LegadoHub core control.

**Tech Stack:** Python 3, FastAPI, SQLite, asyncio, pytest, PyYAML, BeautifulSoup/lxml selectors through existing project dependencies or a small parser helper if already available.

---

## File Structure

Create:

- `app/source_plugins/__init__.py`: package marker and public imports.
- `app/source_plugins/models.py`: plugin metadata, normalized result models, validation errors.
- `app/source_plugins/loader.py`: discover plugin directories, read `metadata.yaml`, import `source.py`, validate methods.
- `app/source_plugins/context.py`: per-call runtime context with controlled fetch, selector helpers, URL utilities, trace hooks.
- `app/source_plugins/scheduler.py`: source-level execution orchestration for search/detail/toc/chapter.
- `app/source_plugins/smoke.py`: smoke validation runner for plugin fixtures.
- `data/source_plugins/demo_html/metadata.yaml`: first local demo plugin metadata.
- `data/source_plugins/demo_html/source.py`: first local demo plugin implementation.
- `data/source_plugins/demo_html/tests/smoke.yaml`: first local smoke fixture.
- `data/source_seeds/so-novel/README.md`: pinned So Novel seed snapshot notes.
- `scripts/inspect_so_novel_rules.py`: inspect So Novel rule files and classify simple conversion candidates.
- `tests/source_plugins/test_models.py`
- `tests/source_plugins/test_loader.py`
- `tests/source_plugins/test_context.py`
- `tests/source_plugins/test_scheduler.py`
- `tests/source_plugins/test_smoke.py`
- `tests/scripts/test_inspect_so_novel_rules.py`

Modify:

- `requirements.txt`: add `PyYAML` only if unavailable.
- `app/services/catalog.py`: call plugin scheduler instead of Reading rule runner for the new path.
- `app/services/search_jobs.py`: route job execution through plugin scheduler and keep SSE event shape.
- `app/api/admin.py`: expose plugin list, reload, and smoke-test endpoints.
- `app/web/admin.py`: add plugin operations pages or sections.
- `config/source_pool.json`: keep existing concurrency/timeout/proxy config as the scheduler input.
- `docs/skills/book-source-craft/*`: keep aligned with plugin source workflow.

Do not expand:

- `engine-jvm/`
- `app/legado_engine/`
- Old Python Reading rule parser modules

Initial source rule seed:

- Use `freeok/so-novel` as the first external source mine.
- Start with `bundle/rules/main.json`.
- Treat `proxy-required.json`, `rate-limit.json`, and `cloudflare.json` as classification inputs.
- Convert rules into Python plugins; do not run So Novel rules directly as the LegadoHub runtime.

## Task 1: Plugin Models

**Files:**

- Create: `app/source_plugins/__init__.py`
- Create: `app/source_plugins/models.py`
- Test: `tests/source_plugins/test_models.py`

- [ ] **Step 1: Write model tests**

Create `tests/source_plugins/test_models.py` with tests for valid metadata, missing required metadata, and normalized search result serialization.

Expected assertions:

- A valid metadata dictionary returns `PluginMetadata(id="demo_html", capabilities=["search", "detail", "toc", "chapter"])`.
- Missing `id` raises `PluginValidationError`.
- A `SearchResult` can produce a dictionary with `name`, `author`, `bookUrl`, and `sourceId`.

- [ ] **Step 2: Run model tests and verify failure**

Run:

```powershell
pytest tests/source_plugins/test_models.py -q
```

Expected: FAIL because `app.source_plugins.models` does not exist yet.

- [ ] **Step 3: Implement plugin models**

Create dataclass or Pydantic-free models in `app/source_plugins/models.py`:

- `PluginValidationError`
- `PluginMetadata`
- `SearchResult`
- `BookDetail`
- `ChapterItem`
- `ChapterContent`

Use simple dictionaries at boundaries with explicit `to_dict()` methods. Keep fields optional where real sites often omit data, but require IDs, names, URLs, capabilities, and lifecycle outputs.

- [ ] **Step 4: Run model tests**

Run:

```powershell
pytest tests/source_plugins/test_models.py -q
```

Expected: PASS.

## Task 2: Plugin Loader

**Files:**

- Create: `app/source_plugins/loader.py`
- Create: `data/source_plugins/demo_html/metadata.yaml`
- Create: `data/source_plugins/demo_html/source.py`
- Test: `tests/source_plugins/test_loader.py`

- [ ] **Step 1: Write loader tests**

Create tests that:

- Load plugin metadata from `data/source_plugins/demo_html/metadata.yaml`.
- Import `source.py`.
- Instantiate `Source`.
- Verify async methods exist for declared capabilities.
- Reject a plugin that declares `chapter` but does not implement `chapter`.

- [ ] **Step 2: Run loader tests and verify failure**

Run:

```powershell
pytest tests/source_plugins/test_loader.py -q
```

Expected: FAIL because the loader and demo plugin do not exist.

- [ ] **Step 3: Add demo plugin metadata and source**

Create `data/source_plugins/demo_html/metadata.yaml` with:

```yaml
id: demo_html
name: Demo HTML Source
version: 0.1.0
type: source
domains:
  - demo.local
capabilities:
  - search
  - detail
  - toc
  - chapter
tags:
  - demo
  - html
```

Create `data/source_plugins/demo_html/source.py` with a deterministic plugin that reads fixture responses from `ctx.fetch_text()` and parses simple HTML.

- [ ] **Step 4: Implement loader**

Implement:

- `PluginLoader(root_path)`
- `discover() -> list[LoadedPlugin]`
- `load_plugin(plugin_dir) -> LoadedPlugin`
- metadata parsing through `yaml.safe_load`
- source import through `importlib.util.spec_from_file_location`
- method validation against declared capabilities

- [ ] **Step 5: Run loader tests**

Run:

```powershell
pytest tests/source_plugins/test_loader.py -q
```

Expected: PASS.

## Task 3: Runtime Context

**Files:**

- Create: `app/source_plugins/context.py`
- Test: `tests/source_plugins/test_context.py`

- [ ] **Step 1: Write context tests**

Test:

- `ctx.urljoin(base, href)` resolves relative URLs.
- `ctx.select(html, selector)` returns nodes.
- `ctx.text(html, selector)` returns stripped text.
- `ctx.attr(html, selector, attr)` returns attribute text.
- `ctx.clean_html(html)` removes scripts and normalizes paragraphs.
- `ctx.fetch_text(url)` calls an injected fetch function so tests do not hit the network.

- [ ] **Step 2: Run context tests and verify failure**

Run:

```powershell
pytest tests/source_plugins/test_context.py -q
```

Expected: FAIL because context does not exist.

- [ ] **Step 3: Implement context helpers**

Use `bs4` if already available; otherwise add the smallest dependency needed in `requirements.txt` and note it in the test output. The context must accept injected dependencies:

- fetch function
- plugin id
- trace collector
- config dict

Do not let plugins create scheduler-level concurrency.

- [ ] **Step 4: Run context tests**

Run:

```powershell
pytest tests/source_plugins/test_context.py -q
```

Expected: PASS.

## Task 4: So Novel Seed Inspector

**Files:**

- Create: `data/source_seeds/so-novel/README.md`
- Create: `scripts/inspect_so_novel_rules.py`
- Test: `tests/scripts/test_inspect_so_novel_rules.py`

- [ ] **Step 1: Write inspector tests**

Test with a small fixture that mimics So Novel rule entries. Verify the inspector reports:

- total rule count
- rules with search support
- proxy-required IDs
- rate-limit IDs
- cloudflare IDs
- simple conversion candidates where search/book/toc/chapter fields are present and do not require browser-only behavior

- [ ] **Step 2: Run inspector tests and verify failure**

Run:

```powershell
pytest tests/scripts/test_inspect_so_novel_rules.py -q
```

Expected: FAIL because the inspector does not exist.

- [ ] **Step 3: Add So Novel seed notes**

Create `data/source_seeds/so-novel/README.md` with:

- upstream repository URL: `https://github.com/freeok/so-novel`
- source files to copy or fetch: `bundle/rules/main.json`, `proxy-required.json`, `rate-limit.json`, `cloudflare.json`, `rule-template.json5`, `BOOK_SOURCES.md`
- requirement to record upstream commit hash
- note that these rules are input material, not the final runtime format

- [ ] **Step 4: Implement inspector**

Implement `scripts/inspect_so_novel_rules.py` with:

- JSON loading for rule arrays or objects.
- Optional classification files.
- CLI arguments for `--main`, `--proxy-required`, `--rate-limit`, `--cloudflare`.
- JSON summary output.
- A pure function that tests can call without network.

- [ ] **Step 5: Run inspector tests**

Run:

```powershell
pytest tests/scripts/test_inspect_so_novel_rules.py -q
```

Expected: PASS.

## Task 5: Scheduler

**Files:**

- Create: `app/source_plugins/scheduler.py`
- Test: `tests/source_plugins/test_scheduler.py`

- [ ] **Step 1: Write scheduler tests**

Test:

- Search runs enabled plugins concurrently up to `max_concurrency`.
- A timed-out plugin returns structured failure evidence and does not cancel successful plugins.
- A plugin exception becomes a source error with plugin id, stage, URL when available, and message.
- Result dictionaries include `sourceId`.

- [ ] **Step 2: Run scheduler tests and verify failure**

Run:

```powershell
pytest tests/source_plugins/test_scheduler.py -q
```

Expected: FAIL because scheduler does not exist.

- [ ] **Step 3: Implement scheduler**

Implement:

- `PluginScheduler`
- `search(keyword, page)`
- `detail(source_id, book_url)`
- `toc(source_id, toc_url)`
- `chapter(source_id, chapter_url)`

Use existing `source_pool.json` settings:

- `max_concurrency`
- `source_batch_size`
- `source_timeout_seconds`
- `overall_search_timeout_seconds`

The scheduler owns `asyncio.Semaphore`, timeout, failure isolation, and result normalization.

- [ ] **Step 4: Run scheduler tests**

Run:

```powershell
pytest tests/source_plugins/test_scheduler.py -q
```

Expected: PASS.

## Task 6: Catalog Rewire

**Files:**

- Modify: `app/services/catalog.py`
- Modify: `app/services/search_jobs.py`
- Test: `tests/services/test_plugin_catalog.py`

- [ ] **Step 1: Write catalog tests**

Test that:

- `Catalog.search("凡人修仙传", 1)` returns the same public shape as `/api/legado/search`.
- Search cache still works.
- Empty plugin pool returns implemented empty result with debug fields.
- Plugin failures appear in debug errors without breaking partial results.

- [ ] **Step 2: Run catalog tests and verify failure**

Run:

```powershell
pytest tests/services/test_plugin_catalog.py -q
```

Expected: FAIL until catalog uses plugin scheduler.

- [ ] **Step 3: Rewire catalog**

Add an internal plugin scheduler path. Preserve current API response fields:

- `implemented`
- `keyword`
- `page`
- `items`
- `debug`

Keep existing cache methods. Do not change `app/core/source_generator.py` unless endpoint contract changes.

- [ ] **Step 4: Run catalog tests**

Run:

```powershell
pytest tests/services/test_plugin_catalog.py -q
```

Expected: PASS.

## Task 7: Smoke Runner

**Files:**

- Create: `app/source_plugins/smoke.py`
- Create: `data/source_plugins/demo_html/tests/smoke.yaml`
- Test: `tests/source_plugins/test_smoke.py`

- [ ] **Step 1: Write smoke tests**

Test that a smoke fixture can:

- Run search.
- Pick the first result.
- Run detail.
- Run toc.
- Pick the first chapter.
- Run chapter.
- Fail with a clear message when content is too short.

- [ ] **Step 2: Run smoke tests and verify failure**

Run:

```powershell
pytest tests/source_plugins/test_smoke.py -q
```

Expected: FAIL because smoke runner does not exist.

- [ ] **Step 3: Implement smoke runner**

Implement a callable runner and CLI module entry:

```powershell
python -m app.source_plugins.smoke data/source_plugins/demo_html --keyword "凡人修仙传"
```

Return non-zero only when an assertion fails or the plugin cannot load.

- [ ] **Step 4: Run smoke tests**

Run:

```powershell
pytest tests/source_plugins/test_smoke.py -q
```

Expected: PASS.

## Task 8: First So Novel Plugin Conversion

**Files:**

- Create: `data/source_plugins/<chosen_so_novel_source>/metadata.yaml`
- Create: `data/source_plugins/<chosen_so_novel_source>/source.py`
- Create: `data/source_plugins/<chosen_so_novel_source>/tests/smoke.yaml`
- Test: `tests/source_plugins/test_so_novel_conversion_smoke.py`

- [ ] **Step 1: Select candidates from inspector output**

Run the inspector against the pinned So Novel seed:

```powershell
python scripts/inspect_so_novel_rules.py --main data/source_seeds/so-novel/main.json --proxy-required data/source_seeds/so-novel/proxy-required.json --rate-limit data/source_seeds/so-novel/rate-limit.json --cloudflare data/source_seeds/so-novel/cloudflare.json
```

Expected: JSON summary with simple conversion candidates.

- [ ] **Step 2: Pick 2 to 3 simple candidates**

Prefer candidates that:

- support search
- do not require Cloudflare
- do not require login
- do not require browser/WebView
- have normal search/detail/toc/chapter fields

- [ ] **Step 3: Write conversion smoke tests**

For each chosen candidate, create a smoke test using captured or fixture HTML where possible. If live verification is required, mark it as integration and keep unit tests fixture-backed.

- [ ] **Step 4: Implement plugins**

Use `docs/skills/book-source-craft/references/source-plugin-template.md` as the starting point. Convert useful selectors, paths, and parsing behavior from So Novel rules into Python plugin methods.

- [ ] **Step 5: Run conversion smoke tests**

Run:

```powershell
pytest tests/source_plugins/test_so_novel_conversion_smoke.py -q
```

Expected: PASS for fixture-backed tests.

## Task 9: Admin Console Rewire

**Files:**

- Modify: `app/api/admin.py`
- Modify: `app/web/admin.py`
- Test: `tests/test_admin_plugin_api.py`

- [ ] **Step 1: Write admin API tests**

Test endpoints:

- `GET /api/admin/plugins`
- `GET /api/admin/plugins/{plugin_id}`
- `POST /api/admin/plugins/reload`
- `POST /api/admin/plugins/{plugin_id}/smoke`

- [ ] **Step 2: Run admin tests and verify failure**

Run:

```powershell
pytest tests/test_admin_plugin_api.py -q
```

Expected: FAIL because endpoints do not exist.

- [ ] **Step 3: Implement admin endpoints and UI links**

Expose plugin metadata, status, capabilities, domains, and last smoke result. Add a dense Chinese plugin operations section to the existing HTML admin console.

- [ ] **Step 4: Run admin tests**

Run:

```powershell
pytest tests/test_admin_plugin_api.py -q
```

Expected: PASS.

## Task 10: Source Craft Skill Alignment

**Files:**

- Modify: `docs/skills/book-source-craft/SKILL.md`
- Modify: `docs/skills/book-source-craft/references/public-source-references.md`
- Test: documentation check with grep.

- [ ] **Step 1: Check old wording**

Run:

```powershell
Select-String -Path 'docs\skills\book-source-craft\**\*.md' -Pattern 'LegadoHub rules|native rule|one-site Legado book source'
```

Expected: Any matches are reviewed and either updated or explicitly marked as legacy reference.

- [ ] **Step 2: Align wording**

Update source craft docs so the primary output is a Python plugin. Keep aggregate shell generation as a compatibility output.

- [ ] **Step 3: Re-run wording check**

Run:

```powershell
Select-String -Path 'docs\skills\book-source-craft\**\*.md' -Pattern 'LegadoHub rules|native rule|one-site Legado book source'
```

Expected: No unmarked active-direction matches.

## Final Verification

Run:

```powershell
pytest tests/source_plugins tests/services/test_plugin_catalog.py tests/test_admin_plugin_api.py -q
pytest tests -q
git diff --check
```

Expected:

- New plugin runtime tests pass.
- Existing API/cache/source-generator tests still pass.
- `git diff --check` reports no whitespace errors.

If full `pytest tests -q` fails because of unrelated legacy Reading-rule tests, record the exact failing tests and run the plugin-specific subset plus aggregate-source tests before reporting progress.
