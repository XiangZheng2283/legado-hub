# Aggregate Source Pattern

Use this when generating a single source shell for LegadoHub or another aggregation API.

## Reference Shape

The archived sample `docs/archive/legacy-reading-engine/2026-06-07/data/sources/reference/光遇聚合26.6.2.json` is a single-source JSON array with:

- `bookSourceName`
- `bookSourceUrl`
- `bookSourceGroup`
- `bookSourceType`
- `searchUrl`
- `ruleSearch`
- `ruleBookInfo`
- `ruleToc`
- `ruleContent`
- `ruleExplore`
- large `jsLib`

## Design Rule

Keep the Legado source as a thin shell:

- Encode search/detail/toc/chapter parameters.
- Request LegadoHub endpoints.
- Decode JSON or base64 payloads.
- Map response fields to Legado rules.
- Delegate merge, AI normalization, fallback, cache, and scheduling to LegadoHub.

## Suggested Endpoint Contract

Prefer stable JSON endpoints:

- `GET /api/legado/search?keyword=&page=&scope=`
- `GET /api/legado/book?id=`
- `GET /api/legado/toc?book_id=`
- `GET /api/legado/chapter?book_id=&chapter_id=`
- `GET /api/legado/explore?category=&page=`

Recommended response shapes:

```json
{
  "items": [
    {
      "id": "stable-result-id",
      "name": "书名",
      "author": "作者",
      "intro": "简介",
      "coverUrl": "https://...",
      "kind": "分类/状态/来源",
      "lastChapter": "最新章节",
      "wordCount": "字数",
      "sourceCount": 3
    }
  ]
}
```

```json
{
  "chapters": [
    {
      "id": "chapter-id",
      "title": "第1章",
      "url": "opaque-or-service-url",
      "updateTime": "2026-06-05"
    }
  ]
}
```

```json
{
  "title": "第1章",
  "content": "正文内容",
  "format": "text",
  "source": "source-id",
  "cached": true
}
```

## Source Shell Constraints

- Generate a JSON array containing one source object.
- Use a stable `bookSourceUrl`, for example `LegadoHub`.
- Include version in `bookSourceName`, for example `LegadoHub 聚合(0.1.0)`.
- Put base API URL in one place, preferably `jsLib`.
- Do not scatter service URLs across many rules.
- Keep `enabledCookieJar: true`.
- Include `bookSourceGroup: 聚合,LegadoHub`.

## Minimum Rule Flow

1. `searchUrl` builds a data URL or service URL.
2. `ruleSearch.bookList` returns `$.items`.
3. `ruleSearch.bookUrl` encodes selected result id.
4. `ruleBookInfo.init` requests or decodes book detail.
5. `ruleBookInfo.tocUrl` encodes book id.
6. `ruleToc.chapterList` returns `$.chapters`.
7. `ruleToc.chapterUrl` encodes chapter id.
8. `ruleContent.content` requests chapter content and returns text or HTML.

## Future Generation From Plugin Metadata

When LegadoHub source plugins exist, generate the aggregate source from plugin/API metadata rather than hand-maintaining JS. Keep this reference focused on Reading/Legado output compatibility.
