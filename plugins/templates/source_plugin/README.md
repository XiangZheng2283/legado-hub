# 示例书源

- Plugin ID: `example_com`
- Domain: `example.com`
- Auth: none
- Content: unknown

Replace fixture files under `tests/fixtures/`, implement `source.py` with `ctx` APIs only, then run:

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/example_com
```
