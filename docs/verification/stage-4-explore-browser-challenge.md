# Stage 4 Explore And Browser Challenge Verification

Date: 2026-06-07

## Scope

This verification covers the source-plugin `explore` lifecycle and the
Cloudflare/manual browser challenge recovery path.

## Implemented Runtime Behavior

- Source plugins may raise `CLOUDFLARE_REQUIRED` or `BROWSER_REQUIRED`.
- The scheduler converts those failures into structured `browserChallenge`
  sessions instead of treating them as opaque source errors.
- Console APIs now expose browser challenge sessions:
  - `GET /api/console/browser-challenges`
  - `POST /api/console/plugins/{plugin_id}/browser-challenge`
  - `GET /api/console/browser-challenges/{session_id}`
  - `POST /api/console/browser-challenges/{session_id}/cookies`
  - `POST /api/console/browser-challenges/{session_id}/retry-live-check`
  - `POST /api/console/browser-challenges/{session_id}/browser/open`
  - `GET /api/console/browser-challenges/{session_id}/browser/status`
  - `POST /api/console/browser-challenges/{session_id}/browser/import-cookies`
- Reading-compatible aggregate APIs also expose browser challenge sessions:
  - `GET /api/legado/browser-challenges`
  - `GET /api/legado/browser-challenges/{session_id}`
  - `POST /api/legado/browser-challenges/{session_id}/cookies`
  - `POST /api/legado/browser-challenges/{session_id}/browser/open`
  - `GET /api/legado/browser-challenges/{session_id}/browser/status`
  - `POST /api/legado/browser-challenges/{session_id}/browser/import-cookies`
  - `POST /api/legado/browser-challenges/{session_id}/retry-live-check`
  Challenges include both console actions and Legado-facing submit/status,
  browser-helper, import-cookie, and retry actions, so aggregate clients do not
  need to call console endpoints to complete browser verification.
- The generated aggregate source comment explicitly mentions
  `debug.browserChallenges`,
  `/api/legado/browser-challenges/{session_id}/browser/open`,
  `/api/legado/browser-challenges/{session_id}/cookies`, and
  `/api/legado/browser-challenges/{session_id}/retry-live-check`, so imported
  Reading clients expose the intended verification path in the source metadata.
- Submitted cookies are stored in `PluginAuthRepository` and are reused by the
  plugin runtime on later calls.
- Browser challenge cookie submission accepts Playwright-style cookie arrays,
  domain-keyed cookie maps, and plain Cookie header strings such as
  `cf_clearance=...; sid=...`. Plain strings are assigned to the challenged
  session's primary cookie domain and still report `clearanceDomains`.
- Browser challenge sessions can trigger a post-cookie live retry. The retry
  runs the same ranked/explore -> detail -> toc -> chapter ->
  search-by-ranked-title -> detail/toc/chapter acceptance path and stores the
  result back on the challenge session.
- Live acceptance and candidate verification failures now also return
  `browserChallenges` when the underlying plugin raises `CLOUDFLARE_REQUIRED` or
  `BROWSER_REQUIRED`, so retry failures remain actionable instead of collapsing
  to plain diagnostics.
- Reading-compatible aggregate API responses preserve
  `debug.browserChallenges` on search/explore/detail/toc/chapter failures.
- Reading-compatible aggregate API now also exposes
  `GET /api/legado/explore`, and the generated aggregate source exports
  `exploreUrl` plus `ruleExplore`.
- The aggregate source JSON includes a console `loginUrl` and comment explaining
  that browser challenges are handled through LegadoHub.
- The `/console` search workbench displays browser verification panels when
  search progress events or job results contain browser challenges.
- The same panel accepts pasted browser cookies as JSON or `Cookie` header text,
  saves them to the plugin auth store, and can immediately run the live retry
  check.
- The panel can also start a visible Playwright browser helper, import cookies
  captured by that helper, and then run the same live retry check. This mirrors
  the Reading-style manual Cloudflare verification flow while keeping browser
  orchestration in runtime instead of plugin code.
- The browser helper reads the same source-pool proxy configuration used by the
  plugin runtime and launches Playwright with that proxy when enabled.
- If a retry check returns a new browser challenge, the `/console` search
  workbench keeps that new challenge visible for the next verification attempt.
