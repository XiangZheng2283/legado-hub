# LegadoHub Plugin Source Runtime Restart Plan

> **For agentic workers:** This document is the new planning source of truth after the 2026-06-07 restart. Keep the aggregate Reading/Legado source provider and the backend operations console. Do not continue the old direction as a full Reading rule compatibility project unless the user explicitly asks for that route again.

**Goal:** Rebuild LegadoHub around a self-maintained Python source plugin runtime, while still exposing one aggregate source to Reading/Legado clients.

**Architecture:** Reading/Legado remains an import target, not the internal source format. LegadoHub owns source execution through Python plugins, central scheduling, shared network/cookie/cache/proxy runtime, and operational diagnostics. Existing aggregate source generation and backend UI planning are retained as the compatibility and operations surface.

**Tech Stack:** Python 3, FastAPI, SQLite, async source scheduler, Python plugin modules, React/Vite/TypeScript/shadcn/ui console frontend.

---

## New Direction

LegadoHub should move from "compatibly execute every Reading BookSource rule" to "run self-maintained novel source plugins and expose their results through a Reading-compatible aggregate shell."

The internal source model should be closer to an extension/plugin system:

```text
Reading App
  -> one imported LegadoHub aggregate source
  -> LegadoHub API
  -> SourceScheduler
  -> Python source plugins
  -> shared ctx runtime for HTTP, cookie, proxy, cache, trace, timeout
```

The source plugin is responsible for site-specific adaptation. The core service is responsible for runtime control.

## Retained Assets

### Aggregate Source Provider

Keep:

- `app/core/source_generator.py`
- `app/core/aggregate_config.py`
- `app/api/legado.py`
- `backend/config/aggregate_source.json`
- `backend/generated/legadohub-source.json`
- `docs/reference-aggregate-source.md`

Reason:

- Reading/Legado still needs one importable source.
- The aggregate source shell is the right compatibility boundary.
- Service-side APIs can change internally as long as the aggregate shell contract remains stable.

Required adjustment:

- `source_generator.py` should continue generating one source object.
- The generated source should call LegadoHub APIs that are backed by the new plugin runtime, not by Reading rule execution.
- The aggregate source JS/rules should stay thin: request, decode, parse JSON, and report errors.

### Backend Operations Console

Keep:

- The backend operations-console information architecture and prior page planning.
- `frontend/` as the active React/Vite console.
- `app/api/console.py`
- Source list, test, trace, cache, settings, update, verification, and generated-source screens as planning assets.

Reason:

- The product remains a local operations console.
- The UI principles in `docs/PRODUCT.md` still fit: evidence first, dense but calm, no fake status, failures visible.
- A plugin runtime needs even stronger operational visibility than a rule runtime.

Required adjustment:

- Rename source-facing concepts from "Reading source rule execution" to "source plugin execution" where appropriate.
- Add plugin status, plugin metadata, plugin smoke tests, plugin reload, and plugin failure evidence.
- Replace the static/server-rendered HTML console with a React/Vite/TypeScript/shadcn/ui frontend in Stage 1.
- Keep the visual style aligned with the previous backend plan: dense Chinese operations console, real data, evidence-first status, no fake/demo content.

### Existing Service Capabilities

Keep or adapt:

- `app/services/cache.py` for search/book/toc/chapter cache.
- `app/services/search_jobs.py` for real-time job state and SSE concepts.
- `app/services/catalog.py` as the public catalog orchestration layer, but rewire it to plugin execution.
- `app/services/plugin_health_repository.py` as the plugin runtime health and attempt store.
- `backend/config/source_pool.json` concurrency, timeout, proxy, and preflight settings.

Reason:

- These files already express the right operational concerns: concurrency, timeout, source health, failure recording, proxy fallback, cache, and partial success.
- The execution target changes, but the orchestration responsibilities remain valuable.

## Initial Source Seed

Use `freeok/so-novel` as the first source seed and conversion reference.

Primary inputs:

- `bundle/rules/main.json`: default mainland-accessible sources with search support.
- `bundle/rules/rule-template.json5`: rule field reference for search, book, toc, chapter, and crawl behavior.
- `bundle/rules/proxy-required.json`: sources that likely need proxy.
- `bundle/rules/rate-limit.json`: sources with rate-limit concerns.
- `bundle/rules/cloudflare.json`: sources that should be treated as special or lower-priority.
- `BOOK_SOURCES.md`: status notes for source groups and support coverage.

Use these inputs as a rule mine, not as the final runtime format.

Recommended first pass:

