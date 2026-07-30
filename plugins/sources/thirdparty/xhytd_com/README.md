# 黄易天地

- Plugin ID: `xhytd_com`
- Domain: `xhytd.com`
- Base URL: `http://wap.xhytd.com`
- Source seed: so-novel `xhytd.com`
- Auth: none
- Content: free

## 当前实现

- 旧 `https://www.xhytd.com/book/...` 路径已失效；当前站点会跳转到移动站。
- 搜索走 `/SearchBook.php?keyword=`，书籍路径为 `/<分片>/<书籍ID>/`。
- 完整目录走 `all.html`，正文读取 `#chaptercontent` 并合并 `_2.html` 等同章分页。
- 2026-07-28 实网验收通过：搜索 100 条、目录 799 章、测试章节正文 1698 字。

## Fixture Smoke

Fixtures cover `detail`, `toc`, and `chapter` under `smoke/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/xhytd_com
```
