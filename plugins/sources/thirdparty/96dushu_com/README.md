# 96读书

- Plugin ID: `96dushu_com`
- Domain: `96dushu.com`
- Base URL: `https://www.96dushu.com`
- Source seed: so-novel `96dushu.com`
- Auth: none
- Content: free

现场补充：

- 正文章节里存在 `qsbs.bb(...)` base64 注入，正文解析器已做站内解码。
- 搜索失败时保留 trace，并会在返回结果前做同源详情补字段。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `tests/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/96dushu_com
```