1. Vendor or cache a pinned snapshot under `plugins/seeds/so-novel/`.
2. Record the upstream commit hash and retrieval date.
3. Parse `main.json` and classify rules by complexity.
4. Convert 2 to 3 simple HTML/JSON sources into Python plugins.
5. Convert one repeated family into a reusable template if patterns are obvious.
6. Mark `proxy-required`, `rate-limit`, and `cloudflare` sources as special candidates, not MVP blockers.

Do not start with Cloudflare or login-heavy sources. The first milestone should prove that So Novel rules can seed normal Python source plugins while LegadoHub keeps scheduling, timeout, proxy, cache, and trace ownership.

## Plugin Contract

The plugin API is defined by `docs/architecture/source-plugin-contract.md`.

Do not let implementation agents invent a different interface. If a source needs extra behavior, extend the contract in a backward-compatible way first.

Key contract commitments:

- Stage 1 accepts `contractVersion: "1.0"`.
- Plugins expose async lifecycle methods for declared capabilities.
- Plugins return normalized search/detail/toc/chapter data.
- Plugins may request auth/manual-login support but do not own browser or session orchestration.
- Official or login-based sources such as 起点、番茄、七猫、QQ 阅读 are supported by metadata, auth hooks, cookie context, and console actions.
- Paid or locked content must be reported as `AUTH_REQUIRED` or `PAID_CONTENT_REQUIRED`, not disguised as parse errors.
- Dependencies may be installed for this private project, but must be recorded in `backend/requirements.txt`, `frontend/package.json`, or plugin-local `requirements.txt`.

## Deprecated Direction

The old direct Reading kernel port is no longer the main path.

Deprecate as primary direction:

- Treating `engine-jvm/` as the future core execution engine.
- Completing full Reading rule compatibility as the central product milestone.
- Growing `app/legado_engine/` as a self-written Reading rule executor.
- Treating public Reading source subscriptions as the main long-term runtime input.

Allowed uses:

- Reference material for understanding common source patterns.
- Migration or sampling input for creating Python source plugins.
- Optional compatibility layer if the user later wants a "legacy Reading source import" feature.

## Plugin Runtime Model

Each source plugin should be a small Python package or directory with metadata and one source implementation.

Recommended layout:

```text
plugins/sources/
  example_plugin/
    metadata.yaml
    source.py
    requirements.txt
    README.md
    tests/
      smoke.yaml
    skills/
      SKILL.md
```

Minimal metadata:

```yaml
id: example_plugin
name: 示例书源
version: 0.1.0
type: source
domains:
  - example.com
capabilities:
  - search
  - detail
  - toc
  - chapter
tags:
  - html
  - no-login
```

Minimal source interface:

```python
class Source:
    id = "example_plugin"
    name = "示例书源"

    async def search(self, ctx, keyword: str, page: int):
        ...

    async def detail(self, ctx, book_url: str):
        ...

    async def toc(self, ctx, book_url: str):
        ...

    async def chapter(self, ctx, chapter_url: str):
        ...
```

The plugin should return standard data objects or dictionaries that LegadoHub normalizes:

- Search result: name, author, intro, coverUrl, kind, lastChapter, wordCount, bookUrl, sourceId.
- Book detail: name, author, intro, coverUrl, kind, lastChapter, wordCount, tocUrl.
- Toc item: title, chapterUrl, updateTime, index.
- Chapter content: title, content, sourceId, chapterUrl.

## Hard Boundary

Plugins may handle special site logic:

- CSS/XPath parsing.
- Strange pagination.
- JS token extraction.
- API signature generation.
- Chapter decryption.
- Alternate domain selection.
- Content cleanup that is specific to a site response.

Plugins must not own runtime control:

- No source-level concurrency decisions.
- No global retry policy.
- No independent proxy switching policy.
- No global cache policy.
- No source health scoring.
- No Reading/Legado response shaping.

Preferred network access:

```python
html = await ctx.fetch_text(url)
data = await ctx.fetch_json(api_url)
pages = await ctx.fetch_many(urls)
```

`ctx` owns:

- Global concurrency.
- Per-host concurrency.
- Per-source timeout.
- Request timeout.
- Cookie jar.
- Proxy mode.
- Rate limit.
- Cache hooks.
- Trace events.
- Failure classification.

## AI Source Craft Skill

The long-term maintenance advantage comes from a repeatable AI-assisted plugin creation workflow.

The project should eventually provide a local skill that can:

1. Accept site URLs, captured HTML, existing failed attempts, or a similar plugin.
2. Identify whether the site fits an existing template.
3. Generate `metadata.yaml`.
4. Generate `source.py`.
5. Generate a smoke fixture.
6. Run search/detail/toc/chapter smoke tests.
7. Repair the plugin from failure evidence.
8. Produce a short adaptation note.

This skill should prefer templates first:

```text
templates/
  biquge_family.py
  mobile_biquge.py
  wordpress_novel.py
  json_api.py
```

Special websites can override only the methods they need.

## Phase Plan

### Phase 0: Planning Reset

Outcomes:

- This document exists as the new direction.
- Existing roadmap points to this document.
- `docs/PRODUCT.md` reflects the plugin-source product direction.

Validation:

- `git diff -- docs/architecture/plugin-source-runtime-restart-plan.md docs/PRODUCT.md`

### Phase 1: Plugin Contract And Data Model

Outcomes:

- Add plugin metadata model.
- Add normalized result models.
- Add a plugin discovery service.
- Add a minimal in-process plugin loader.
- Add tests for metadata loading and interface validation.

Suggested files:

- `backend/app/source_plugins/models.py`
- `backend/app/source_plugins/loader.py`
- `backend/app/source_plugins/runtime.py`
- `tests/source_plugins/test_loader.py`

### Phase 2: Runtime Context

Outcomes:

- Add `ctx.fetch_text`, `ctx.fetch_json`, and `ctx.fetch_many`.
- Route network through existing timeout, proxy, cookie, trace, and failure classification policies.
- Keep plugin code focused on parsing and site-specific transformations.

Suggested files:

- `backend/app/source_plugins/context.py`
- `backend/app/source_plugins/fetch.py`
- `tests/source_plugins/test_context.py`

### Phase 3: Scheduler Rewire

Outcomes:

- Rewire `Catalog.search/detail/toc/chapter` to call plugin runtime.
- Preserve aggregate source API shape for Reading/Legado.
- Preserve cache behavior.
- Preserve partial-success debug fields.

Suggested files:

- `app/services/catalog.py`
- `app/services/search_jobs.py`
- `app/api/legado.py`
- `tests/services/test_plugin_catalog.py`

### Phase 4: First Source Plugins

Outcomes:

- Add a pinned `freeok/so-novel` source seed snapshot or documented retrieval script.
- Add a So Novel rule inspection/import helper.
- Convert 2 to 3 simple So Novel rules into Python source plugins.
- Add one template-based repeated-site plugin if the first rules reveal a common family.
- Mark one special So Novel rule as a future custom plugin candidate, but do not block MVP on it.

Suggested files:

- `plugins/sources/example_html/`
- `plugins/sources/biquge_family_demo/`
- `plugins/sources/special_demo/`
- `plugins/seeds/so-novel/`
- `dev-assets/probes/inspect_so_novel_rules.py`（本地探测脚本，不推送）
- `tests/source_plugins/test_smoke_runner.py`

### Phase 5: Console Rewire

Outcomes:

- Add plugin list, enabled state, metadata, capabilities, domains, and health.
- Add plugin reload button.
- Add smoke-test action.
- Add failure evidence display by plugin/stage/url.
- Keep current dense Chinese operations style.

Suggested files:

- `app/api/console.py`
- `frontend/`
- `app/services/plugin_health_repository.py`

### Phase 6: AI-Assisted Source Craft

Outcomes:

- Convert `docs/skills/book-source-craft/` from Reading-rule craft into Python plugin craft.
- Add template references.
- Add generated-plugin checklist.
- Add smoke-test repair loop instructions.

Suggested files:

- `docs/skills/book-source-craft/SKILL.md`
- `docs/skills/book-source-craft/references/plugin-source-workflow.md`
- `docs/skills/book-source-craft/references/source-plugin-template.md`

## Completion Criteria For The Restart

The restart is successful when:

- Reading app imports one LegadoHub aggregate source.
- Search results come from Python source plugins.
- Book detail, toc, and chapter content work through normalized plugin outputs.
- Console can show plugin health, attempts, failures, and cache status.
- Plugin smoke tests can validate search/detail/toc/chapter without using Reading app.
- Source scripts do not control source-level concurrency or system-wide runtime policy.

## Risk Register

- Existing code has many Reading-rule-era names; rename gradually to avoid churn before runtime is working.
- The old JVM engine has been moved to `docs/archive/legacy-reading-engine/2026-06-07/engine-jvm/` and must not receive new feature work on this branch.
- Direct Python plugin execution is acceptable for this private project, but the runtime should still keep timeout and cancellation controls.
- AI-generated plugins will need strong smoke tests; otherwise generated scripts can look plausible while silently returning bad data.