- Aegis browser verification pages, observed on `https://69shuba.tw/`, are
  classified as `BROWSER_REQUIRED` and enter the same challenge flow.
- Cloudflare Turnstile pages that expose markers such as
  `onloadTurnstileCallback`, `cf-turnstile`, or
  `challenges.cloudflare.com/turnstile` are now classified through the same
  runtime challenge detector. This covers the Reading rule pattern that starts
  a browser when `onloadTurnstileCallback` appears, and prevents 69shuba pages
  with a 200-status verification body from being mistaken for parse-empty book
  pages.
- Runtime now also supports controlled headless browser fetch for plugins that
  declare `browser.mode: required`. The plugin calls
  `ctx.fetch_text(..., browser=True)`, while LegadoHub core owns Playwright,
  proxy, timeout, and temporary profile cleanup.
- Console search now follows the Reading-style progressive model: every source
  emits `source_start`, `source_done`/`source_empty`/`source_timeout`/
  `source_verification_required`, and `result` events independently. Candidate
  book groups are updated as soon as a source returns results, without waiting
  for all sources to finish.
- Search cancellation now cancels pending source tasks in the active batch
  instead of only changing the job status.
- The Reading-compatible aggregate search endpoint now creates or reuses a
  background search job and returns a current snapshot quickly. Repeating the
  same keyword/page request returns the growing result set while the backend
  continues searching.
- The generated aggregate source uses
  `/api/legado/search?keyword={{key}}&page={{page}}&waitMs=1200`, so Reading
  clients do not block until every plugin finishes.
- Runtime now preflights Cloudflare browser-required search sources that have no
  stored `cf_clearance`. Those sources immediately emit
  `source_verification_required` and `debug.browserChallenges` instead of
  spending the normal source timeout on a doomed request.
- Browser-required plugin metadata may declare `browser.verificationUrl`.
  `69shuba_com` uses `https://www.69shuba.com/newhot_0_1_1.htm`, so both search
  preflight and explore failures point users at the same concrete verification
  page instead of a generic homepage.
- The console retry action now sends the active search keyword into
  `/api/console/browser-challenges/{session_id}/retry-live-check`, so manual
  verification retries follow the user's current search context.
- Browser-required plugins with `auth.mode: none` no longer report as ordinary
  "no login required" sources in the console. `/api/console/plugins/{id}/auth`
  returns `mode: browser_verification`, a `verificationStatus`, required
  actions, and a concrete `browserChallenges` entry when no usable cookies are
  stored. If cookies are present, the same endpoint reports
  `verificationStatus: cookies_saved` and asks the user to run live acceptance
  instead of treating saved cookies as proof of readability.
- Plugin detail pages now expose a direct "实时验收" action. It calls
  `/api/console/plugins/{id}/live-check` and displays the ranked book, search
  count, toc count, chapter content length, diagnostics, and any returned
  `browserChallenges`. This lets a user verify post-Cookie recovery for
  `69shuba_com` without first entering the search workbench.
- The same plugin detail challenge panel now exposes the runtime browser-helper
  flow: open verification URL, start visible browser helper, import captured
  cookies, manually paste/save cookies, and retry live acceptance for the
  challenge session.
- Browser challenge cookie submission now reports `clearanceDomains` and
  `missingClearanceDomains`, so users can see whether the saved cookies actually
  include `cf_clearance` for the domains required by the challenged source.
- The live acceptance matrix runner now supports direct Cookie-header injection
  for post-verification checks. After completing a real browser challenge, a
  maintainer can run the exact ranked reading loop without editing the database
  manually:

