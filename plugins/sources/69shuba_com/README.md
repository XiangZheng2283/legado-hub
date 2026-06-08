# 69书吧

- ID: `69shuba_com`
- Domains: `69shuba.com`, `69shuba.cx`
- Capabilities: `search`, `detail`, `toc`, `chapter`, `explore`
- Proxy/browser: runtime proxy required. Current live site returns Cloudflare verification even with proxy and browser impersonation.
- Current status: parser rules are implemented from archived Reading source. Runtime now exposes a controlled browser challenge flow, Cookie import, and post-Cookie live retry.
- Domain fallback: the plugin actively tries `www.69shuba.com` and `www.69shuba.cx`. Current live evidence shows both domains are challenged by Cloudflare from this environment.
- Related site: `https://69shuba.tw/` currently returns an Aegis browser verification page to non-browser requests. It should not be mixed into this plugin unless its post-verification DOM is proven compatible; if it differs, create a separate `69shuba_tw` plugin.
- Search note: Google `site:www.69shuba.com <book>` can sometimes help discover direct book URLs when the native site search is blocked, but Google result pages are not stable enough to be the default backend search path. Treat it as a future optional fallback or manual diagnostic path.
