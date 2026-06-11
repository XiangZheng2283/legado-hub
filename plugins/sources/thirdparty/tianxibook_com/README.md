# 新天禧小说

- Plugin ID: `tianxibook_com`
- Domains: `tianxibook.com`, `sososhu.com`
- Base URL: `https://www.tianxibook.com`
- Source seed: so-novel `tianxibook.com`
- Auth: none
- Content: free

现场补充：

- 搜索实际通过 `sososhu.com` 站外聚合入口命中，再回到源站详情/目录链路。
- 搜索结果已统一做绝对 URL 和同源详情补字段。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `tests/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/tianxibook_com
```
