# Stage 5 Browserless Browser Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build LegadoHub Browser Bridge on Browserless Docker + Playwright, with fixed per-source access strategies, long-lived browser sessions/cookies, search-engine access, and one shared challenge session flow for Console and aggregate-source clients.

**Architecture:** LegadoHub backend remains the orchestration owner. Source plugins declare access strategy and parse site responses; they do not control browser lifecycle, concurrency, proxy, cookie persistence, or retry policy. Browserless is the browser runtime substrate; LegadoHub Browser Bridge is the business control layer that exposes HTTP, stealth HTTP, browser fetch, search-engine, profile, cookie, network, DOM, and challenge-session capabilities.

**Tech Stack:** FastAPI/Python backend, Playwright client, Browserless Docker service, SQLite-backed auth/session repositories, React console UI, existing Reading-compatible aggregate API.

---

## Goal Command

```text
实现 Stage 5 Browserless Browser Bridge：基于 Browserless Docker + Playwright 建立固定书源访问策略、长期 profile/cookie、统一挑战会话、搜索引擎接口，并完成 69shuba 系列源的真实搜索/详情/目录/正文验收。
```

## Non-Negotiable Decisions

- Browser runtime uses self-hosted Browserless in Docker, not a Chrome extension.
- A finished source chooses one final strategy per lifecycle stage; do not keep a permanent chain of hidden fallbacks.
- Console verification and aggregate-source verification use the same challenge session model.
- Browser Bridge may attempt automatic challenge completion, but it must not claim guaranteed CF bypass. If the page requires human interaction, return the verification page/session to the user.
- Browser Bridge owns long-lived session state: profile, cookies, storage snapshot, proxy binding, challenge status, and verification timestamps.
- Source plugins may request named capabilities through `ctx`, but must not create unmanaged Playwright, Browserless, browser profile, global HTTP session, or background task objects.
- Search-engine access is a Browser Bridge capability, not duplicated inside individual source plugins.

## Target Capability Surface

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

## Target Source Strategy Contract

Add a backward-compatible optional metadata section:

```yaml
accessStrategy:
  search: http | stealth_http | search_engine | browser | cf_challenge
  detail: http | stealth_http | browser
  toc: http | stealth_http | browser
  chapter: http | stealth_http | browser
browser:
  mode: none | optional | required
  provider: browserless
  profileScope: plugin_domain_proxy
  challenge:
    mode: attempt_then_manual
    verificationUrl: https://example.com/
    callback: local
searchEngine:
  providerOrder:
    - duckduckgo_html
    - bing_html
  targetDomain: www.example.com
  urlPatterns:
    - /book/\d+\.htm
```

For `69shuba_com`, the expected final strategy is:

```yaml
accessStrategy:
  search: search_engine
  detail: stealth_http
  toc: stealth_http
  chapter: stealth_http
browser:
  mode: required
  provider: browserless
  profileScope: plugin_domain_proxy
  challenge:
    mode: attempt_then_manual
    verificationUrl: https://www.69shuba.com/newhot_0_1_1.htm
searchEngine:
  providerOrder:
    - duckduckgo_html
    - bing_html
  targetDomain: www.69shuba.com
  urlPatterns:
    - /book/\d+\.htm
```

## File Map

- Modify: `backend/requirements.txt`
  Add any Python Browserless/Playwright client dependencies only if the existing stack cannot connect to Browserless with current dependencies.
- Create: `backend/app/services/browser_bridge/`
  Browser Bridge package. Keep files focused; avoid turning the old `browser_fetch.py` into a large mixed service.
- Create: `backend/app/services/browser_bridge/models.py`
  Dataclasses or Pydantic models for access strategy, browser request, browser response, profile id, challenge attempt result, search-engine result, DOM snapshot, and session status.
- Create: `backend/app/services/browser_bridge/config.py`
  Load Browserless endpoint, token, default timeouts, profile root, and public callback base URL from config/env.
- Create: `backend/app/services/browser_bridge/client.py`
  Low-level Browserless/Playwright connection and lifecycle wrapper.
- Create: `backend/app/services/browser_bridge/profiles.py`
  Stable profile id calculation and profile/cookie/storage persistence rules.
- Create: `backend/app/services/browser_bridge/search_engine.py`
  DuckDuckGo/Bing HTML search implementation and URL-pattern extraction.
