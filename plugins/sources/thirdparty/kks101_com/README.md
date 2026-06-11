# 101看书网

- Plugin ID: `kks101_com`
- Domain: `101kks.com`
- Base URL: `https://101kks.com`
- Auth: none
- Content: free

## Fixture Smoke

Replace `tests/fixtures/*.html` with captured search/detail/toc/chapter pages, then run:

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/kks101_com
```

Detail output should fill Reading-compatible fields whenever the page exposes
them: `name`, `author`, `bookUrl`, `coverUrl`, `intro`, `kind`, `lastChapter`,
`wordCount`, `tocUrl`, `authRequired`, and useful extras such as `status` or
`updateTime`.

Ordinary mirror/scraper sources must not declare `explore`; ranking and category
capabilities are reserved for official/licensed sources.
