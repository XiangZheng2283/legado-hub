# 速读谷

- Plugin ID: `sudugu_org`
- Domain: `sudugu.org`
- Base URL: `https://www.sudugu.org`
- Backup URL: `https://www.sudugu.co`
- Source seed: so-novel `sudugu.org`
- Auth: none
- Content: free

现场补充：

- `.org` 保持主链路；仅当主站搜索无结果或失败时，才使用 `.co` 的独立搜索协议发现备用书籍 URL。
- 搜索失败时会保留 trace，并对返回项做同源详情补字段。
- 作者字段已清理 `作者：` 前缀；2026-07-28 真实闭环通过，目录 2512 章。
- 目录分页按真实下一页终止，不再使用固定页数上限。
- 2026-07-31 复核：`.org` 搜索、详情、分页目录和正文均可用；`.co` 搜索、详情、目录可用，但部分旧书正文为空，因此不替代主链路。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `smoke/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/sudugu_org
```
