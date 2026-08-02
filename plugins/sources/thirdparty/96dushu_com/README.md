# 96读书

- Plugin ID: `96dushu_com`
- Domain: `96dushu.com`
- Base URL: `https://www.96dushu.com`
- Source seed: so-novel `96dushu.com`
- Auth: none
- Content: free

现场补充：

- 正文章节里存在 `qsbs.bb(...)` base64 注入，正文解析器已做站内解码。
- 源站搜索受 Cloudflare 保护，搜索通过 Source Access Bridge 的 DDGS/Bing/Google provider 发现书籍 URL。
- 搜索阶段只返回索引结果，不预读详情；用户选中后再读取源站详情、目录和正文。
- 源站页面使用与共享浏览器池一致的 Chrome 请求头，HTTP 失败时复用浏览器会话；代理策略仍由宿主管理。
- 2026-07-31 宿主实测：搜索 7 条；《红尘尸仙》目录 493 章；首章正文 2855 字。普通 HTTP 会被当前日本出口的 Managed Challenge 拦截，插件通过宿主 Chrome 指纹请求链路成功读取；若源站升级为交互验证码，仍需更换可用出口。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `smoke/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/96dushu_com
```
