# 69書吧繁體

- Plugin ID: `69shuba_tw`
- Domain: `69shuba.tw`
- Capabilities: `search`, `detail`, `toc`, `chapter`
- Auth: none
- Content: free
- Access: proxy and browser required because the site serves an Aegis verification page to direct requests

The plugin uses the host Source Access Bridge for browser rendering. It does
not own proxy, retry, timeout, or browser lifecycle policy.

## 2026-07-28 现场校对

- `天命之上` 搜索、详情、865 章目录及第 4 章正文闭环通过。
- 删除插件内自重试，目录按真实下一页终止，章节标题会清理尾部 `(1 / 1)` 分页标记。
- 首个目录项正文只有 33 字，属于短章节边界，不能据此判定整个插件失效。
- fixture 使用 2026-07-28 真实页面，保存全部 9 个目录分页并精确断言 865 章。

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/69shuba_tw
```
