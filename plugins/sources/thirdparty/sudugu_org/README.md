# 速读谷

- Plugin ID: `sudugu_org`
- Domain: `sudugu.org`
- Base URL: `https://www.sudugu.org`
- Source seed: so-novel `sudugu.org`
- Auth: none
- Content: free

现场补充：

- 该源有代理/限流倾向，建议 live 验收时低并发。
- 搜索失败时会保留 trace，并对返回项做同源详情补字段。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `tests/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/sudugu_org
```
