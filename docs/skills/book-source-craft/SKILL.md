---
name: book-source-craft
description: Create, debug, review, or evolve Legado/阅读 APP book sources and aggregate source shells. Use when the user asks to write a source rule, make a Legado source, generate a bookSource JSON, inspect public reading sources, adapt sources from XIU2/Yuedu, aoaostar/legado, Yiove, So Novel rules, or produce a LegadoHub aggregate source. Do not use for unrelated crawler projects or non-Legado formats unless converting them into LegadoHub rules.
---

# Book Source Craft

Use this skill to create or review Legado-compatible book sources and LegadoHub aggregate source shells.

## Core Principles

- Work module by module: base info, discovery, search, detail, toc, content, then final JSON.
- Validate each module before building the next one when a live website is involved.
- Prefer evidence from live HTML, public source JSON, or saved samples over guessing selectors.
- Keep source-side JS thin for LegadoHub aggregate sources; put heavy logic in the service.
- Treat public source repositories as examples and compatibility references, not blindly trusted code.

## Source Types

Choose the path before writing rules:

- **Normal Legado source**: a source JSON for one website.
- **Aggregate shell source**: a single source that calls a local/remote aggregation API, like the `光遇聚合26.6.2.json` sample.
- **LegadoHub native rule**: an internal rule representation that may later generate Legado source JSON.
- **Imported source review**: inspect existing public source JSON and summarize fields, risks, and reusable patterns.

## Required Workflow

1. Identify target: website URL, existing source JSON, aggregate API, or public source repository.
2. Check accessibility and encoding for live sites.
3. Inspect reference examples before creating rules.
4. Draft the smallest useful module.
5. Ask the user to validate in Legado when runtime behavior cannot be verified locally.
6. Merge only verified modules into the current source JSON.
7. Deliver the full JSON plus a short validation checklist.

For detailed module-by-module instructions, read `references/legado-module-workflow.md`.

For aggregate source generation, read `references/aggregate-source-pattern.md`.

For public source inspection and examples, read `references/public-source-references.md`.

## Practical Defaults

- Use mobile User-Agent by default.
- Set `enabledCookieJar: true` unless there is a reason not to.
- Set text novel sources to `bookSourceType: 0`.
- Use `bookSourceType: 0` plus HTML image tags when image URLs use non-image suffixes that Legado mishandles.
- Keep `bookSourceUrl` stable and unique.
- Include `bookSourceName` versioning for generated aggregate shells.

## Validation

For existing source JSON files, run:

```bash
python scripts/inspect_legado_source.py path/to/source.json
```

Use the output to understand top-level fields, module coverage, JS size, and likely complexity before editing.
