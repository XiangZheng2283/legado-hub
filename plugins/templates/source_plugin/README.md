# 示例书源

- Plugin ID: `example_com`
- Domain: `example.com`
- Auth: none
- Content: unknown

Replace fixture files under `tests/fixtures/`, implement `source.py` with `ctx` APIs only, then run:

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/example_com
```

Detail output should fill Reading-compatible fields whenever the page exposes
them: `name`, `author`, `bookUrl`, `coverUrl`, `intro`, `kind`, `lastChapter`,
`wordCount`, `tocUrl`, `authRequired`, and useful extras such as `status` or
`updateTime`.

Search output must be useful on its own. If the search page omits `author`,
`lastChapter`, `kind`, `wordCount`, or `updateTime`, enrich the result inside
the source plugin by calling the plugin's own detail parser for a bounded number
of stable candidates. Do not leave these fields for the scheduler to repair.

Before writing HTML selectors, inspect the site for JSON/AJAX/get endpoints:
search APIs, complete chapter-list APIs, and chapter content APIs. Prefer those
interfaces when they are stable; use page parsing only as the fallback. Record
failed endpoint probes in traces or validation notes so future maintainers know
why HTML parsing is used.

TOC output must be complete and ordered. Many mirror sites render a preview
block with the latest chapters plus the first page of the catalog; follow
pagination or AJAX chapter-list endpoints until the full catalog is collected.
Do not deduplicate only by chapter number because extras such as `番外`, `完结感言`,
or unnumbered chapters are valid catalog entries.

Chapter output must be plain text with paragraph breaks. Merge same-chapter
pagination, strip title page markers such as `(1/2)`, and remove site chrome,
short ad blocks, download prompts, missing-chapter notices, and recommendation
text. If a source page itself returns missing or polluted content, return empty
or trace the limitation rather than caching obviously bad text as valid content.

Ordinary mirror/scraper sources must not declare `explore`; ranking and category
capabilities are reserved for official/licensed sources.

## Host-layer boundaries

Do not read or write `Cookie.json` inside the plugin directory. Use `ctx.cookies`
for Cookie payload access; the host owns the file at
`backend/config/cookies/<plugin_id>.json`. Proxy is direct by default; declare
`proxy.mode` and `proxy.required` in `metadata.yaml` only if the source actually
needs it. Do not rely on search events or health state being persisted: the host
keeps search events in memory and writes process/debug logs to
`backend/runtime/logs/`.