- Create: `backend/app/services/browser_bridge/challenge.py`
  Unified challenge session orchestration, automatic attempt, manual open/callback, retry handoff.
- Create: `backend/app/services/browser_bridge/dom.py`
  DOM snapshot and network capture helpers.
- Modify: `backend/app/source_plugins/models.py`
  Parse and validate optional `accessStrategy` and `searchEngine`.
- Modify: `backend/app/source_plugins/context.py`
  Expose controlled Browser Bridge methods through `ctx.browser` or explicit methods.
- Modify: `backend/app/source_plugins/scheduler.py`
  Route plugin lifecycle calls through access strategy where appropriate and emit progressive challenge/search events.
- Modify: `backend/app/services/browser_challenge.py`
  Either migrate into `browser_bridge/challenge.py` or keep as a compatibility wrapper with no duplicate session model.
- Modify: `backend/app/api/console.py`
  Add Console endpoints for Browser Bridge status, session open, callback, cookie/profile status, and retry.
- Modify: `backend/app/api/legado.py` or current aggregate API module
  Expose the same challenge session URLs to Reading-compatible clients using local/public callback base URL.
- Modify: `backend/config/source_pool.json`
  Add Browserless connection settings and public callback host settings.
- Modify: `start.bat`
  Detect Browserless config and print Browser Bridge readiness guidance.
- Modify: `plugins/sources/69shuba_com/metadata.yaml`
  Set final strategy to search-engine search and stealth HTTP reading stages.
- Modify: `plugins/sources/69shuba_tw/metadata.yaml`, `plugins/sources/69hsw_com/metadata.yaml`, `plugins/sources/twkan_com/metadata.yaml`
  Declare final strategy based on live behavior discovered in current implementation.
- Create/Modify tests under `backend/tests/`
  Unit tests for metadata parsing, profile id, search-engine extraction, challenge session, API shape, aggregate callback URLs, and scheduler events.
- Create/Update: `docs/architecture/browser-bridge.md`
  Architecture and capability contract.
- Create/Update: `docs/verification/stage-5-browserless-browser-bridge.md`
  Verification log with exact commands and live source evidence.

---

## Task 0: Baseline And Guardrails

**Files:**
- Read: `docs/architecture/source-plugin-contract.md`
- Read: `docs/verification/stage-4-explore-browser-challenge.md`
- Read: `backend/app/services/browser_fetch.py`
- Read: `backend/app/services/browser_challenge.py`
- Read: `backend/scripts/browser_fetch_helper.mjs`
- Read: `backend/scripts/browser_challenge_helper.mjs`

- [ ] **Step 1: Run baseline tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

Expected: Current backend tests pass or existing failures are documented before any edit.

- [ ] **Step 2: Run frontend build**

Run:

```powershell
cd frontend; npm run build; cd ..
```

Expected: Build succeeds before Browser Bridge changes.

- [ ] **Step 3: Scan for legacy route/name residue**

Run:

```powershell
rg -n "/admin|api/admin|demo_|engine-jvm|LegadoEngineRunner|app\.legado_engine|app\.engine" backend frontend plugins docs -S -g "!docs/archive/**"
```

Expected: No active runtime dependency on archived engine or `/admin`; documented historical mentions are acceptable only in archive/verification docs.

---

## Task 1: Browser Bridge Contract And Metadata Parsing

**Files:**
- Modify: `docs/architecture/source-plugin-contract.md`
- Modify: `backend/app/source_plugins/models.py`
- Test: `backend/tests/source_plugins/test_models.py`

- [ ] **Step 1: Add failing metadata tests**

Add tests that verify:

```python
def test_metadata_accepts_access_strategy():
    metadata = PluginMetadata.from_dict({
        "contractVersion": "1.0",
        "id": "example",
        "name": "示例",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search", "detail", "toc", "chapter"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "tags": ["html"],
        "accessStrategy": {
            "search": "search_engine",
            "detail": "stealth_http",
            "toc": "stealth_http",
            "chapter": "stealth_http",
        },
        "searchEngine": {
            "providerOrder": ["duckduckgo_html", "bing_html"],
            "targetDomain": "www.example.com",
            "urlPatterns": [r"/book/\d+\.htm"],
        },
    })
    assert metadata.access_strategy["search"] == "search_engine"
    assert metadata.search_engine["targetDomain"] == "www.example.com"
    assert metadata.validate() == []


def test_metadata_rejects_invalid_access_strategy():
    metadata = PluginMetadata.from_dict({
        "contractVersion": "1.0",
        "id": "example",
        "name": "示例",
        "version": "0.1.0",
        "type": "source",
        "domains": ["example.com"],
        "baseUrls": ["https://example.com"],
        "capabilities": ["search"],
        "auth": {"mode": "none"},
        "content": {"access": "free"},
        "tags": [],
        "accessStrategy": {"search": "random_fallback"},
    })
    assert "invalid accessStrategy.search: random_fallback" in metadata.validate()
```

