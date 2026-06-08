# 笔尖中文

- Plugin ID: `xbiquzw_net`
- Domain: `xbiquzw.net`
- Base URL: `http://www.xbiquzw.net`
- Source seed: so-novel `xbiquzw.net`
- Auth: none
- Content: free/unknown
- Proxy/browser: not required for fixture smoke

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `tests/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/xbiquzw_net
```
