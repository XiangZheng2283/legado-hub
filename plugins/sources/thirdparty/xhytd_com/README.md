# 黄易天地

- Plugin ID: `xhytd_com`
- Domain: `xhytd.com`
- Base URL: `https://www.xhytd.com`
- Source seed: so-novel `xhytd.com`
- Auth: none
- Content: free

现场补充：

- 站内搜索不稳定，当前正式方案改为 `search_provider` 搜索引擎兜底，再回到源站详情/目录/正文链路。
- 如后续确认站内搜索重新稳定，可再切回站内搜索，但不应影响当前 provider 兜底路径。

## Fixture Smoke

Fixtures cover `detail`, `toc`, and `chapter` under `tests/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/xhytd_com
```