```powershell
cd backend
$env:LEGADOHUB_69SHUBA_COOKIE='cf_clearance=<real>; ...'
..\.venv\Scripts\python.exe scripts\run_live_acceptance_matrix.py --plugin 69shuba_com --clear-cookies --cookie-header-env LEGADOHUB_69SHUBA_COOKIE --cookie-domain 69shuba.com --keyword 剑宗外门
```

  The helper requires at least one explicit `--plugin`, parses the supplied
  `Cookie` header, saves it to the selected plugin's auth store, then runs the
  same explore -> detail -> toc -> chapter -> search-by-ranked-title loop.
  It accepts direct `--cookie-header`, `--cookie-header-env`, or
  `--cookie-header-file` input. `--clear-cookies` removes stale cookies for the
  selected plugin before the new Cookie header is saved.

  The runner can also open the same visible Playwright helper used by the
  console, then import the generated Playwright cookie JSON:

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\run_live_acceptance_matrix.py --plugin 69shuba_com --open-browser-challenge --keyword 剑宗外门
# Complete the challenge in the visible browser. The SUMMARY prints helper.cookieFile.
..\.venv\Scripts\python.exe scripts\run_live_acceptance_matrix.py --plugin 69shuba_com --clear-cookies --browser-cookie-json "<helper.cookieFile>" --keyword 剑宗外门
```

  The second command imports all domains present in the Playwright cookie file
  and immediately runs the ranked live acceptance loop.
- Runtime cookie matching now follows browser domain semantics: a cookie saved
  for `.69shuba.com`/`69shuba.com` is sent to `www.69shuba.com`, while
  subdomain-only cookies are not sent back to the parent domain. `Set-Cookie`
  `Domain=.example.com` attributes are persisted as parent-domain cookies.
- `69shuba_com` metadata now explicitly declares all browser-verification cookie
  domains: `69shuba.com`, `www.69shuba.com`, `69shuba.cx`, and
  `www.69shuba.cx`. The challenge session still deduplicates these with
  `domains` and `domainProfiles`, but the contract is now visible directly from
  the plugin metadata.
- Runtime-owned browser fetch now receives the same saved plugin cookies as the
  HTTP fetcher. Browser-required plugins such as `69shuba_com` and
  `69shuba_tw` can therefore reuse submitted verification cookies when they call
  `ctx.fetch_text(..., browser=True)`.
- Successful runtime-owned browser fetches now persist cookies returned by
  Playwright back into the plugin auth repository. A browser-only source can
  therefore acquire or refresh cookies during a successful browser fetch and
  reuse them on later HTTP or browser requests.
- Browser fetch also merges Playwright-returned cookies into its in-memory jar,
  so multiple `browser=True` fetches inside the same plugin execution can reuse
  cookies acquired by an earlier browser fetch before the next scheduler run.
- Normal HTTP fetches now persist response cookies into the plugin auth
  repository as well. `Set-Cookie: Domain=.69shuba.com` is stored as a
  parent-domain cookie and can be reused by later HTTP or browser fetches.
- Browser challenge API tests now use isolated temporary auth databases. Earlier
  test runs had written a fake `cf_clearance=ok` for `69shuba_com` into
  `backend/data/app.db`; that test residue was cleared before the latest live
  matrix.
- Added the standalone `69hsw_com` plugin for `https://www.69hsw.com/`.
  It is intentionally separate from `69shuba_com`: the site uses a different
  responsive HTML layout and its own numeric search captcha instead of the
  same Cloudflare desktop flow. The plugin supports explore/ranking, detail,
  toc, chapter, and a search fallback that can complete the ranked-title search
  loop from discover pages when the native search endpoint asks for captcha.

## 69shuba Live Evidence

Command:

```powershell
@'
import asyncio, json
from app.source_plugins.scheduler import PluginScheduler

async def main():
    scheduler = PluginScheduler()
    result = await scheduler.explore('69shuba_com', 'newhot', 1)
    print(json.dumps({
        'items': len(result.get('items', [])),
        'error': result.get('debug', {}).get('error'),
        'browserChallenges': result.get('debug', {}).get('browserChallenges', []),
    }, ensure_ascii=False, indent=2))

asyncio.run(main())
'@ | ..\.venv\Scripts\python.exe -
```

Result summary:

- `items`: `0`
- `debug.error.code`: `CLOUDFLARE_REQUIRED`
- `debug.error.message` records attempted domains:
  `https://www.69shuba.com/newhot_0_1_1.htm`,
  `https://www.69shuba.cx/newhot_0_1_1.htm`
- `debug.browserChallenges[0].openUrl`:
  `https://www.69shuba.com/newhot_0_1_1.htm`
- Cookie domains include `69shuba.com`, `www.69shuba.com`, `69shuba.cx`, and
  `www.69shuba.cx`.

This proves the runtime no longer collapses 69shuba into an opaque failure. It
returns a recoverable browser-verification session. It does not prove 69shuba is
fully readable before a user completes Cloudflare verification and submits valid
cookies.

