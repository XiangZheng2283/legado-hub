# 笔趣阁365

- Plugin ID: `biquge365_net`
- Domain: `biquge365.net`
- Base URL: `https://www.biquge365.net`
- Source seed: so-novel `biquge365.net`
- Auth: none
- Content: free/unknown
- Proxy/browser: not required for fixture smoke

现场校对补充：

- 目录与正文链路可闭环，但目录分页较深，现场一次 live acceptance 中
  出现过超时。当前更像慢源边界问题，不是已确认的解析失败。
- 目录分页已改为按真实下一页和新增章节终止，不再使用固定页数上限。
- 2026-07-28 闭环探针通过，但搜索命中了只有 4 章的同名书，不能作为完整目录证据。
- 重新抓包未确认到可直接替代目录/正文 HTML 的稳定业务 API；页面里的
  `xhr/fetch` 主要是统计/运行时请求。

## Fixture Smoke

Fixtures cover `search`, `detail`, `toc`, and `chapter` under `smoke/fixtures/`.

```powershell
cd backend
python scripts/validate_source_plugin.py --plugin ../plugins/sources/thirdparty/biquge365_net
```
