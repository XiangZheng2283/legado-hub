# Source Access Bridge Architecture

## Purpose

LegadoHub Source Access Bridge is the backend-owned source access capability
layer for special source plugins. It gives source plugins controlled access to
HTTP, stealth HTTP, TLS impersonation, search providers, Chromium-backed page
rendering, optional remote browsers, feeds, APIs, local files, long-lived
profiles, cookies, network capture, DOM snapshots, and session status.

Source plugins describe which capability they need. They do not control browser
lifecycle, concurrency, proxy binding, global retries, profile directories, or
cookie persistence.

## Runtime Choice

The default browser runtime substrate is Playwright's bundled Chromium. This
keeps the deployment to one backend container while still working on Windows,
Linux, and other Playwright-supported platforms. Browserless remains available
as an optional remote runtime when an operator explicitly chooses a split
browser service.

LegadoHub owns the browser lifecycle and keeps business state in the backend:

- profile identity and storage path
- cookie and storage snapshots
- challenge diagnostics
- source capability routing decisions

LegadoHub does not use a browser extension as the primary runtime path because
the project must work in Docker deployments and inside local reading clients.

## Configuration

Source Access Bridge reads these environment variables:

```text
LEGADOHUB_BROWSERLESS_WS
LEGADOHUB_BROWSERLESS_TOKEN
LEGADOHUB_BROWSER_PROVIDER
LEGADOHUB_BROWSER_ENABLED
LEGADOHUB_BROWSER_PUBLIC_BASE_URL
LEGADOHUB_BROWSER_PROFILE_ROOT
LEGADOHUB_BROWSER_CONNECT_TIMEOUT_MS
LEGADOHUB_BROWSER_ACTION_TIMEOUT_MS
```

Defaults:

```text
provider: chromium
enabled: true
profileRoot: backend/data/browser_profiles
connectTimeoutMs: 5000
actionTimeoutMs: 90000
```

Set `LEGADOHUB_BROWSER_ENABLED=0` to disable Source Access Bridge. If
`LEGADOHUB_BROWSER_PROVIDER=browserless`, `LEGADOHUB_BROWSERLESS_WS` must be
configured; otherwise browser-dependent actions return a structured unavailable
result instead of failing opaque runtime startup.

Single-container Docker Compose example:

```yaml
services:
  legadohub:
    build:
      context: .
    ports:
      - "8765:8765"
    environment:
      - LEGADOHUB_BROWSER_PROVIDER=chromium
      - LEGADOHUB_BROWSER_ENABLED=1
    volumes:
      - ./backend/data:/app/backend/data
```

Example backend environment:

```text
LEGADOHUB_BROWSER_PROVIDER=chromium
LEGADOHUB_BROWSER_ENABLED=1
LEGADOHUB_BROWSER_PUBLIC_BASE_URL=http://192.168.31.10:8765
```

## Profile Identity

Browser profiles are long-lived and bound to:

```text
pluginId + domainProfile + proxyProfile
```

This keeps browser storage aligned with the source, site-family domain, and
proxy/IP profile that produced it. Profile ids are stable, sanitized, and
include a short hash of the original tuple to avoid collisions.

Example:

```text
69shuba_com-primary-<hash>-proxy-a
```

For Playwright Chromium sessions, LegadoHub persists Playwright
`storage_state` under the profile directory. This captures cookies and storage
state that can be reused on later browser sessions without requiring a
browser extension or local desktop browser.

## Capability Surface

The target capability surface is:

```text
http.fetch
http.stealthFetch
http.tlsImpersonate
search.provider
browser.fetch
browser.headless
browser.remote
browser.profile
browser.cookies
api.fetch
feed.fetch
localFile.read
challenge.detect
network.capture
dom.snapshot
```

The implementation includes configuration/profile identity, Browserless
Playwright compatibility, local Playwright Chromium, centralized DDGS/Bing/Google
search providers, controlled `ctx.access` methods, DOM/network normalization
helpers, and challenge diagnostics. `ctx.access.search_provider` returns
normalized `SearchProviderHit` objects. Source plugins map those hits into
site-specific search results, but they should not duplicate search-provider
redirect parsing.

Plugin runtime contexts are created with a backend-owned access client. Plugins
use `ctx.access.http_fetch_text`, `ctx.access.stealth_fetch_text`,
`ctx.access.fetch`, and `ctx.access.search_provider`. The scheduler still owns
concurrency, timeout, proxy, cookie repository, and browser profile policy;
plugins request capabilities but do not create browser clients or sessions
themselves.

## Challenge Bypass Principle

Manual Cloudflare/browser verification is no longer part of the runtime
contract. Multi-source aggregation should not ask users to solve challenges per
source. When runtime detects `CLOUDFLARE_REQUIRED` or `BROWSER_REQUIRED`, it
records a diagnostic with `bypassRequired` and skips that source for the current
request.

Browser simulation remains a backend capability for maintainable bypass
strategies, rendering, search-provider access, and future controlled fetch
flows. It must not expose verification pages, callback sessions, or Cookie
round-trips to Reading/Legado clients.


