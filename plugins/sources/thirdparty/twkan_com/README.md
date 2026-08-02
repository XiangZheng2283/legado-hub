# 台灣小說網

- ID: `twkan_com`
- Domains: `twkan.com`
- Capabilities: `search`, `detail`, `toc`, `chapter`
- Proxy/browser: 直连优先、失败后由宿主按策略回退代理；插件请求统一走 `ctx.access.*`。
- Source reference: live `twkan.com` inspection.
- Explore note: ordinary mirror sources do not expose ranking/category capabilities. Future aggregate rankings should use official/licensed sources only.

## 2026-07-28 现场校对

- 历史真实抓取曾完成 `天命之上` 985 章目录，其中保存正文 483 章。
- 本轮已获取真实搜索、详情、985 章 AJAX 完整目录和正文响应。
- Cloudflare 挑战由宿主统一处理：浏览器完成验证并回灌同域 Cookie，然后重试原 stealth 请求；不借用其他站点正文。
- 搜索改为 DDGS/Bing/Google provider 优先，索引结果不再逐条预读详情；站内 POST 仅在索引无结果时后备。
- 2026-07-31 实网复核：搜索命中、详情成功、目录 665 章、正文成功；Browser 深层页使完整四段约 92 秒，功能可用但偏慢。

## 2026-07-31 水印采样

- 排行榜三本书的样本中均出现独立整行 `GOOGLE搜索TWKAN`；另有两本书出现
  `台湾小说网→花体 twkan.com` 域名提示。
- 两类短语均带唯一站点标识和明确边界，已通过插件级 `adPatterns` 精确删除；
  不匹配普通的 Google 搜索描述、正文中的 `TWKAN` 单词或不带箭头的站名。
