# 黄金屋中文

- Plugin ID: `hjwzw_com`
- Domain: `tw.hjwzw.com`
- Base URL: `https://tw.hjwzw.com`
- Auth: none
- Content: free

插件使用站点的搜索页、OpenGraph 详情字段、完整目录页和章节正文页。站点输出繁体中文，所有面向阅读端的文本均由宿主转换为简体中文。

## Fixture Smoke

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/hjwzw_com
python -m app.source_plugins.smoke ../plugins/sources/thirdparty/hjwzw_com --keyword "剑宗外门"
```
