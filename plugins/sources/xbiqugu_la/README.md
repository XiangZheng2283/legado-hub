# 香书小说

- Plugin ID: `xbiqugu_la`
- Domain: `xbiqugu.la`
- Base URL: `http://www.xbiqugu.la`
- Source seed: so-novel `xbiqugu.la`
- Auth: none
- Content: free/unknown
- Proxy/browser: not required for fixture smoke

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `tests/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/xbiqugu_la
```
