# Browser Bridge Architecture

## Purpose

LegadoHub Browser Bridge is the backend-owned browser capability layer for
special source plugins. It gives source plugins controlled access to realistic
HTTP, stealth HTTP, Browserless-backed page rendering, search-engine lookup,
challenge sessions, long-lived profiles, cookies, network capture, DOM
snapshots, and session status.

Source plugins describe which capability they need. They do not control browser
lifecycle, concurrency, proxy binding, global retries, profile directories, or
cookie persistence.

## Runtime Choice

The selected browser runtime substrate is self-hosted Browserless in Docker.
LegadoHub connects to Browserless through Playwright-compatible WebSocket
endpoints and keeps business state in the backend:

- profile identity and storage path
- cookie and storage snapshots
- challenge session status
- Console and aggregate-source callback URLs
- retry handoff for original source operations

LegadoHub does not use a browser extension as the primary runtime path because
the project must work in Docker deployments.

## Configuration

Browser Bridge reads these environment variables:

```text
LEGADOHUB_BROWSERLESS_WS
LEGADOHUB_BROWSERLESS_TOKEN
LEGADOHUB_BROWSER_PUBLIC_BASE_URL
LEGADOHUB_BROWSER_PROFILE_ROOT
LEGADOHUB_BROWSER_CONNECT_TIMEOUT_MS
LEGADOHUB_BROWSER_ACTION_TIMEOUT_MS
```

Defaults:

```text
provider: browserless
profileRoot: backend/data/browser_profiles
connectTimeoutMs: 5000
actionTimeoutMs: 90000
```

If `LEGADOHUB_BROWSERLESS_WS` is empty, Browser Bridge is considered
unconfigured. The backend must still start, and ordinary HTTP source plugins
must continue to work. Browser-dependent actions should return a structured
unavailable result instead of failing opaque runtime startup.

## Profile Identity

Browser profiles are long-lived and bound to:

```text
pluginId + domainProfile + proxyProfile
```

This keeps Cloudflare and similar browser state aligned with the source,
site-family domain, and proxy/IP profile that produced it. Profile ids are
stable, sanitized, and include a short hash of the original tuple to avoid
collisions.

Example:

```text
69shuba_com-primary-<hash>-proxy-a
```

For Browserless-backed Playwright sessions, LegadoHub persists Playwright
`storage_state` under the profile directory. This captures cookies and storage
state that can be reused on later Browserless sessions without requiring a
browser extension or local desktop browser.

## Capability Surface

The target capability surface is:

```text
http.fetch
http.stealthFetch
browser.fetch
browser.profile
browser.cookies
browser.searchEngine
challenge.attempt
challenge.session
challenge.open
challenge.callback
challenge.retry
network.capture
dom.snapshot
session.status
```

The current implementation has established the configuration/profile identity
foundation and central no-API search-engine parsing. `ctx.browser.search_engine`
routes DuckDuckGo/Bing HTML result pages through Browser Bridge helpers and
returns normalized `SearchEngineHit` objects. Source plugins map those hits into
site-specific search results, but they should not duplicate search-engine
redirect parsing.

Browserless connection support is implemented through a Playwright adapter that
connects to a configured Browserless WebSocket endpoint. Unified challenge
session migration and richer callback-driven retry are tracked in
`docs/superpowers/plans/2026-06-08-stage-5-browserless-browser-bridge.md`.

## Challenge Session Principle

Console verification and aggregate-source verification are the same capability.
Both create or reference one challenge session and one local open URL. The only
difference is who opens the URL:

- Console: the web backend opens or navigates to the challenge session URL.
- Aggregate source: Reading receives the local URL and opens it through the
  user's device/browser.

After verification, Browser Bridge calls back into the same session, saves
profile/cookie state, and retries the original resumable source operation.

The unified local entry points are:

```text
GET  /api/browser/challenges
GET  /api/browser/challenges/{sessionId}
GET  /api/browser/challenges/{sessionId}/open
POST /api/browser/challenges/{sessionId}/callback
POST /api/browser/challenges/{sessionId}/cookies
```

Legacy Console and aggregate-specific challenge endpoints may remain as aliases,
but generated clients should prefer the unified `/api/browser` entry point.
