# 69書吧繁體

- Plugin ID: `69shuba_tw`
- Domain: `69shuba.tw`
- Capabilities: `search`, `detail`, `toc`, `chapter`
- Auth: none
- Content: free
- Access: proxy and browser required because the site serves an Aegis verification page to direct requests

The plugin uses the host Source Access Bridge for browser rendering. It does
not own proxy, retry, timeout, or browser lifecycle policy.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/69shuba_tw
```
