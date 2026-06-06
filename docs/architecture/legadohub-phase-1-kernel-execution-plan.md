# LegadoHub Reading Kernel Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent Kotlin/JVM Reading-compatible kernel for LegadoHub so Python/FastAPI can call a real source execution engine instead of extending the old approximate Python parser.

**Architecture:** Keep Python as orchestration and management, but move BookSource execution semantics into `engine-jvm`. The JVM module mirrors Reading source semantics, replaces Android dependencies with backend runtime interfaces, and returns structured results with trace and unsupported reasons.

**Tech Stack:** Kotlin/JVM 2.0.21, Java 17 toolchain, kotlinx.serialization, kotlinx.coroutines, OkHttp, Jsoup, JsonPath, Kotest, Python/FastAPI integration in later phases.

---

## File Structure

- `settings.gradle.kts`
  - Root Gradle settings and `:engine-jvm` inclusion.
- `build.gradle.kts`
  - Shared Kotlin plugin versions.
- `engine-jvm/build.gradle.kts`
  - JVM module dependencies and test configuration.
- `engine-jvm/src/main/kotlin/legadohub/engine/model/`
  - Reading-compatible source and execution result models.
- `engine-jvm/src/main/kotlin/legadohub/engine/source/`
  - BookSource import and source-level header parsing.
- `engine-jvm/src/main/kotlin/legadohub/engine/runtime/`
  - Backend runtime interfaces replacing Android dependencies.
- `engine-jvm/src/main/kotlin/legadohub/engine/url/`
  - AnalyzeUrl extraction and request preparation.
- `engine-jvm/src/main/kotlin/legadohub/engine/rule/`
  - AnalyzeRule extraction for CSS/JsonPath/Regex and structured gaps.
- `engine-jvm/src/test/kotlin/legadohub/engine/`
  - Kotest coverage for every kernel boundary.
- `docs/architecture/upstream-legado-source-baseline.md`
  - Fixed upstream commit, source entry points, Android replacement map.

## Commands

Use these commands from `C:/Home/Workspace/UGit/legado-hub`.

```powershell
git -C data\upstreams\luoyacheng-legado fetch --all --prune
git -C data\upstreams\luoyacheng-legado pull --ff-only
git -C data\upstreams\luoyacheng-legado rev-parse HEAD
```

If no root Gradle wrapper exists, use the upstream wrapper against this root project:

```powershell
$env:JAVA_HOME = "<JDK 根目录>"
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
data\upstreams\luoyacheng-legado\gradlew.bat -p . :engine-jvm:test
```

Later, after Python integration resumes:

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

## Task 1: Lock Upstream Baseline

**Files:**
- Create: `docs/architecture/upstream-legado-source-baseline.md`

- [x] **Step 1: Record upstream repository and commit**

Expected commit for this execution:

```text
44e07fea541287804cc58d0168940a756cd11cfd
```

- [x] **Step 2: Record source files used as semantic truth**

Include `BookSource.kt`, `BaseSource.kt`, `AnalyzeUrl.kt`, `AnalyzeRule.kt`, selector engines, `WebBook.kt`, import view model, and `modules/web`.

- [x] **Step 3: Record Android replacement map**

Map Room/Parcelable, OkHttp helpers, CookieStore, CacheManager, Rhino, BackstageWebView, AppConfig, AppLog to JVM backend interfaces.

## Task 2: Create JVM Kernel Module

**Files:**
- Create: `settings.gradle.kts`
- Create: `build.gradle.kts`
- Create: `engine-jvm/build.gradle.kts`

- [x] **Step 1: Add `:engine-jvm` Gradle module**

Root `settings.gradle.kts` must include:

```kotlin
include(":engine-jvm")
```

- [x] **Step 2: Add dependencies**

`engine-jvm` must include kotlinx.serialization, coroutines, OkHttp, Jsoup, JsonPath, and Kotest.

- [ ] **Step 3: Run tests**

```powershell
data\upstreams\luoyacheng-legado\gradlew.bat -p . :engine-jvm:test
```

Expected: tests run. Current machine blocks here until a JDK is installed or `JAVA_HOME` is set.

## Task 3: Implement BookSource Import Identity

**Files:**
- Create: `engine-jvm/src/main/kotlin/legadohub/engine/model/BookSource.kt`
- Create: `engine-jvm/src/main/kotlin/legadohub/engine/source/BookSourceParser.kt`
- Test: `engine-jvm/src/test/kotlin/legadohub/engine/source/BookSourceParserTest.kt`

- [x] **Step 1: Model Reading fields**