## twkan Live Evidence

Command:

```powershell
@'
import asyncio, json
from app.source_plugins.scheduler import PluginScheduler
from app.services.live_acceptance import LiveAcceptanceService

async def main():
    scheduler = PluginScheduler()
    service = LiveAcceptanceService(scheduler=scheduler)
    result = await service.run_plugin_live_check('twkan_com', persist=False)
    print(json.dumps({
        'pluginId': result.get('pluginId'),
        'status': result.get('status'),
        'exploreName': result.get('explore', {}).get('selected', {}).get('name'),
        'exploreContentLength': result.get('explore', {}).get('contentLength'),
        'searchCount': result.get('search', {}).get('count'),
        'selectedName': result.get('selectedCandidate', {}).get('name'),
        'tocCount': result.get('toc', {}).get('count'),
        'contentLength': result.get('chapter', {}).get('contentLength'),
        'diagnostics': result.get('diagnostics'),
    }, ensure_ascii=False, indent=2))

asyncio.run(main())
'@ | ..\.venv\Scripts\python.exe -
```

Result:

- `pluginId`: `twkan_com`
- `status`: `passed`
- Ranked/explore book: `宇智波孤兒，我就無情怎麼了`
- Ranked/explore chapter content length: `5321`
- Search count for the ranked book name: `1`
- Selected search result: `宇智波孤兒，我就無情怎麼了`
- Toc count: `36`
- Search-loop chapter content length: `5321`
- Diagnostics: `[]`

This proves `twkan_com` passes the required
ranking/explore -> detail -> toc -> chapter -> search-by-ranked-title ->
detail/toc/chapter loop through the proxy-backed plugin runtime.

## Aggregate Explore Evidence

The generated aggregate source now includes:

- `enabledExplore: true`
- `exploreUrl`
- `ruleExplore`

Generated `exploreUrl` entries include:

- `聚合推荐::http://127.0.0.1:8765/api/legado/explore?page={{page}}`
- `69书吧::http://127.0.0.1:8765/api/legado/explore?sourceId=69shuba_com&page={{page}}`
- `台灣小說網::http://127.0.0.1:8765/api/legado/explore?sourceId=twkan_com&page={{page}}`

This means Reading-compatible clients can enter the ranked/discovery path from
the aggregate source, not only from the console.

## 69hsw.com Live Evidence

`69hsw_com` was added after checking the live site directly. The live site
supports ranking/category discovery without Cloudflare. Native `/ss/` search
may return a numeric captcha page, so the plugin treats that as a verification
condition and uses discover-page matching for the ranked-title acceptance loop.

Command:

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\run_live_acceptance_matrix.py --plugin 69hsw_com --keyword 剑宗外门
```

Result:

- `pluginId`: `69hsw_com`
- `status`: `passed`
- Ranked/explore book: `万古神帝`
- Ranked/explore chapter content length: `3550`
- Search count for the ranked book name: `1`
- Selected search result: `万古神帝`
- Toc count: `4364`
- Search-loop chapter content length: `3550`
- Diagnostics: `[]`

## 69shuba.tw And Google Search Notes

`https://69shuba.tw/` was checked after the user reported it as another 69书吧
site. Normal HTTP and browser-impersonated requests return an Aegis verification
page containing `aegis_challenge_object` / `aegis_challenge_verify`. It is not a
drop-in mirror for `69shuba_com`: it uses mobile-oriented pages such as
`/book/{id}/`, `/indexlist/{id}/`, and `/read/{bookId}/{chapterId}`. It is now
implemented as the separate `69shuba_tw` plugin, using runtime-owned browser
fetch through the configured proxy.

Live acceptance evidence for `69shuba_tw`:

- `pluginId`: `69shuba_tw`
- `status`: `passed`
- Ranked/explore book: `我咋就天下無敵了`
- Ranked/explore chapter content length: `4684`
- Search count for the ranked book name: `1`
- Selected search result: `我咋就天下無敵了`
- Toc count: `100`
- Search-loop chapter content length: `4684`
- Diagnostics: `[]`

Google `site:www.69shuba.com <book>` was also checked as a possible workaround
for site search blocked by Cloudflare. HTTP requests to Google returned a search
page, but no stable direct `69shuba.com` result links were extractable in the
current probe. It may be useful as a manual diagnostic or future configurable
search-only fallback, but it does not solve `.com` detail/toc/chapter Cloudflare
access and therefore is not used as the default backend reading path.

