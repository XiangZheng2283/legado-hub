# 速读谷

- Plugin ID: `sudugu_org`
- Domain: `sudugu.org`
- Base URL: `https://www.sudugu.org`
- Source seed: so-novel `sudugu.org`
- Auth: none
- Content: free

现场补充：

- 该源直连可用，代理策略为自动回退；宿主按单并发、最小间隔 1200 ms 调度。
- 搜索失败时会保留 trace，并对返回项做同源详情补字段。
- 作者字段已清理 `作者：` 前缀；2026-07-28 真实闭环通过，目录 2512 章。
- 目录分页按真实下一页终止，不再使用固定页数上限。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `smoke/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/sudugu_org
```
