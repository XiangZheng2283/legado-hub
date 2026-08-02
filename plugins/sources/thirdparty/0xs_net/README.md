# 零点小说

- Plugin ID: `0xs_net`
- Domain: `0xs.net`
- Base URL: `https://www.0xs.net`
- Source seed: so-novel `0xs.net`
- Auth: none
- Content: free

## 当前实现

- 搜索使用桌面站 `/search.html?kw=`，不再经过会丢失参数的移动站跳转。
- 详情页提供 `/la_<分类>/<书籍>.html` 完整目录；目录请求携带书籍页 Referer，避免源站返回伪 200 错误页。
- 正文请求携带目录页 Referer，并合并页面 `.content`、脚本 Base64 `p_key` 与同章后续分页。
- 分页导航自然结束或进入下一章后移除页间“本章未完”提示；翻页循环或超过上限时保留提示。
- 2026-07-31 实网复核：搜索 20 条；《凡人修仙传》完整目录 2564 章；首章正文三页可读取。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `smoke/fixtures/`.

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\validate_source_plugin.py --plugin ..\plugins\sources\thirdparty\0xs_net
```
