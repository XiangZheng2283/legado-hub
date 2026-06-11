# 69书吧

- ID: `69shuba_com`
- Domains: `69shuba.com`, `69shuba.cx`
- Capabilities: `search`, `detail`, `toc`, `chapter`
- Proxy/browser: runtime proxy may be required. Current live site returns Cloudflare verification even with proxy and browser impersonation.
- Current status: parser rules are implemented from archived Reading source. Manual Cloudflare verification is no longer part of this plugin path; blocked pages are reported as bypass-required source failures.
- Domain fallback: the plugin actively tries `www.69shuba.com` and `www.69shuba.cx`. Current live evidence shows both domains are challenged by Cloudflare from this environment.
- Related site: `https://69shuba.tw/` currently returns an Aegis browser verification page to non-browser requests. It should not be mixed into this plugin unless its post-verification DOM is proven compatible; if it differs, create a separate `69shuba_tw` plugin.
- Search note: native site search is intentionally not used because it triggers Cloudflare. Search uses the Source Access Bridge search-provider capability with DDGS, Bing HTML, and Google HTML providers declared by the plugin.
- Explore note: ordinary mirror sources do not expose ranking/category capabilities. Future aggregate rankings should use official/licensed sources only.
- June 10, 2026 re-check: detail/toc can still be read in some runtime paths, but chapter pages continue to return a Cloudflare challenge in direct browser/network probes from this environment. No stable正文 API was confirmed in this pass.



