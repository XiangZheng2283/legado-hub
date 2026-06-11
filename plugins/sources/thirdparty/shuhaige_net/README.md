# 书海阁小说网

- Plugin ID: `shuhaige_net`
- Domain: `shuhaige.net`
- Base URL: `https://www.shuhaige.net`
- Source seed: so-novel `shuhaige.net`
- Auth: none
- Content: free/unknown
- Proxy/browser: not required for fixture smoke

现场校对补充：

- 目前未确认到稳定的目录/正文 API，主链路仍是 HTML。
- 搜索页在无命中时可能只返回空壳页面或泛推荐内容。插件不能把推荐项
  当成有效搜索结果，必须有明确书名命中后再返回。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `tests/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/shuhaige_net
```
