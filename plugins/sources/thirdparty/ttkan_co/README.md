# 天天看书网

- Plugin ID: `ttkan_co`
- Domain: `ttkan.co`
- Base URL: `https://www.ttkan.co`
- Auth: none
- Content: free

## Fixture Smoke

Replace `tests/fixtures/*.html` with captured search/detail/toc/chapter pages, then run:

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/ttkan_co
```

Detail output should fill Reading-compatible fields whenever the page exposes
them: `name`, `author`, `bookUrl`, `coverUrl`, `intro`, `kind`, `lastChapter`,
`wordCount`, `tocUrl`, `authRequired`, and useful extras such as `status` or
`updateTime`.

现场校对补充：

- 目录页已确认存在 `GET /api/nq/amp_novel_chapters?language=tw&novel_id=...`
  可直接拿完整目录，优先于 HTML 列表。
- 搜索页可能返回泛推荐书单。插件必须确认书名真实命中后再返回结果，
  不能把整页推荐项当成有效搜索结果。

Ordinary mirror/scraper sources must not declare `explore`; ranking and category
capabilities are reserved for official/licensed sources.
