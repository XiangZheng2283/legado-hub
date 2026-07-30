# 东滩小说

- Plugin ID: `dongtanxs_com`
- Domain: `dongtanxs.com`
- Base URL: `http://www.dongtanxs.com`
- Source seed: so-novel `dongtanxs.com`
- Auth: none
- Content: free

现场补充：

- 搜索与 explore fallback 已保留 trace，便于区分空结果与站点失败。
- 搜索结果会补详情字段，避免阅读端列表缺作者/最新章节。
- 作者字段已统一去掉 `作者：` 前缀；2026-07-28 真实闭环通过，目录 2463 章。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `smoke/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/dongtanxs_com
```
