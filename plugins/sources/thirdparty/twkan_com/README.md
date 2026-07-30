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
