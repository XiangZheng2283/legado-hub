# 笔趣阁365

- Plugin ID: `biquge365_net`
- Domain: `biquge365.net`
- Base URL: `https://www.biquge365.net`
- Source seed: so-novel `biquge365.net`
- Auth: none
- Content: free/unknown
- Proxy/browser: not required for fixture smoke

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `tests/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/biquge365_net
```