- [ ] **Step 2: Run failing tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\source_plugins\test_models.py -q
```

Expected: Fails because `PluginMetadata` does not yet expose/validate `access_strategy` and `search_engine`.

- [ ] **Step 3: Implement metadata fields and validation**

Add fields to `PluginMetadata`:

```python
access_strategy: dict = field(default_factory=dict)
search_engine: dict = field(default_factory=dict)
```

Parse them in `from_dict` from `accessStrategy` and `searchEngine`.

Validate with these values:

```python
valid_strategy = {"http", "stealth_http", "search_engine", "browser", "cf_challenge"}
for stage, mode in self.access_strategy.items():
    if stage not in {"search", "detail", "toc", "chapter", "explore"}:
        errors.append(f"invalid accessStrategy stage: {stage}")
    if mode not in valid_strategy:
        errors.append(f"invalid accessStrategy.{stage}: {mode}")
```

- [ ] **Step 4: Document the contract**

In `docs/architecture/source-plugin-contract.md`, add the `accessStrategy` and `searchEngine` optional sections shown in this plan.

- [ ] **Step 5: Run tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\source_plugins\test_models.py -q
```

Expected: Metadata tests pass.

---

## Task 2: Browserless Configuration And Profile Identity

**Files:**
- Create: `backend/app/services/browser_bridge/__init__.py`
- Create: `backend/app/services/browser_bridge/config.py`
- Create: `backend/app/services/browser_bridge/models.py`
- Create: `backend/app/services/browser_bridge/profiles.py`
- Test: `backend/tests/test_browser_bridge_config.py`
- Test: `backend/tests/test_browser_bridge_profiles.py`

- [ ] **Step 1: Add config tests**

Verify env/default config:

```python
def test_browser_bridge_config_defaults(monkeypatch):
    monkeypatch.delenv("LEGADOHUB_BROWSERLESS_WS", raising=False)
    config = BrowserBridgeConfig.from_env()
    assert config.provider == "browserless"
    assert config.connect_timeout_ms > 0
    assert config.profile_root.name == "browser_profiles"
```

- [ ] **Step 2: Add profile id tests**

Verify stable separation:

```python
def test_profile_id_includes_plugin_domain_and_proxy():
    first = make_profile_id("69shuba_com", "primary", "proxy-a")
    second = make_profile_id("69shuba_com", "primary", "proxy-b")
    assert first != second
    assert first.startswith("69shuba_com-primary-")
```

- [ ] **Step 3: Implement config and profile helpers**

`BrowserBridgeConfig` must read:

```text
LEGADOHUB_BROWSERLESS_WS
LEGADOHUB_BROWSERLESS_TOKEN
LEGADOHUB_BROWSER_PUBLIC_BASE_URL
LEGADOHUB_BROWSER_PROFILE_ROOT
LEGADOHUB_BROWSER_CONNECT_TIMEOUT_MS
LEGADOHUB_BROWSER_ACTION_TIMEOUT_MS
```

Default profile root:

```text
backend/data/browser_profiles
```

- [ ] **Step 4: Run tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_browser_bridge_config.py backend\tests\test_browser_bridge_profiles.py -q
```

Expected: New config/profile tests pass.

---

## Task 3: Browserless Client And Browser Fetch

**Files:**
- Create: `backend/app/services/browser_bridge/client.py`
- Modify: `backend/app/source_plugins/context.py`
- Test: `backend/tests/test_browser_bridge_client.py`
- Test: `backend/tests/source_plugins/test_context.py`

- [ ] **Step 1: Add fake-client unit tests**

Use a fake Browserless adapter so CI does not require real Browserless:

```python
class FakeBrowserlessClient:
    async def fetch(self, request):
        return BrowserFetchResult(
            ok=True,
            final_url="https://example.com/book/1.htm",
            title="Example",
            html="<html><body>ok</body></html>",
            cookies=[{"domain": "example.com", "name": "sid", "value": "1"}],
            challenge={"detected": False},
            network=[],
        )
