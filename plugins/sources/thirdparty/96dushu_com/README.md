# 96读书

- Plugin ID: `96dushu_com`
- Domain: `96dushu.com`
- Base URL: `https://www.96dushu.com`
- Source seed: so-novel `96dushu.com`
- Auth: none
- Content: free

现场补充：

- 正文章节里存在 `qsbs.bb(...)` base64 注入，正文解析器已做站内解码。
- 源站搜索受 Cloudflare 保护，搜索通过 Source Access Bridge 的 Bing/Google provider 发现书籍 URL。
- 搜索命中后仍由本插件读取源站详情，并尽力补全作者、封面、简介和最新章节。
- 搜索提供器遵循宿主代理策略，不再强制绕过已配置代理。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `smoke/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/96dushu_com
```
