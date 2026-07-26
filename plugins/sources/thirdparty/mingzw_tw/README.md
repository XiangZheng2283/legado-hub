# 明智屋

- Plugin ID: `mingzw_tw`
- Domain: `tw.mingzw.net`
- Base URL: `https://tw.mingzw.net`
- Auth: none
- Content: free

站点目录采用多栏排版，DOM 顺序不等于阅读顺序。插件按递增章节 ID 还原目录，并将繁体搜索输入和输出统一接入宿主转换能力。

## Fixture Smoke

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/mingzw_tw
python -m app.source_plugins.smoke ../plugins/sources/thirdparty/mingzw_tw --keyword "金榜题名时"
```
