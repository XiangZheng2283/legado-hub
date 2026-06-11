# Stage 5 Browser Bridge Progress Handoff

Date: 2026-06-08

## Current Status

Browser Bridge Stage 5 has been implemented and verified as complete for the
agreed runtime scope:

- Browserless Docker + Playwright runtime path exists.
- Browser Bridge typed request/result models exist.
- Long-lived profile storage path exists and is ignored from git.
- `ctx.browser` exposes controlled HTTP, stealth HTTP, browser fetch, and
  search-engine capabilities.
- Console, Legado aggregate API, and `/api/browser` share one browser challenge
  session model.
- Automatic CF challenge attempts have been removed from the active runtime
  path. Challenge sessions now follow Reading's model: pass the real
  verification URL to Reading/WebView or Console, then save returned cookies.
- `69shuba_com` now uses formal `accessStrategy.search: search_engine` instead
  of the legacy `browser.searchFallback`.

Main documents:

- `docs/architecture/browser-bridge.md`
- `docs/verification/stage-5-browserless-browser-bridge.md`
- `docs/verification/stage-5-69shuba-live.json`

## Verified Evidence

Backend regression:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
# 240 passed, 1 warning
```

Frontend build:

```powershell
cd frontend
npm run build
# built successfully
```

Whitespace check:

```powershell
git diff --check
# no whitespace errors; only expected line-ending conversion warnings
```

Remote Browserless evidence:

```text
Host: 192.168.31.161
Container: legadohub-browserless
Port: 3000
Endpoint: ws://192.168.31.161:3000/chromium/playwright
```

`BrowserBridgeClient.fetch` against `https://example.com` returned:

```json
{
  "ok": true,
  "finalUrl": "https://example.com/",
  "title": "Example Domain",
  "htmlLength": 528,
  "networkCount": 1,
  "domTextHasExample": true,
  "profileStored": true
}
```

Historical Browserless challenge attempt evidence from the earlier Stage 5
prototype:

- `https://example.com` challenge session: `auto_passed`.
- `https://www.69shuba.com/newhot_0_1_1.htm` challenge session:
  `manual_required`, `challenge_still_present`.
- The 69shuba session retained unified `/api/browser/challenges/{sessionId}`
  actions plus Console and Legado aliases.

69shuba known detail/read path:

```json
{
  "detailName": "霍格沃茨的学习面板",
  "author": "林曦遇鹿",
  "tocCount": 569,
  "firstChapter": "第1章 1：伦敦孤儿",
  "firstChapterUrl": "https://www.69shuba.com/txt/90442/40755363",
  "chapterTitle": "第1章 1：伦敦孤儿",
  "contentLength": 2360
}
```

## CF / Reading Source Analysis

Reading's relevant mechanism is not automatic CF bypass. The archived source
shows this flow:

1. `SourceVerificationHelp.getVerificationResult(...)` starts a WebView
   verification flow and waits for user input.
2. `WebViewActivity` calls `AppCookieManager.applyToWebView(url)` before page
   load, injecting stored HTTP cookies into Android WebView.
3. After page finish, `WebViewActivity` reads Android `CookieManager` cookies
   and saves them into `CookieStore`.
4. It detects Cloudflare challenge state with `!!window._cf_chl_opt`; after the
   challenge is no longer present, it saves the verification result and closes.
5. Later HTTP requests call `CookieManager.loadRequest(request)` and attach the
   stored cookies.

Key archive references:

- `app/src/main/java/io/legado/app/help/source/SourceVerificationHelp.kt`
- `app/src/main/java/io/legado/app/ui/browser/WebViewActivity.kt`
- `app/src/main/java/io/legado/app/ui/browser/WebViewModel.kt`
- `app/src/main/java/io/legado/app/help/http/CookieManager.kt`
- `app/src/main/java/io/legado/app/help/http/CookieStore.kt`

## Local Playwright CF Attempt

A temporary headed Playwright test opened:

```text
https://www.69shuba.com/newhot_0_1_1.htm
```

Result:

- The user could not complete the Cloudflare verification.
- The saved Playwright state contained `cf_chl_rc_ni` and Turnstile
  localStorage data.
- It did not contain `cf_clearance`.

Conclusion:

- Plain headed Playwright is not equivalent to Reading's Android WebView or a
  real user browser profile.
- It should not be treated as a reliable automatic CF bypass path.

## Current Recommended Direction

Do not keep trying to make generic Playwright automatically pass third-party
Cloudflare challenges. The reliable product path should match Reading's model:

```text
detect challenge
-> create Browser Challenge session
-> open real user browser / Reading WebView
-> import or receive cookies
-> verify cf_clearance/cookie validity
-> retry original source operation
```

Next implementation stage should be:

```text
Browser Bridge Manual Verification v2
```

Suggested tasks:

1. Add stronger cookie validity check for `cf_clearance` per plugin/domain.
2. Add Console action to paste/import a full Cookie header.
3. Add aggregate-source response fields that make Reading open the same local
   challenge URL and submit cookies back to LegadoHub.
4. Add retry of the original operation after cookie import.
5. Add UI session status showing:
   - active session id
   - target URL
   - profile id
   - cookie domains
   - whether `cf_clearance` exists
   - last verification / cookie import result

## Runtime Artifacts To Avoid Committing

These are local runtime/generated artifacts and should remain uncommitted:

- `.tmp/`
- `backend/data/`
- `backend/data/browser_profiles/`
- `backend/config/aggregate_source.json` timestamp-only diffs

`.gitignore` now includes:

```text
backend/data/browser_profiles/
```

## Current Git State Notes

The working tree intentionally contains Stage 5 implementation changes and
untracked new files. It has not been committed or pushed in this final handoff
step.