Keep JSON names such as `bookSourceUrl`, `bookSourceName`, `bookSourceGroup`, `searchUrl`, `exploreUrl`, `ruleSearch`, `ruleBookInfo`, `ruleToc`, `ruleContent`.

- [x] **Step 2: Use `bookSourceUrl` as identity**

`BookSource.sourceId` returns `bookSourceUrl`.

- [x] **Step 3: Parse single object and arrays**

`BookSourceParser.parseMany` must treat each array element as an independent source.

## Task 4: Add Runtime Interfaces

**Files:**
- Create: `engine-jvm/src/main/kotlin/legadohub/engine/runtime/RuntimeContracts.kt`

- [x] **Step 1: Add HTTP runtime boundary**

Create `HttpRuntime`, `EngineHttpRequest`, and `EngineHttpResponse`.

- [x] **Step 2: Add state runtime boundaries**

Create `CookieStore`, `SourceVariableStore`, and `EngineCache`.

- [x] **Step 3: Add WebView and logging boundaries**

Create `WebViewRuntime`, `UnsupportedWebViewRuntime`, and `EngineLogger`.

## Task 5: Port AnalyzeUrl First Slice

**Files:**
- Create: `engine-jvm/src/main/kotlin/legadohub/engine/url/AnalyzeUrlModels.kt`
- Create: `engine-jvm/src/main/kotlin/legadohub/engine/url/AnalyzeUrlParser.kt`
- Test: `engine-jvm/src/test/kotlin/legadohub/engine/url/AnalyzeUrlParserTest.kt`

- [x] **Step 1: Replace simple inline variables**

Support `{{key}}`, `{{page}}`, `{{title}}`, `{{author}}`, and explicit `variables`.

- [x] **Step 2: Parse Reading URL options**

Support method, charset, headers, body, retry, type, webView, webJs, dnsIp, js, bodyJs, serverID, webViewDelayTime, and proxy.

- [x] **Step 3: Merge source and option headers**

Source header is loaded first. URL option headers override source headers. `proxy` is extracted as a proxy hint rather than sent as an HTTP header.

- [x] **Step 4: Mark unsupported runtime features**

Return `UnsupportedReason` for WebView, JavaScript URL transforms, bodyJs, and login headers.

## Task 6: Port AnalyzeRule First Slice

**Files:**
- Create: `engine-jvm/src/main/kotlin/legadohub/engine/rule/AnalyzeRuleModels.kt`
- Create: `engine-jvm/src/main/kotlin/legadohub/engine/rule/AnalyzeRuleParser.kt`
- Test: `engine-jvm/src/test/kotlin/legadohub/engine/rule/AnalyzeRuleParserTest.kt`

- [x] **Step 1: Add CSS extraction**

Support `selector@text`, `selector@html`, `selector@outerHtml`, and `selector@attrName`.

- [x] **Step 2: Add JsonPath extraction**

Support rules beginning with `$`.

- [x] **Step 3: Add Regex extraction**

Support `regex:<pattern>` and return the first capture group when present.

- [x] **Step 4: Add fallback and replace**

Support `ruleA||ruleB` and `rule##pattern##replacement`.

- [x] **Step 5: Mark JavaScript and XPath gaps**

Return structured unsupported reasons for JavaScript and XPath until the next slice implements them fully.

## Task 7: Next Required Kernel Slice

**Files:**
- Modify: `engine-jvm/src/main/kotlin/legadohub/engine/rule/AnalyzeRuleParser.kt`
- Create: `engine-jvm/src/main/kotlin/legadohub/engine/pipeline/WebBookPipeline.kt`
- Create: `engine-jvm/src/test/kotlin/legadohub/engine/pipeline/WebBookPipelineTest.kt`

- [ ] **Step 1: Add XPath adapter**

Use a JVM HTML XPath adapter compatible with parsed Jsoup documents. Test `xpath://h1/text()` and attribute extraction.

- [ ] **Step 2: Add search pipeline**

Build `search(source, keyword, page)` from `source.searchUrl` + `ruleSearch`. Return items, trace, unsupported, and latency.

- [ ] **Step 3: Add detail/toc/content pipeline**

Port the minimal `WebBook` flow only after `search` is testable.

- [ ] **Step 4: Add batch execution**

Add batch defaults: `batchSize=20`, `globalConcurrency=20`, `perHostConcurrency=2`, `sourceTimeout=15s`, `requestTimeout=8s`.

## Current Environment Blocker

The current machine has no `java` or `gradle` on PATH, and no JDK was found in common `Program Files` JDK/JBR locations. Do not claim Phase 1 tests pass until this command runs successfully:

```powershell
data\upstreams\luoyacheng-legado\gradlew.bat -p . :engine-jvm:test
```