After the Yiove rule review, the parser keeps the Google/Bing direct-link
fallback as an explicit diagnostic path. Normal runtime search now prioritizes
fast, recoverable browser verification for `69shuba_com` when no valid
Cloudflare clearance is present, instead of letting blocked search requests
collapse into opaque timeouts.

For Traditional Chinese sources such as `69shuba_tw`, search input is converted
from Simplified to Traditional before submitting to the site, while all returned
book/detail/toc/chapter text is converted back to Simplified Chinese.
`69shuba_tw` now uses the site's stable GET query form
`/search/?searchkey=<traditional keyword>`; the generic POST form workflow was
observed to time out for `剑宗外门`.

Yiove source references used for this decision:

- `https://shuyuan.yiove.com/book-source/410ad233-0c84-4809-aaec-80d0f5b5862d`
- `https://shuyuan.yiove.com/book-source/7e136abd-eb70-40b6-bc8a-a7543ab5874c`

## Verification Commands

Backend full test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
```

Result:

- `146 passed, 7 warnings in 75.88s`

Targeted browser challenge and realtime search tests:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_browser_challenge.py backend/tests/test_realtime_search_api.py -q
```

Result:

- `9 passed, 6 warnings in 29.65s`

Targeted aggregate explore and fetcher classification tests:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_aggregate_source_plugin_runtime.py backend/tests/source_plugins/test_fetcher.py -q
```

Result:

- `11 passed, 1 warning in 24.42s`

Targeted browser challenge tests after adding the browser helper API:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_browser_challenge.py -q
```

Result:

- `6 passed, 1 warning in 2.80s`

Targeted live acceptance challenge propagation tests:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_live_acceptance.py backend/tests/test_browser_challenge.py -q
```

Result:

- `9 passed, 1 warning in 3.20s`

Frontend build:

```powershell
cd frontend; npm run build
```

Result:

- Vite build succeeded.
- Output assets:
  - `dist/assets/index-DbV16m0f.css`
  - `dist/assets/index-B-ZzfegA.js`

Additional targeted tests:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/test_69shuba_domain_fallback.py backend/tests/test_browser_challenge.py -q
```

Result:

- `5 passed, 1 warning in 3.58s`

Additional verification after adding source access type, 69shuba search
fallback, and Traditional-to-Simplified conversion:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_69shuba_domain_fallback.py backend\tests\test_69shuba_tw_simplified.py backend\tests\test_plugin_console_api.py -q
```

Result:

- `16 passed, 1 warning in 2.93s`

Targeted verification after making `69shuba_com` cookie domains explicit in
metadata:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_plugin_console_api.py backend\tests\test_browser_challenge.py backend\tests\test_69shuba_domain_fallback.py -q
```

Result:

- `30 passed, 1 warning in 4.01s`

Targeted verification after adding shared Cloudflare/Turnstile/Aegis challenge
detection:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\source_plugins\test_fetcher.py backend\tests\test_69shuba_domain_fallback.py -q
```

Result:

- `17 passed in 8.02s`

Targeted verification after adding Cookie-header/env/file support, browser
cookie JSON import, helper launch support, and explicit cookie clearing to the
live matrix runner:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\scripts\test_run_live_acceptance_matrix.py -q
```

Result:

- `12 passed in 1.92s`

Progressive search and aggregate snapshot verification:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_aggregate_source_plugin_runtime.py backend\tests\test_realtime_search_api.py backend\tests\test_browser_challenge.py backend\tests\test_69shuba_tw_simplified.py backend\tests\test_69shuba_domain_fallback.py -q
```

Result:

- `26 passed, 2 warnings in 90.88s`

Aggregate browser challenge propagation verification after adding explicit
detail/toc/chapter regression coverage:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_aggregate_source_plugin_runtime.py backend\tests\test_browser_challenge.py backend\tests\test_realtime_search_api.py -q
```

Result:

- `27 passed, 1 warning in 76.94s`

Frontend build after progressive search UI changes:

```powershell
cd frontend; npm run build
```

Result:

