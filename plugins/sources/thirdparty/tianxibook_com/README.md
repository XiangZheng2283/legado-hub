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
- 目录分页已移除固定页数上限，以真实下一页和新增章节决定终止。
- 2026-07-28 现场搜索无结果，因此实时读取闭环未评估；这不代表已确认解析失效。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `smoke/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/tianxibook_com
```
