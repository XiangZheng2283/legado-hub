# 零点小说

- Plugin ID: `0xs_net`
- Domain: `0xs.net`
- Base URL: `https://www.0xs.net`
- Source seed: so-novel `0xs.net`
- Auth: none
- Content: free

现场补充：

- 该站限流明显，搜索失败时已补源内 fallback，并保留 trace 供后续 live 审查。
- 搜索结果会做同源详情补字段，优先补作者、最新章节、分类和更新时间。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `tests/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/0xs_net
```