```

Assert `ctx.browser.fetch_text(...)` returns HTML and persists cookies through the existing auth repository.

- [ ] **Step 2: Define request/result models**

Use explicit models for:

```text
BrowserFetchRequest
BrowserFetchResult
BrowserChallengeState
BrowserCookie
NetworkEntry
DomSnapshot
```

Result must include:

```text
ok
final_url
title
html
cookies
challenge.detected
challenge.kind
challenge.message
network
dom_snapshot
proxy_used
profile_id
elapsed_ms
```

- [ ] **Step 3: Implement Browserless connection wrapper**

Connect to Browserless by WebSocket URL. Keep implementation behind `BrowserBridgeClient` so tests can inject fake adapters.

- [ ] **Step 4: Keep old browser helper as compatibility only**

Do not remove `backend/app/services/browser_fetch.py` in this task. Route new code through Browser Bridge while keeping old tests passing.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_browser_bridge_client.py backend\tests\source_plugins\test_context.py -q
```

Expected: Context and Browser Bridge tests pass without real Browserless.

---

## Task 4: Unified Challenge Session

**Files:**
- Create: `backend/app/services/browser_bridge/challenge.py`
- Modify: `backend/app/services/browser_challenge.py`
- Modify: `backend/app/api/console.py`
- Modify: aggregate API module under `backend/app/api/`
- Test: `backend/tests/test_browser_challenge.py`
- Test: `backend/tests/test_browser_bridge_challenge.py`
- Test: `backend/tests/test_aggregate_source_plugin_runtime.py`

- [ ] **Step 1: Add tests for one session, two entry points**

Assert Console and aggregate open URLs point to the same session id and same callback:

```python
def test_console_and_legado_challenge_share_session():
    session = service.create_session(source_id="69shuba_com", open_url="https://www.69shuba.com/newhot_0_1_1.htm")
    assert session["actions"]["consoleOpen"].endswith(f"/api/browser/challenges/{session['sessionId']}/open")
    assert session["actions"]["legadoOpen"].endswith(f"/api/browser/challenges/{session['sessionId']}/open")
    assert session["actions"]["callback"].endswith(f"/api/browser/challenges/{session['sessionId']}/callback")
```

- [ ] **Step 2: Implement session states**

Required states:

```text
pending
auto_attempting
auto_passed
manual_required
browser_opened
verified
cookies_saved
retry_passed
retry_failed
expired
failed
```

- [ ] **Step 3: Implement automatic attempt handoff**

`challenge.attempt` must:

- Open Browserless session with the correct profile id.
- Wait for normal challenge completion markers.
- Collect cookies/storage.
- If usable cookies or non-challenge final HTML is detected, mark `auto_passed`.
- If still on CF/Turnstile/Aegis/captcha page, mark `manual_required` and return local `challenge.open`.

- [ ] **Step 4: Implement callback**

`challenge.callback` must:

- Accept Browser Bridge callback payload.
- Save cookies/storage/profile status.
- Mark session `verified` or `manual_required`.
- Trigger retry of original operation when the original operation is still resumable.

- [ ] **Step 5: Preserve existing cookie paste/import behavior**

Existing cookie JSON, Cookie header, and Set-Cookie header import must continue to work.

- [ ] **Step 6: Run tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_browser_challenge.py backend\tests\test_browser_bridge_challenge.py backend\tests\test_aggregate_source_plugin_runtime.py -q
```

Expected: Old challenge behavior and new unified session behavior pass.

---

## Task 5: Search Engine As Browser Bridge Capability

**Files:**
- Create: `backend/app/services/browser_bridge/search_engine.py`
- Modify: `plugins/sources/69shuba_com/source.py`
- Modify: `plugins/sources/69shuba_com/metadata.yaml`
- Test: `backend/tests/test_browser_bridge_search_engine.py`
- Test: `backend/tests/test_69shuba_domain_fallback.py`

- [ ] **Step 1: Add parser tests**

Use fixed HTML fixtures for DuckDuckGo and Bing. Assert direct links, redirected `uddg`, and Bing encoded redirect links are extracted.

- [ ] **Step 2: Implement provider interface**

Expose:

```python
async def search_site(
    keyword: str,
    *,
    target_domain: str,
    url_patterns: list[str],
    provider_order: list[str],
    limit: int = 10,
) -> list[SearchEngineHit]:
    ...
