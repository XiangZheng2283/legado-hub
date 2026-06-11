# Stage 5 Browserless Browser Bridge Verification

Date: 2026-06-08

## Scope

Goal: build LegadoHub Browser Bridge around Browserless Docker + Playwright,
fixed source access strategies, long-lived profile/cookie state, and one shared
CF/browser challenge session model for Console and aggregate-source clients.

## Implemented Evidence

- Browser Bridge typed models, config, profile store, Playwright Browserless
  client, centralized search-engine parsing, DOM/network helpers, and manual
  challenge handoff compatibility exist under `backend/app/services/browser_bridge/`.
- Plugin scheduler contexts now receive a backend-owned `BrowserBridgeClient`;
  plugins access HTTP, stealth HTTP, Browserless page fetch, and search-engine
  lookup through `ctx.browser` instead of constructing browser clients.
- The Playwright adapter now records elapsed time, detects Cloudflare/browser
  challenge pages, captures request/response network entries, produces compact
  DOM snapshots when requested, supports non-GET fetch bodies, and writes
  Playwright `storage_state` back to long-lived source profiles.
- Unified Browser Challenge endpoints exist under `/api/browser`.
- Console and aggregate aliases use the same BrowserChallengeService session
  store and expose the same session id.
- Source metadata supports `accessStrategy` and `searchEngine`.
- `69shuba_com` declares:
  - `search: search_engine`
  - `detail: stealth_http`
  - `toc: stealth_http`
  - `chapter: stealth_http`
- Browserless startup assets exist:
  - `docker-compose.browserless.yml`
  - `.env.example`
  - `start.bat` readiness output

## Commands Run

```powershell
docker --version
# failed: docker command is not installed / not on PATH in this environment

docker compose version
# failed: docker command is not installed / not on PATH in this environment
```

Remote Browserless host verification:

```powershell
Test-NetConnection -ComputerName 192.168.31.161 -Port 3000 -InformationLevel Detailed
# TcpTestSucceeded: True
```

Remote Docker evidence:

```text
Docker version 29.2.1
Docker Compose version v5.0.2
legadohub-browserless Up, 0.0.0.0:3000->3000/tcp
Browserless route: /chromium/playwright
```

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\source_plugins backend\tests\test_realtime_search_api.py backend\tests\test_aggregate_source_plugin_runtime.py backend\tests\test_browser_challenge.py backend\tests\test_browser_bridge_config.py backend\tests\test_browser_bridge_profiles.py backend\tests\test_browser_bridge_client.py backend\tests\test_browser_bridge_challenge.py backend\tests\test_browser_bridge_search_engine.py backend\tests\test_browser_bridge_dom.py -q
# 141 passed, 1 warning
```

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
# 240 passed, 1 warning
```

```powershell
cd frontend
npm run build
# built successfully
```

```powershell
.\.venv\Scripts\python.exe -m py_compile backend\app\services\browser_bridge\challenge.py backend\app\services\browser_bridge\dom.py backend\app\api\browser.py backend\app\api\console.py backend\app\api\legado.py backend\app\services\browser_challenge.py
# passed
```

```powershell
git diff --check
# no whitespace errors; Git reports expected line-ending conversion warnings
# for backend/config/source_pool.json and start.bat
```

```powershell
rg -n "/admin|api/admin|demo_|engine-jvm|LegadoEngineRunner|app\.legado_engine|app\.engine" backend frontend plugins docs -S -g "!docs/archive/**"
# no active runtime dependencies; matches are documentation, tests asserting old routes stay 404,
# or validation scripts rejecting legacy names.
```

## Live Browserless Fetch Evidence

Environment:

```powershell
$env:LEGADOHUB_BROWSERLESS_WS='ws://192.168.31.161:3000/chromium/playwright'
$env:LEGADOHUB_BROWSERLESS_TOKEN='legadohub-local'
```

`BrowserBridgeClient.fetch` against `https://example.com` returned:

```json
{
  "ok": true,
  "finalUrl": "https://example.com/",
  "title": "Example Domain",
  "htmlLength": 528,
  "networkCount": 1,
  "domTitle": "Example Domain",
  "domTextHasExample": true,
  "challenge": {
    "detected": false,
    "kind": "",
    "message": "",
    "url": "https://example.com/"
  },
  "profileId": "browser_bridge_live-example-default",
  "profileStored": true,
  "error": ""
}
```

This proves that the Browserless Playwright adapter connects to Browserless,
captures DOM/network data, detects no challenge on normal pages, and writes
profile storage state under the Browser Bridge profile root.

## Live Challenge Attempt Evidence

With the same Browserless endpoint:

- Earlier prototype evidence showed a Browserless attempt could pass a normal
  page such as `https://example.com`; active runtime no longer relies on this
  path for CF verification.
- A `69shuba_com` challenge session pointed at
  `https://www.69shuba.com/newhot_0_1_1.htm` returned
  `status: manual_required`, `errorCode: challenge_still_present`, and stored
  session status `manual_required`.
- The 69shuba result kept the same unified actions:
  - `/api/browser/challenges/{sessionId}/open`
  - `/api/browser/challenges/{sessionId}/callback`
  - `/api/browser/challenges/{sessionId}/cookies`
  - `/api/browser/challenges/{sessionId}/cookies`
  - Console and aggregate aliases for the same session id.

This proves Browser Bridge can create the shared manual verification callback
when the challenge remains.

## Live 69shuba Search/Challenge Evidence

Command:

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\run_live_acceptance_matrix.py --plugin 69shuba_com --keyword 剑宗外门 --clear-cookies --json-out ..\docs\verification\stage-5-69shuba-live.json
```

Result:

- `passed`: false
- diagnostics:
  - `explore`: `BROWSER_REQUIRED`
  - `runtime`: `CLOUDFLARE_REQUIRED`
- The result includes an actionable unified challenge session:
  - `actions.open`: `/api/browser/challenges/{sessionId}/open`
  - `actions.callback`: `/api/browser/challenges/{sessionId}/callback`
  - `actions.submitCookies`: `/api/browser/challenges/{sessionId}/cookies`
  - `actions.submitCookies`: `/api/browser/challenges/{sessionId}/cookies`

This proves that when live 69shuba search is blocked without valid clearance
cookies, the runtime returns a unified challenge handoff instead of an opaque
timeout-only failure.

## Live 69shuba Detail/Toc/Chapter Evidence

Direct known detail target:

```text
https://www.69shuba.com/book/90442.htm
```

Inline runtime check result:

```json
{
  "detailName": "霍格沃茨的学习面板",
  "author": "林曦遇鹿",
  "tocUrl": "https://www.69shuba.com/book/90442/",
  "tocCount": 569,
  "firstChapter": "第1章 1：伦敦孤儿",
  "firstChapterUrl": "https://www.69shuba.com/txt/90442/40755363",
  "chapterTitle": "第1章 1：伦敦孤儿",
  "contentLength": 2360
}
```

The chapter content sample was readable Chinese prose after plugin cleaning,
not symbol noise. This validates the fixed strategy split: search may require
search-engine/challenge flow, while detail/toc/chapter can be read by controlled
HTTP/stealth HTTP once the book URL is known.

## Completion Notes

- Browserless Docker was verified on a reachable LAN host because local Docker
  is unavailable on this workstation.
- `backend/data/browser_profiles/` is ignored because it contains runtime
  Browser Bridge profile state.
- `69shuba_com` no longer declares the legacy `browser.searchFallback`; runtime
  search strategy is driven by `accessStrategy.search: search_engine`.
