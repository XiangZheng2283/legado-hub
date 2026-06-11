# 小说虎

- Plugin ID: `xiaoshuohu_com`
- Domain: `xiaoshuohu.com`
- Base URL: `https://www.xiaoshuohu.com`
- Source seed: so-novel `xiaoshuohu.com`
- Auth: none
- Content: free

现场补充：

- 站内搜索不稳定，当前正式方案改为 `search_provider` 搜索引擎兜底，再回到源站详情/目录/正文链路。
- 该源正文广告清洗规则比普通镜像更重，后续 live 审查时应重点看正文污染。

## Fixture Smoke

Fixtures cover `detail`, `toc`, and `chapter` under `tests/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/xiaoshuohu_com
```
