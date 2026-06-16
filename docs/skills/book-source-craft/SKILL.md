---
name: book-source-craft
description: Create, debug, review, or evolve LegadoHub Python source plugins and aggregate Reading/Legado source shells. Use when the user asks to adapt a novel site, generate a Python source plugin, inspect public reading sources as references, convert repeated site patterns into templates, repair a special source, or produce the LegadoHub aggregate source. Do not use for unrelated crawler projects unless converting them into LegadoHub source plugins.
---

# Book Source Craft

Use this skill to create or review LegadoHub Python source plugins and the thin Reading/Legado aggregate shell that exposes LegadoHub to the Reading app.

## Core Principles

- Treat Reading/Legado as an output compatibility surface, not the internal source format.
- Work module by module: metadata, search, detail, toc, chapter, then smoke tests.
- Keep concurrency, timeout, proxy, cache, retry, and health scoring in LegadoHub core.
- Put only site-specific adaptation inside the plugin.
- Prefer evidence from live HTML, captured pages, failed traces, public source JSON, or saved samples over guessing selectors.
- Prefer existing source templates before writing one-off plugin logic.
- Keep aggregate source-side JS thin; put heavy logic in LegadoHub service APIs.
- Treat public source repositories as examples and pattern references, not blindly trusted runtime code.

## Source Types

Choose the path before writing rules:

- **Python source plugin**: a LegadoHub-native plugin implementing search, detail, toc, and chapter.
- **Template-based plugin**: a plugin that inherits or configures a common repeated-site template.
- **Special-site plugin**: a plugin with custom token, signing, decryption, pagination, or anti-bot handling.
- **Aggregate shell source**: a single Reading/Legado source that calls LegadoHub APIs.
- **Imported source review**: inspect existing public source JSON or So Novel rules and summarize reusable patterns.

## Required Workflow

1. Identify target: website URL, captured page, existing source JSON, aggregate API, or public source repository.
2. Check accessibility and encoding for live sites.
3. Inspect reference examples and existing templates before creating plugin code.
4. Draft the smallest useful plugin module.
5. Run search/detail/toc/chapter smoke checks through LegadoHub tooling when available.
6. Repair from concrete failure evidence instead of rewriting blindly.
7. Deliver plugin files plus a short validation checklist.

For detailed plugin instructions, read `references/plugin-source-workflow.md`.

For Stage 2 plugin production, fixture smoke, validation scripts, and AI adaptation workflow, read `references/stage-2-plugin-production.md`.

For plugin file templates, read `references/source-plugin-template.md`.

For aggregate source generation, read `references/aggregate-source-pattern.md`.

For public source inspection and examples, read `references/public-source-references.md`.

## Practical Defaults

- Use mobile User-Agent by default.
- Use plugin `metadata.yaml` for id, name, version, domains, capabilities, and tags.
- Use `ctx.fetch_text`, `ctx.fetch_json`, or `ctx.fetch_many` instead of direct network libraries.
- Return normalized data dictionaries; let LegadoHub shape Reading/Legado API responses.
- Keep source IDs stable and unique.
- Include versioning for generated aggregate shells.

## Validation

For existing source JSON files used as references, run:

```bash
python dev-assets/probes/inspect_legado_source.py path/to/source.json
```

Use the output to understand top-level fields, module coverage, JS size, and likely complexity before editing.

> Note: `inspect_legado_source.py` is a local development probe kept in `dev-assets/`, which is gitignored and not pushed.

For Python source plugins, create and validate with Stage 2 tooling:

```powershell
cd backend
python scripts/create_source_plugin.py --id example_com --name 示例书源 --domain example.com --base-url https://example.com
python scripts/validate_source_plugin.py --plugin ../plugins/sources/example_com
python -m app.source_plugins.smoke ../plugins/sources/example_com --keyword "凡人修仙传"
```

Fixture smoke must cover search, detail, toc, and chapter without live network. Use service-level search/detail/toc/chapter API only after fixture smoke passes.