- Vite build succeeded.
- Output assets:
  - `dist/assets/index-DbV16m0f.css`
  - `dist/assets/index-BJpIoYdv.js`

Full backend regression:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

Result:

- `178 passed, 1 warning in 82.62s`

Frontend build after the console source type column:

```powershell
cd frontend; npm run build
```

Result:

- Vite build succeeded.
- Output assets:
  - `dist/assets/index-DbV16m0f.css`
  - `dist/assets/index-D9G51DZ0.js`

Plugin detail browser verification smoke:

```powershell
# Start uvicorn on 127.0.0.1:8765, open /console/plugins/69shuba_com with Playwright,
# then stop the started server process.
```

Result:

- `hasPlugin`: `true`
- `hasAuth`: `true`
- `hasLiveCheck`: `true`
- `hasCookieButton`: `true`
- After opening the Auth tab and loading auth state:
  - `hasSaveCookie`: `true`
  - `hasBrowserHelper`: `true`
  - `hasRetry`: `true`

Full live acceptance matrix after adding `69hsw_com`:

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\run_live_acceptance_matrix.py --keyword 剑宗外门 --json-out ..\docs\verification\live-matrix-latest.json
```

Latest result on 2026-06-08:

- Total plugins: `9`
- Passed: `7`
- Failed: `2`
- Passed plugins:
  `22biqu_com`, `69hsw_com`, `69shuba_tw`, `biquge365_net`,
  `shuhaige_net`, `xbiqugu_la`, `xbiquzw_net`
- Recoverable browser-verification plugins:
  `69shuba_com`, `twkan_com`
- `69shuba_com` failure is a recoverable `BROWSER_REQUIRED` challenge with
  attempted domains:
  `https://www.69shuba.com/newhot_0_1_1.htm`,
  `https://www.69shuba.cx/newhot_0_1_1.htm`
- `twkan_com` can pass the full loop when the proxy/browser-impersonated
  request is accepted by the site, but the latest full matrix returned
  `CLOUDFLARE_REQUIRED` for `https://twkan.com/novels/hot`. The plugin metadata
  now declares `browser.mode: optional` and `browser-challenge` so console and
  aggregate clients can surface the same manual verification flow.

`22biqu_com` search note:

- Native search can return a `搜索间隔: 30 秒` script page even though the
  ranked book is readable.
- The plugin now treats that as a site-level rate/captcha condition and falls
  back to discover/ranking matching, keeping concurrency and waiting policy in
  the runtime.
- Single-source check after the fix passed with ranked book `读档九八`,
  `searchCount: 4`, `tocCount: 200`, and chapter content length `1709`.

Live `69shuba_tw` acceptance after conversion:

- `status`: `passed`
- explore selected: `我咋就天下无敌了`
- explore content length: `4684`
- search count: `1`
- detail name: `我咋就天下无敌了`
- toc count: `100`
- chapter title: `第1章 这是高手，绝对是高手(1 / 1)`
- chapter content length: `4684`
- chapter preview is simplified text, for example `拿着木棍`, `蹲着`, `混着`.

Direct live search evidence for user keyword `剑宗外门`:

- `69shuba_tw` search count: `1`
- First result: `剑宗外门`
- Author: `其声喵喵然`
- Book URL: `https://69shuba.tw/book/347237/`
- Detail name: `剑宗外门`
- Toc count: `100`
- First chapter: `第1章 石珠(1 / 1)`
- First chapter content length: `3718`
- Content preview is Simplified Chinese; the previous `捏著` residue now becomes
  `捏着`.

Live `twkan_com` acceptance evidence:

- `status`: `passed`
- ranked/explore selected: `宇智波孤兒，我就無情怎麼了`
- explore content length: `5321`
- search count: `1`
- toc count: `36`
- chapter content length: `5321`
- diagnostics: `[]`

The same site is now also observed to intermittently return Cloudflare from
this environment. A direct runtime browser fetch still stops on the verification
page, so current failures are reported as recoverable browser challenges instead
of being counted as parser failures.

Live `69shuba_com` challenge evidence after clearing stored fake test cookies:

- 2026-06-08 single-source live-check still returns `CLOUDFLARE_REQUIRED`:
  - `openUrl`: `https://www.69shuba.com/newhot_0_1_1.htm`
  - attempted domains:
    `https://www.69shuba.com/newhot_0_1_1.htm`,
    `https://www.69shuba.cx/newhot_0_1_1.htm`
