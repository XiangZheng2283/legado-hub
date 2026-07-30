# 零点小说

- Plugin ID: `0xs_net`
- Domain: `0xs.net`
- Base URL: `https://m.0xs.net`
- Source seed: so-novel `0xs.net`
- Auth: none
- Content: free

## 当前实现

- 搜索使用移动站 `/search?kw=`，桌面站会丢失查询参数。
- 目录从 `/la_<分类>/<书籍>/1..N` 逐页读取；读取前先建立书籍详情会话。
- 正文合并页面 `.content`、脚本中的 Base64 `p_key` 以及同章后续分页。
- 普通路径使用 HTTP；首次返回 403 时用一次共享浏览器池建立站点 cookie，再重试 HTTP。
- 2026-07-28 实网曾取得搜索 20 条及书籍“青山”页面；连续探测后当前出口被临时 403，完整三段验收仍待限频解除后复核。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `smoke/fixtures/`.

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\validate_source_plugin.py --plugin ..\plugins\sources\thirdparty\0xs_net
```
