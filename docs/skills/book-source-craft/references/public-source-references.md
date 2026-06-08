# Public Source References

Use these repositories and sites as reference inputs when creating or evolving LegadoHub Python source plugins.

The native output is a Python source plugin, not a Reading source JSON. Reading source JSON and So Novel rules are useful for discovering selectors, API paths, site families, anti-bot notes, and repeated templates.

## Reading Source Repositories

- `XIU2/Yuedu`: direct Legado source file, small and suitable for first tests.
- `aoaostar/legado`: release branch contains generated `sources/*.json`; main branch is a Python sync reference.
- `sjshb57/legado-57`: candidate rules and helper sources; classify before using.
- `Yiove 综合书源库`: discovery index; do not blindly scrape all in early stages.

## Legacy Engine References

- `Luoyacheng/legado`: semantic reference for Legado rule behavior.
  - `AnalyzeRule.kt`
  - `AnalyzeUrl.kt`
  - `RuleAnalyzer.kt`
  - `AnalyzeByJSoup.kt`
  - `AnalyzeByXPath.kt`
  - `AnalyzeByJSonPath.kt`
  - `AnalyzeByRegex.kt`
  - `BookSource.kt`
  - `model/webBook/SearchModel.kt`
  - `BookChapterList.kt`
  - `BookContent.kt`

Use these only when understanding legacy Reading rule behavior or importing historical source knowledge. Do not expand the old Reading-kernel-port route unless the user explicitly asks.

## So Novel References

- `freeok/so-novel`: rule-model and crawler behavior reference.
  - Initial LegadoHub source seed should come from this project.
  - `bundle/rules/main.json`
  - `proxy-required.json`
  - `rate-limit.json`
  - `no-search.json`
  - `cloudflare.json`
  - `rule-template.json5`
  - `Rule.java`
  - `AggregatedSearchAction.java`
  - parser classes
  - `Crawler.java`

Treat So Novel rules as a second input format, not native Legado source JSON and not the final LegadoHub runtime format. Convert useful behavior into a Python source plugin or document why direct conversion is not possible.

Initial import priority:

1. Start with `bundle/rules/main.json`.
2. Exclude or defer entries listed in `cloudflare.json` for the MVP.
3. Mark entries in `proxy-required.json` as proxy candidates.
4. Mark entries in `rate-limit.json` for conservative scheduling.
5. Pick 2 to 3 simple searchable sources as the first Python plugin conversions.

## Inspection Checklist

When reviewing a public source:

- Is it a direct Legado source, an aggregate shell, a sync tool, or another rule format?
- What license applies?
- How many source entries are present?
- Which modules are filled: search, explore, detail, toc, content?
- Does it use heavy JS or external APIs?
- Does it require cookies, login, proxy, WebView, Cloudflare, or rate limits?
- Which selectors, API paths, headers, cookies, or special algorithms are reusable in a Python plugin?
- Does it belong to an existing repeated-site template?
- Can a minimal plugin subset be used for LegadoHub MVP?
