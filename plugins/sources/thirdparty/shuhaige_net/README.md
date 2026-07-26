# 书海阁小说网

- Plugin ID: `shuhaige_net`
- Domain: `shuhaige.net`
- Base URL: `https://www.shuhaige.net`
- Source seed: so-novel `shuhaige.net`
- Auth: none
- Content: free
- Proxy/browser: not required for fixture smoke

## 链路

- 搜索：`POST /search.html`，字段 `searchkey` + `searchtype=all`。
- 详情：`/{book_id}/`，使用 `og:*` meta 与 `#info` 解析。
- 目录：详情页同 URL，单页完整目录（示例 2451 章）。
- 正文：`/{book_id}/{chapter_id}.html`，内容在 `.content` / `#content`。

## 现场校对补充

- 主链路仍是 HTML；无稳定 API。
- 搜索无命中时可能返回空壳或泛推荐页面，插件只在书名命中后返回结果。
- 当前实网存在短时频率限制：连续探测后搜索可能返回“找不到您要查找的数据，请稍后重试”，详情/目录也可能超时；fixture 与早期探针保留真实证据。
- `m.shuhaige.net` 搜索可用但手机页解析规则未适配；`m.shuhaige.tw` 搜索字段/书 ID 均不互通，不作为镜像回退。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `smoke/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/shuhaige_net
python -m app.source_plugins.smoke ../plugins/sources/thirdparty/shuhaige_net
```
