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

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `tests/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/ranwen8_cc
```