```

Each hit must include:

```text
title
url
provider
rank
snippet
matched_pattern
```

- [ ] **Step 3: Route 69shuba search through Browser Bridge searchEngine**

The plugin should not contain its own DuckDuckGo/Bing parsing logic after this task. It may map Browser Bridge hits into source search results.

- [ ] **Step 4: Run tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_browser_bridge_search_engine.py backend\tests\test_69shuba_domain_fallback.py -q
```

Expected: Search-engine parser and 69shuba search strategy tests pass.

---

## Task 6: Scheduler Strategy Routing And Progressive Events

**Files:**
- Modify: `backend/app/source_plugins/scheduler.py`
- Modify: `backend/app/services/search_jobs.py`
- Test: `backend/tests/source_plugins/test_scheduler.py`
- Test: `backend/tests/test_realtime_search_api.py`

- [ ] **Step 1: Add tests for strategy routing**

Assert that:

- `accessStrategy.search: search_engine` routes to Browser Bridge search engine.
- `accessStrategy.detail: stealth_http` keeps using controlled HTTP fetch with impersonation/cookies.
- Challenge detection emits `source_verification_required`.
- One source result is emitted immediately without waiting for all sources.
- Search cancellation cancels pending source tasks.

- [ ] **Step 2: Implement strategy-aware routing**

The scheduler should choose the runtime path from metadata, not from ad hoc plugin fallback chains.

- [ ] **Step 3: Keep plugin parsing local**

Plugins still own HTML/JSON parsing after the runtime returns data. Do not move site-specific parsing into Browser Bridge.

- [ ] **Step 4: Run tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\source_plugins\test_scheduler.py backend\tests\test_realtime_search_api.py -q
```

Expected: Progressive search and cancellation tests pass.

---

## Task 7: Console And Aggregate Challenge UX

**Files:**
- Modify: `frontend/src/routes/SearchJobs.tsx`
- Modify: `frontend/src/routes/PluginDetail.tsx`
- Modify: `frontend/src/routes/Verification.tsx`
- Modify: `backend/app/api/console.py`
- Modify: aggregate API module under `backend/app/api/`
- Test: existing frontend build and backend API tests

- [ ] **Step 1: Add Console status display**

Show:

```text
profile id
cookie domains
cf_clearance domains
last verified time
last challenge kind
proxy binding
current session status
retry result
```

- [ ] **Step 2: Add one verification button**

The UI should not expose separate "Console CF" and "Aggregate CF" flows. Use one button that opens the session URL.

- [ ] **Step 3: Aggregate API returns local open URL**

The aggregate response must include a local URL using configured host/IP:

```text
http://<public-local-host>:8765/api/browser/challenges/{sessionId}/open
```

- [ ] **Step 4: Run frontend build**

Run:

```powershell
cd frontend; npm run build; cd ..
```

Expected: Build succeeds.

---

## Task 8: 69shuba Series Strategy Stabilization

**Files:**
- Modify: `plugins/sources/69shuba_com/metadata.yaml`
- Modify: `plugins/sources/69shuba_com/source.py`
- Modify: `plugins/sources/69shuba_tw/metadata.yaml`
- Modify: `plugins/sources/69hsw_com/metadata.yaml`
- Modify: `plugins/sources/twkan_com/metadata.yaml`
- Test: `backend/tests/test_live_acceptance.py`
- Test: source-specific tests

- [ ] **Step 1: Lock final strategy per site**

Do not leave hidden permanent fallback chains. Choose one strategy per stage based on observed live behavior.

- [ ] **Step 2: Verify 69shuba.com known detail path**

Known evidence target:

```text
https://www.69shuba.com/book/90442.htm
```

Acceptance:

```text
detail name is not empty
toc count > 20
first chapter title is not empty
chapter content length > 500
content is cleaned readable text
```

- [ ] **Step 3: Verify search path**

Search keyword:

```text
剑宗外门
```

Acceptance:

```text
search returns at least one book candidate from 69shuba_com when search engine providers are reachable
opening returned detail succeeds
toc succeeds
chapter succeeds
```

- [ ] **Step 4: Verify challenge degradation**

When search-engine providers or target site challenge pages are unavailable, result must be:

```text
source_verification_required
debug.browserChallenges includes challenge.open local URL
no opaque timeout-only failure
```

---

## Task 9: Docker And Startup Integration

**Files:**
- Create or modify Docker assets if present.
- Modify: `start.bat`
- Modify: `backend/config/source_pool.json`
- Create/Update: `docs/architecture/browser-bridge.md`

- [ ] **Step 1: Document Browserless service**

Add a Docker Compose example:

```yaml
services:
  browserless:
    image: ghcr.io/browserless/chromium
    ports:
      - "3000:3000"
    environment:
      - CONCURRENT=2
      - TIMEOUT=90000
      - TOKEN=legadohub-local
    volumes:
      - ./backend/data/browser_profiles:/data/browser_profiles
