# So Novel Seed Snapshot

> **Input seed only, not runtime format.** These files are used as reference material for creating LegadoHub Python source plugins. LegadoHub does not execute So Novel rules directly.

## Upstream

- **Repository:** https://github.com/freeok/so-novel
- **Commit:** `bfb5fda1d6ea04ad7f30a761640e08ce2e5db0e0`
- **Retrieval date:** 2026-06-06
- **Retrieval method:** curl from GitHub raw content

## Files

| File | Purpose |
|---|---|
| `main.json` | Default mainland-accessible sources with search support |
| `proxy-required.json` | Sources that likely need proxy |
| `rate-limit.json` | Sources with rate-limit concerns |
| `cloudflare.json` | Sources that should be treated as special or lower-priority |
| `rule-template.json5` | Rule field reference for search, book, toc, chapter, and crawl behavior |
| `BOOK_SOURCES.md` | Status notes for source groups and support coverage |

## Usage

Run the inspector to classify and summarize the seed:

```powershell
cd backend
python scripts/inspect_so_novel_rules.py --main ../plugins/seeds/so-novel/main.json --proxy-required ../plugins/seeds/so-novel/proxy-required.json --rate-limit ../plugins/seeds/so-novel/rate-limit.json --cloudflare ../plugins/seeds/so-novel/cloudflare.json
```
