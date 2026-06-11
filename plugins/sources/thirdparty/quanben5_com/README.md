# 全本小说网

- Plugin ID: `quanben5_com`
- Domain: `quanben5.com`
- Base URL: `https://www.quanben5.com`
- Source seed: so-novel `quanben5.com`
- Auth: none
- Content: free

现场补充：

- 该源更偏向完本书搜索，实时搜索失败时会回落到 explore 并保留 trace。
- 搜索结果会做同源详情补字段，避免回落时只剩书名和 URL。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `tests/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/quanben5_com
```
