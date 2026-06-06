# Public Source References

Use these repositories and sites as inputs when creating or evolving sources.

## Reading Source Repositories

- `XIU2/Yuedu`: direct Legado source file, small and suitable for first tests.
- `aoaostar/legado`: release branch contains generated `sources/*.json`; main branch is a Python sync reference.
- `sjshb57/legado-57`: candidate rules and helper sources; classify before using.
- `Yiove 综合书源库`: discovery index; do not blindly scrape all in early stages.

## Engine References

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

## So Novel References

- `freeok/so-novel`: rule-model and crawler behavior reference.
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

Treat So Novel rules as a second input format, not native Legado source JSON. Convert them through a `SoNovelRuleAdapter` or document why direct conversion is not possible.

## Inspection Checklist

When reviewing a public source:

- Is it a direct Legado source, an aggregate shell, a sync tool, or another rule format?
- What license applies?
- How many source entries are present?
- Which modules are filled: search, explore, detail, toc, content?
- Does it use heavy JS or external APIs?
- Does it require cookies, login, proxy, WebView, Cloudflare, or rate limits?
- Can a minimal subset be used for LegadoHub MVP?
