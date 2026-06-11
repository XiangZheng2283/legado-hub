# 笔尖中文

- Plugin ID: `xbiquzw_net`
- Domain: `xbiquzw.net`
- Runtime base URL: `https://www.xbiqugu.com`
- Source seed: so-novel `xbiquzw.net`
- Auth: none
- Content: free/unknown
- Proxy/browser: not required for fixture smoke

当前说明：

- 现场重新校对后，`xbiquzw.net` 主域在当前环境下不可稳定访问，证据包含证书不匹配、握手失败与超时。
- 现插件运行时实际使用的是结构兼容的 `xbiqugu.com` 镜像，以保证搜索、详情、目录、正文链路可用。
- 后续若重新发现稳定的 `xbiquzw` 真站，应单独重新抓取并恢复真实域，不应直接按“同框架”假设切回。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `tests/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/xbiquzw_net
```
