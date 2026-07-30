# 燃文小说网

- Plugin ID: `ranwen8_cc`
- Domain: `ranwen8.cc`
- Base URL: `https://www.ranwen8.cc`
- Source seed: so-novel `ranwen8.cc`
- Auth: none
- Content: free

现场补充：

- 正文章节存在 `qsbs.bb(...)` base64 脚本注入，章节解析器会先解码再清洗。
- 搜索结果已接同源详情补字段，异常会写 trace，不再静默吞掉。
- 目录分页已移除固定页数上限，以已访问页面和新增章节作为终止条件。
- 2026-07-28 现场探针在宿主超时内未完成，实时闭环未评估。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `smoke/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/ranwen8_cc
```
