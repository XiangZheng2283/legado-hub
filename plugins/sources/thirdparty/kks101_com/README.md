# 101看书网

- Plugin ID: `kks101_com`
- Domain: `101kks.com`
- Base URL: `https://101kks.com`
- Auth: none
- Content: free

## Fixture Smoke

Fixture validation uses captured pages under `smoke/fixtures/`:

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/kks101_com
```

Detail output should fill Reading-compatible fields whenever the page exposes
them: `name`, `author`, `bookUrl`, `coverUrl`, `intro`, `kind`, `lastChapter`,
`wordCount`, `tocUrl`, `authRequired`, and useful extras such as `status` or
`updateTime`.

Ordinary mirror/scraper sources must not declare `explore`; ranking and category
capabilities are reserved for official/licensed sources.

## 2026-07-31 实网复核

- 强制代理会触发 HTTP 429，现改为宿主自动路由；Stealth 遇挑战或限流时仅对 GET 深层页回退共享 Browser profile。
- 四段实测通过：搜索 19 条、目录 600 章、正文 2955 字符。