- Console auth endpoint returns:
  - `mode`: `browser_verification`
  - `verificationStatus`: `required`
  - `requiredActions`: `["browser_verification"]`
  - `browserChallenges[0].openUrl`:
    `https://www.69shuba.com/newhot_0_1_1.htm`
  - Stored cookies remain `{}` after checking auth.
- Console plugin live-check endpoint returns:
  - `status`: `failed`
  - `passed`: `false`
  - `diagnostics[0].code`: `BROWSER_REQUIRED`
  - `browserChallenges[0].openUrl`:
    `https://www.69shuba.com/newhot_0_1_1.htm`
  - `browserChallenges[0].actions` includes submit-cookie, browser-helper,
    import-cookie, and retry-live-check endpoints.
- Challenge cookie submission probe with a `.69shuba.com` `cf_clearance` returns:
  - `saved`: `true`
  - `clearanceDomains`: `["69shuba.com"]`
  - `missingClearanceDomains`:
    `["69shuba.cx", "www.69shuba.cx"]`
- Search for `剑宗外门` returns `BROWSER_REQUIRED`.
- Search challenge stage: `search`
- Search preflight challenge open URL:
  `https://www.69shuba.com/newhot_0_1_1.htm`
- Explore challenge open URL:
  `https://www.69shuba.com/newhot_0_1_1.htm`
- Cookie domains include `69shuba.com`, `www.69shuba.com`, `69shuba.cx`, and
  `www.69shuba.cx`.
- Aggregate search snapshot shows `source_verification_required:69shuba_com`
  within the first second and exposes one `debug.browserChallenges` item while
  the remaining sources continue running.

Yiove source index lookup:

- Search page URL: `https://shuyuan.yiove.com/search?page=1&page_size=20&search_type=book-sources&keyword=69`
- Actual API base discovered from the SPA bundle: `https://shuyuan-api.yiove.com`
- Search API:
  `https://shuyuan-api.yiove.com/shuyuan/search?search_key=69&search_type=book-sources&page=1&page_size=20`
- Import API:
  `https://shuyuan-api.yiove.com/import/book-source-search/1-20/69`
- The index returned multiple 69-family sources, including `69书吧`,
  `69书吧[需要挂🪜.有点小问题]`, and `太极书吧（魔法）`.
- The `太极书吧（魔法）` rule uses `https://69shux.co/search/{{key}}/{{page}}.html`,
  explicit `java.t2s` conversion, and stronger chapter cleanup. This supports
  treating it as a separate future 69-family plugin instead of mixing it into
  `69shuba_com`.

`69shuba_com` search fallback boundary:

- Native `www.69shuba.com` search returned `HTTP 401` from this environment.
- Search fallback was triggered and fetched Google and Bing `site:` result
  pages.
- The fallback only returns items when it can parse a
  `https://www.69shuba.com/book/*.htm` or `/txt/*.htm` URL. In the current live
  run no such URL was parsed for keyword `我有一个`, so the plugin correctly
  reported the original `HTTP 401` instead of fabricating a result.

## Current Verification On 2026-06-08

Targeted runtime tests after the `twkan_com` optional browser fallback and
browser challenge propagation work:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_live_acceptance.py backend\tests\test_realtime_search_api.py backend\tests\test_browser_challenge.py backend\tests\test_twkan_browser_fallback.py -q
```

Result:

- `28 passed, 1 warning in 16.65s`

Full backend regression:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

Result:

- `195 passed, 1 warning in 86.65s`

Script compile check:

```powershell
.\.venv\Scripts\python.exe -m py_compile backend\scripts\run_live_acceptance_matrix.py
```

Result:

- Passed with no output.

Latest full live acceptance matrix:

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\run_live_acceptance_matrix.py --keyword 剑宗外门 --json-out ..\docs\verification\live-matrix-latest.json
```

Result:

- Total plugins: `9`
- Passed in the full matrix: `6`
- Full-matrix passed plugins:
  `22biqu_com`, `69hsw_com`, `shuhaige_net`, `twkan_com`,
  `xbiqugu_la`, `xbiquzw_net`