```

If the exact image/tag differs during implementation, record the verified image in `docs/architecture/browser-bridge.md`.

- [ ] **Step 2: Add startup checks**

`start.bat` should print:

```text
Console: http://127.0.0.1:8765/console
Browser Bridge: configured / not configured
Browserless: reachable / not reachable
Aggregate challenge base URL: ...
```

- [ ] **Step 3: Do not require Browserless for ordinary sources**

Backend must start when Browserless is not configured. Browser-dependent actions should return structured `browser_bridge_unavailable` errors.

---

## Task 10: Final Verification

**Files:**
- Create/Update: `docs/verification/stage-5-browserless-browser-bridge.md`
- Update tests as needed.

- [ ] **Step 1: Run targeted backend tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\test_browser_bridge_config.py backend\tests\test_browser_bridge_profiles.py backend\tests\test_browser_bridge_client.py backend\tests\test_browser_bridge_challenge.py backend\tests\test_browser_bridge_search_engine.py -q
```

Expected: All targeted Browser Bridge tests pass.

- [ ] **Step 2: Run source/plugin regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests\source_plugins backend\tests\test_realtime_search_api.py backend\tests\test_aggregate_source_plugin_runtime.py -q
```

Expected: Source runtime, progressive search, and aggregate API tests pass.

- [ ] **Step 3: Run full backend tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

Expected: Full backend suite passes or any unrelated pre-existing failures are explicitly listed with evidence.

- [ ] **Step 4: Run frontend build**

Run:

```powershell
cd frontend; npm run build; cd ..
```

Expected: Build succeeds.

- [ ] **Step 5: Run live acceptance**

Run:

```powershell
cd backend
..\.venv\Scripts\python.exe scripts\run_live_acceptance_matrix.py --plugin 69shuba_com --keyword 剑宗外门
```

Expected:

```text
rank/explore or fixed strategy discovery succeeds, or returns structured challenge session
detail succeeds for selected candidate
toc succeeds
chapter content length > 500
search-by-title repeats the same detail/toc/chapter loop
```

- [ ] **Step 6: Verify callback URL shape**

Start backend and inspect an aggregate search or challenge response. It must include:

```text
http://<local-ip-or-configured-host>:8765/api/browser/challenges/{sessionId}/open
```

The same session must be visible from Console status APIs.

- [ ] **Step 7: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected: No whitespace errors.

---

## Completion Requirements

Stage 5 is not complete unless all of these are true:

- Browserless is the selected browser runtime substrate and is documented.
- Browser Bridge has typed backend capability interfaces.
- Source metadata supports fixed access strategies.
- Search-engine access is centralized in Browser Bridge.
- Challenge session is unified across Console and aggregate-source clients.
- Automatic challenge attempt exists and degrades to manual verification without opaque timeout-only failures.
- Browser profile/cookie state is long-lived and bound to plugin/domain/proxy profile.
- 69shuba strategy is no longer a hidden multi-fallback chain.
- At least one 69shuba live path proves search/detail/toc/chapter, or returns an actionable challenge session with callback URL when blocked.
- Existing ordinary HTTP sources still work without Browserless configured.

## Self-Review

- Spec coverage: This plan covers Browserless selection, fixed source strategies, Browser Bridge interfaces, unified callback session, Console/aggregate reuse, long-lived cookies/profile, search-engine centralization, and 69shuba live acceptance.
- Placeholder scan: No `TBD`, `TODO`, or unspecified "handle later" steps remain.
- Type consistency: `accessStrategy`, `searchEngine`, `BrowserBridgeConfig`, `BrowserFetchRequest`, `BrowserFetchResult`, `challenge.session`, `challenge.open`, `challenge.callback`, and `challenge.retry` are used consistently.
