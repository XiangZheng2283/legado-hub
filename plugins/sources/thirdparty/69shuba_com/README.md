# 69书吧

- ID: `69shuba_com`
- Domains: `69shuba.com`, `69shuba.cx`
- Capabilities: `search`, `detail`, `toc`, `chapter`
- Proxy/browser: runtime proxy is required；Cloudflare 会按请求动态放行或阻断，插件通过宿主 Access Bridge 管理会话。
- Current status: 解析规则已实现；挑战页会明确返回 bypass-required，不会作为正文处理。
- Domain fallback: 插件会依次尝试 `www.69shuba.com` 和 `www.69shuba.cx`。
- Related site: `https://69shuba.tw/` currently returns an Aegis browser verification page to non-browser requests. It should not be mixed into this plugin unless its post-verification DOM is proven compatible; if it differs, create a separate `69shuba_tw` plugin.
- Search note: native site search is intentionally not used because it triggers Cloudflare. Search uses the Source Access Bridge search-provider capability with DDGS, Bing HTML, and Google HTML providers declared by the plugin.
- 搜索提供器命中会在详情补全后按真实书名过滤，避免“天命之上”误返回“高天之上”。
- Explore note: ordinary mirror sources do not expose ranking/category capabilities. Future aggregate rankings should use official/licensed sources only.
- 2026-07-27 真实校对：`天命之上` 目录 866 章、`凡人修仙传` 目录 2562 章；正文请求存在间歇性 Cloudflare 和 HTTP 429，宿主应保持单并发低频调度。
- 2026-07-28 fixture：使用真实搜索提供器命中与 `高天之上` 页面，完整目录 1139 章，第 3 章正文 3254 字符。fixture 不代表站点当日必然可达。

