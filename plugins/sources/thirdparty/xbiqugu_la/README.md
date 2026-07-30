# 香书小说

- Plugin ID: `xbiqugu_la`
- Domain: `xbiqugu.la`
- Base URL: `http://www.xbiqugu.la`
- Source seed: so-novel `xbiqugu.la`
- Auth: none
- Content: free/unknown
- Proxy/browser: not required for fixture smoke

## 2026-07-28 现场校对

- 目录分页已改为跟随真实下一页并对已访问页面去重，不再以固定页数截断。
- 当前测试环境在 TLS 握手阶段失败，实时闭环未评估；这不等同于解析器失效。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `smoke/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/xbiqugu_la
```
