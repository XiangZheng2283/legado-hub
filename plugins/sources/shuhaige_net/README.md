# 书海阁小说网

- Plugin ID: `shuhaige_net`
- Domain: `shuhaige.net`
- Base URL: `https://www.shuhaige.net`
- Source seed: so-novel `shuhaige.net`
- Auth: none
- Content: free/unknown
- Proxy/browser: not required for fixture smoke

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `tests/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/shuhaige_net
```
