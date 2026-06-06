# Legado Module Workflow

Use this workflow for one-site Legado book source creation.

## 1. Website Check

Check the target with at least two methods:

```bash
curl -sI -L --connect-timeout 10 --max-time 15 "https://example.com"
curl -s -L --connect-timeout 10 --max-time 15 "https://example.com" | head
```

Confirm:

- HTTP status and redirects.
- Charset: UTF-8, GBK, GB2312, Big5, etc.
- Mobile vs desktop layout differences.
- Whether search exists.
- Whether pages require cookies, headers, proxy, or WebView-style JS.

If access fails, try:

- `http://` and `https://`
- with and without `www.`
- `-L` redirects
- mobile User-Agent

## 2. Base Module

Draft only base fields first:

```json
{
  "bookSourceName": "网站名称",
  "bookSourceGroup": "小说",
  "bookSourceUrl": "https://example.com",
  "bookSourceType": 0,
  "enabled": true,
  "enabledCookieJar": true,
  "enabledExplore": true,
  "customOrder": 0,
  "header": {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
  },
  "respondTime": 20000,
  "weight": 0
}
```

Ask the user to confirm it can be saved in Legado before continuing.

## 3. Discovery Module

Inspect category/list pages. Identify:

- list item selector
- title rule
- detail URL rule
- cover URL rule
- pagination pattern

Example:

```json
{
  "exploreUrl": "分类::/category/list_1_{{page}}.html",
  "ruleExplore": {
    "bookList": "ul.pic.pic1 li",
    "name": "a@title",
    "bookUrl": "a@href",
    "coverUrl": "img@src"
  }
}
```

Validate in Legado discovery view.

## 4. Search Module

If the site supports search, inspect GET/POST form behavior and response list.

Common fields:

```json
{
  "searchUrl": "/search?keyword={{key}}&page={{page}}",
  "ruleSearch": {
    "bookList": ".result-item",
    "name": ".title@text",
    "author": ".author@text",
    "bookUrl": "a@href",
    "coverUrl": "img@src",
    "lastChapter": ".latest@text"
  }
}
```

If the site lacks search, omit `searchUrl` and `ruleSearch`; rely on discovery.

## 5. Detail Module

Inspect a detail page and extract:

- name
- author
- cover
- intro
- latest chapter
- toc URL

Example:

```json
{
  "ruleBookInfo": {
    "name": "h1@text",
    "author": ".author@text##作者：",
    "coverUrl": ".cover img@src",
    "intro": ".intro@text",
    "tocUrl": "{{baseUrl}}"
  }
}
```

Validate detail display in Legado.

## 6. Toc Module

For normal chapter lists:

```json
{
  "ruleToc": {
    "chapterList": "#list dd",
    "chapterName": "a@text",
    "chapterUrl": "a@href"
  }
}
```

For single work with multiple image pages, use JS to generate chapter/page entries:

```json
{
  "ruleToc": {
    "chapterList": "@js:\nvar html = java.ajax(baseUrl);\nvar match = html.match(/共(\\d+)页/);\nvar total = match ? parseInt(match[1]) : 1;\nvar base = baseUrl.replace(/\\/index(_\\d+)?\\.html$/, '/');\nvar list = [];\nfor (var i = 1; i <= total; i++) {\n  list.push({ name: '第' + i + '页', url: i === 1 ? base + 'index.html' : base + 'index_' + i + '.html' });\n}\nlist;",
    "chapterName": "name",
    "chapterUrl": "url"
  }
}
```

Validate chapter count and order.

## 7. Content Module

For text:

```json
{
  "ruleContent": {
    "content": "#content@html",
    "replaceRegex": "广告正则##"
  }
}
```

For image URLs with normal image suffixes:

```json
{
  "ruleContent": {
    "content": "#imgString img@src",
    "imageStyle": "FULL"
  }
}
```

For image URLs with misleading suffixes such as `.zip`, keep `bookSourceType: 0` and return HTML:

```json
{
  "ruleContent": {
    "content": "<js>\nvar imgs = result.match(/<img[^>]+>/g);\nimgs && imgs.length > 0 ? imgs[0] : '';\n</js>"
  }
}
```

Validate one normal chapter and one edge chapter.

## 8. Final Delivery

Return the full JSON array or object matching the user's target import style. Include:

- what was verified
- what still needs user-side validation
- known fragile selectors
- encoding or anti-bot notes