- `69shuba_com` is still a recoverable Cloudflare/browser challenge:
  - `reason`: `CLOUDFLARE_REQUIRED`
  - `openUrl`: `https://www.69shuba.com/newhot_0_1_1.htm`
  - attempted domains:
    `https://www.69shuba.com/newhot_0_1_1.htm`,
    `https://www.69shuba.cx/newhot_0_1_1.htm`
- `69shuba_tw` and `biquge365_net` timed out during this full matrix run, but
  both immediately passed when rerun as selected single-source checks:
  - `69shuba_tw`: ranked book `我咋就天下无敌了`, toc `100`,
    chapter content length `4684`
  - `biquge365_net`: ranked book `斗罗大陆4`, search count `6`,
    toc `26`, chapter content length `2836`

Selected transient-source rerun:

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\run_live_acceptance_matrix.py --plugin 69shuba_tw --plugin biquge365_net --keyword 剑宗外门
```

Result:

- `69shuba_tw`: `passed`
- `biquge365_net`: `passed`

Single-source rerun for the xbiqugu mirror-backed plugins:

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\run_live_acceptance_matrix.py --plugin xbiqugu_la --plugin xbiquzw_net --keyword 剑宗外门
```

Result:

- `xbiqugu_la`: `passed`
- `xbiquzw_net`: `passed`

Current persisted `69shuba_com` auth cookies were checked after these probes and
remain `{}`. No fake Cloudflare clearance is present in `backend/data/app.db`.

## 69shuba Detail-Page Recheck On 2026-06-08

After testing the user-reported real browser behavior, `69shuba_com` was narrowed
from "whole-site Cloudflare" to a split access model:

- Ranking/search entry pages can still return Cloudflare from the backend.
- Known detail pages can be fetched without cookies when the runtime uses
  `curl_cffi` Chrome impersonation.
- Chapter pages require a detail/catalog `Referer`; direct chapter requests
  without that `Referer` can return Cloudflare.
- The site serves GBK HTML while reporting a conflicting UTF-8 content type in
  the impersonated response path, so runtime decoding now prefers HTML
  `<meta charset>` before response headers.

Live detail reading probe:

```powershell
cd backend
# detail -> toc -> first chapter for https://www.69shuba.com/book/90442.htm
```

Result:

- Book: `霍格沃茨的学习面板`
- Author: `林曦遇鹿`
- Toc count: `569`
- First chapter: `第1章 1：伦敦孤儿`
- Chapter content length: `2360`

The live acceptance matrix for `69shuba_com` still fails when it starts from the
rank/explore entry because `https://www.69shuba.com/newhot_0_1_1.htm` returns a
recoverable browser challenge. The acceptance runner now records that challenge
and can fall back to the search path for sources declaring
`browser.searchFallback: search_engine`. In the current backend environment,
Google/Bing did not return a stable parseable `69shuba.com/book/*.htm` result
for `霍格沃茨的学习面板`, so the search fallback correctly ended as
`BROWSER_REQUIRED` instead of fabricating a candidate.

Browser-helper Cookie import was also hardened:

- The helper now writes cookie domains, cookie names, and `cf_clearance`
  domains into the captured cookie JSON.
- It queries cookies for the source-declared target domains, not only the
  current page context.
- Manual cookie paste accepts raw `Cookie:` and `Set-Cookie:` header lines from
  browser DevTools.

Verification after these changes:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
cd frontend; npm run build
git diff --check
```

Result:

- Backend: `199 passed, 2 warnings in 120.16s`
- Frontend: Vite build succeeded, output JS `index-4Sm1bCQQ.js`
- `git diff --check`: passed with no output

## Remaining Gap

`69shuba_com` still requires a real browser Cloudflare clearance before the
rank/detail/toc/chapter reading loop can pass live. `twkan_com` also
intermittently requires Cloudflare verification from the current runtime
environment. The backend and aggregate API support both as recoverable manual
verification flows. The separate `69shuba_tw` plugin now provides a working
69书吧-family reading loop through runtime browser fetch and self-converts
Traditional Chinese output to Simplified Chinese, but it is intentionally not
merged into `69shuba_com` because the domains have different DOM and
verification behavior.

The plugin now performs real same-site domain fallback across
`www.69shuba.com` and `www.69shuba.cx`. Current live evidence shows both domains
are challenged by Cloudflare from this runtime/proxy environment.
