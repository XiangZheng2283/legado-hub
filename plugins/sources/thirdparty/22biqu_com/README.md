# 笔趣阁22

- Plugin ID: `22biqu_com`
- Domain: `22biqu.com`
- Base URL: `https://www.22biqu.com`
- Source seed: so-novel `22biqu.com`
- Auth: none
- Content: free/unknown
- Proxy/browser: not required for fixture smoke

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `tests/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/22biqu_com
```
