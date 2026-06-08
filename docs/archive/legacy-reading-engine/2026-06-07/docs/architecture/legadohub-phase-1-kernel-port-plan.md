# LegadoHub Direct Reading Kernel Port Implementation Plan

> **Superseded on 2026-06-07:** This plan is now a historical reference for the JVM direct-port direction. The active restart direction is `docs/architecture/plugin-source-runtime-restart-plan.md`: LegadoHub moves internal source execution to self-maintained Python source plugins.
>
> **For agentic workers:** This document is no longer the active architecture source of truth. Use it only to understand the previous Reading-kernel-port plan and the assets that may still be retained.

**Goal:** Replace the experimental self-written Reading parser route with a Kotlin/JVM engine that directly ports Luoyacheng/legado source execution semantics.

**Architecture:** Keep Python as service orchestration plus final article/content post-processing. Port upstream Reading BookSource execution files into `engine-jvm`, preserve upstream control flow where possible, and replace Android dependencies with backend runtime interfaces. Delete self-written engine code when the direct port covers the same responsibility.

**Tech Stack:** Kotlin/JVM 2.x, Java 17, kotlinx.coroutines, kotlinx.serialization, OkHttp, Rhino-compatible JS runtime, Jsoup/JSONPath only when upstream code already uses equivalent behavior, Kotest/JUnit tests, Python/FastAPI bridge in the next phase.

---

## Phase 1 Definition Of Done

Phase 1 is complete only when all of these are true:

- The upstream baseline commit is recorded and verified locally.
- The engine contains direct upstream-derived code for BookSource, AnalyzeUrl, AnalyzeRule, JS extension setup, and WebBook search/detail/toc/content flow.
- Android-only dependencies are replaced by small backend adapters or compatibility shims.
- The self-written parser path is deleted or disabled as non-core scaffolding.
- XIU2/Yuedu source snapshot imports as 26 independent BookSource objects.
- At least one simple source chain passes through the direct port path: search -> detail -> toc -> content.
- At least one JS-extension rule test proves the selected JS runtime can execute an upstream-style helper.
- Batch search accepts a list of sources, runs in Kotlin, emits progress events, and enforces timeout/concurrency limits.
- CLI or process bridge exposes version, parse-source, and batch-search smoke commands.
- `:engine-jvm:test` passes with Java 17.

Phase 1 is not complete because JVM implements every display-side cleanup behavior from the Reading App. It is complete when source-rule execution can fetch and extract search/detail/toc/content/explore data with traceable failures. Final article cleanup is a Python layer.

## Layer Boundary For This Plan

`engine-jvm` owns source execution:

- BookSource import and identity.
- `AnalyzeUrl` request construction.
- `AnalyzeRule` selector and JS-chain extraction.
- Search/detail/toc/content/explore/ranking execution.
- Cookies, source variables, proxy flags, WebView-required signaling, source trace, and failure classification.
- Extraction-critical JS helpers, including HTTP helpers such as `java.ajax`.

Python owns post-extraction article handling:

- Final `replaceRegex` policy, ad cleanup, paragraph normalization, whitespace/layout cleanup, display title decoration, and user reading preferences.
- Aggregation sorting, cache/fallback orchestration, response shaping, and admin/UI state.
- Any user-configurable cleanup that should not change BookSource compatibility.

Boundary rule:

- If the behavior changes whether a source can request, parse, or produce a structured field, it belongs in `engine-jvm`.
- If the behavior only changes the final chapter text after extraction, it belongs in Python.

## Non-Goals

- Do not build the new web admin UI in Phase 1.
- Do not add new Python parser features.
- Do not preserve backward compatibility with deleted experimental parser APIs.
- Do not convert Kotlin upstream code to Java.
- Do not group multiple BookSource objects by website host.
- Do not claim real source compatibility from mock-only tests.
- Do not continue a full upstream `ContentProcessor` port in Phase 1.
- Do not move article display/user-preference cleanup into `engine-jvm`.

## Required Commands

Use these commands from `C:\Home\Workspace\UGit\legado-hub`.

```powershell
$env:JAVA_HOME='C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot'
$env:Path="$env:JAVA_HOME\bin;$env:Path"
$env:GRADLE_OPTS=''
git -C data\upstreams\luoyacheng-legado rev-parse HEAD
data\upstreams\luoyacheng-legado\gradlew.bat -p . :engine-jvm:test --no-daemon
```

Expected upstream commit:

```text
44e07fea541287804cc58d0168940a756cd11cfd
```

## File Map

### Create

- `engine-jvm/src/main/kotlin/legadohub/engine/compat/AndroidCompat.kt`
  - Small JVM replacements for Android APIs that upstream code references.
- `engine-jvm/src/main/kotlin/legadohub/engine/runtime/EngineRuntime.kt`
  - HTTP, cookie, cache, logger, source variable, WebView, and JS runtime boundaries.
- `engine-jvm/src/main/kotlin/legadohub/engine/bridge/EngineBridgeModels.kt`
  - Serializable request/response models for CLI and later socket/gRPC bridge.
- `engine-jvm/src/main/kotlin/legadohub/engine/bridge/EngineCli.kt`
  - Thin command entrypoint.
- `engine-jvm/src/test/kotlin/legadohub/engine/port/`
  - Direct port semantic tests.
- `engine-jvm/src/test/kotlin/legadohub/engine/bridge/`
  - CLI/bridge tests.

### Port From Upstream

Port these files from `data/upstreams/luoyacheng-legado/app/src/main/java/io/legado/app/` with package names preserved where practical:

- `data/entities/BaseSource.kt`
- `data/entities/BookSource.kt`
- `data/entities/rule/SearchRule.kt`
- `data/entities/rule/BookInfoRule.kt`
- `data/entities/rule/TocRule.kt`
- `data/entities/rule/ContentRule.kt`
- `model/analyzeRule/AnalyzeUrl.kt`
- `model/analyzeRule/AnalyzeRule.kt`
- `model/analyzeRule/AnalyzeRuleHelper.kt`
- `model/analyzeRule/JsExtensions.kt`
- `model/webBook/WebBook.kt`
- `model/webBook/BookList.kt`
- `model/webBook/BookInfo.kt`
- `model/webBook/BookChapterList.kt`
- `model/webBook/BookContent.kt`

If a ported file needs many Android dependencies, keep the upstream file shape and move the dependency replacement into `legadohub.engine.compat` or `legadohub.engine.runtime`.

### Delete Or Disable

Delete these once the direct port replacement compiles:

- `engine-jvm/src/main/kotlin/legadohub/engine/rule/AnalyzeRuleParser.kt`
- `engine-jvm/src/main/kotlin/legadohub/engine/url/AnalyzeUrlParser.kt`
- `engine-jvm/src/main/kotlin/legadohub/engine/pipeline/WebBookPipeline.kt`
- Tests that only validate the self-written parser behavior.

Do not keep both paths active.

## Task 1: Lock Upstream And Inventory Dependencies

**Files:**
- Modify: `docs/architecture/upstream-legado-source-baseline.md`

- [ ] **Step 1: Verify upstream commit**

Run:

```powershell
git -C data\upstreams\luoyacheng-legado rev-parse HEAD
```

Expected:

```text
44e07fea541287804cc58d0168940a756cd11cfd
```

- [ ] **Step 2: Record direct-port file list**

Update `docs/architecture/upstream-legado-source-baseline.md` with the exact upstream files listed in the File Map above.

- [ ] **Step 3: Record dependency replacement table**

The table must include:

```text
android.util.Log -> EngineLogger
android.content.Context -> EngineConfig / removed call site
android.webkit.WebView -> WebViewRuntime
Room entities -> kotlinx.serialization data classes / Python DB mapping
Parcelable -> removed on JVM
AppConfig -> EngineConfig
AppLog -> EngineLogger
CookieStore -> EngineCookieStore
CacheManager -> EngineCache
OkHttp helpers -> EngineHttpRuntime backed by OkHttp
Rhino JS setup -> EngineJsRuntime with upstream JsExtensions
```

## Task 2: Replace Engine Direction In Gradle Module

**Files:**
- Modify: `engine-jvm/build.gradle.kts`
- Modify: `settings.gradle.kts`

- [ ] **Step 1: Keep module version at 0.0.1**

`engine-jvm/build.gradle.kts` must contain:

```kotlin
group = "legadohub"
version = "0.0.1"
```

- [ ] **Step 2: Add dependencies required by the port**

The module must include at least:

```kotlin
implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.9.0")
implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
implementation("com.squareup.okhttp3:okhttp:4.12.0")
implementation("org.jsoup:jsoup:1.18.3")
implementation("com.jayway.jsonpath:json-path:2.9.0")
implementation("org.mozilla:rhino:1.7.15")
testImplementation("io.kotest:kotest-runner-junit5:5.9.1")
testImplementation("io.kotest:kotest-assertions-core:5.9.1")
```

- [ ] **Step 3: Keep executable bridge packaging**

`application.mainClass` must point to the final CLI entrypoint:

```kotlin
application {
    mainClass.set("legadohub.engine.bridge.EngineCliKt")
}
```

## Task 3: Build Backend Runtime Boundary

**Files:**
- Create: `engine-jvm/src/main/kotlin/legadohub/engine/runtime/EngineRuntime.kt`
- Test: `engine-jvm/src/test/kotlin/legadohub/engine/runtime/EngineRuntimeTest.kt`

- [ ] **Step 1: Define runtime interfaces**

Create interfaces with these responsibilities:

```kotlin
interface EngineHttpRuntime {
    suspend fun execute(request: EngineHttpRequest): EngineHttpResponse
}

interface EngineCookieStore {
    suspend fun get(sourceId: String, url: String): String?
    suspend fun put(sourceId: String, url: String, cookie: String)
}

interface EngineCache {
    suspend fun get(key: String): String?
    suspend fun put(key: String, value: String, ttlSeconds: Long? = null)
    suspend fun remove(key: String)
}

interface EngineLogger {
    fun trace(sourceId: String, stage: String, message: String)
    fun warn(sourceId: String, stage: String, message: String)
    fun error(sourceId: String, stage: String, message: String, cause: Throwable? = null)
}

interface WebViewRuntime {
    suspend fun render(request: WebViewRequest): WebViewResult
}
```

- [ ] **Step 2: Add explicit unsupported WebView result**

The default backend WebView implementation must return:

```kotlin
WebViewResult(
    ok = false,
    errorCode = "WEBVIEW_REQUIRED",
    message = "This source requires WebView runtime"
)
```

- [ ] **Step 3: Test runtime contracts**

Add tests that instantiate fake runtime implementations and assert method calls preserve source id, URL, timeout, proxy, and headers.

## Task 4: Direct-Port BookSource And Rule Models

**Files:**
- Port: upstream BookSource/BaseSource/rule model files
- Test: `engine-jvm/src/test/kotlin/legadohub/engine/port/BookSourcePortTest.kt`

- [ ] **Step 1: Port models with Reading JSON field names**

The port must preserve field names such as:

```text
bookSourceUrl
bookSourceName
bookSourceGroup
searchUrl
exploreUrl
ruleSearch
ruleBookInfo
ruleToc
ruleContent
```

- [ ] **Step 2: Keep `bookSourceUrl` as identity**

Add a test:

```kotlin
source.bookSourceUrl shouldBe source.getKey()
```

If upstream uses a different helper name, wrap it without changing the identity rule.

- [ ] **Step 3: Validate XIU2/Yuedu import**

Test:

```kotlin
val sources = parser.parseMany(Files.readString(path))
sources shouldHaveSize 26
sources.distinctBy { it.bookSourceUrl } shouldHaveSize 26
sources.first().bookSourceName shouldBe "起点中文"
sources.first().bookSourceUrl shouldBe "https://www.qidian.com"
```

## Task 5: Direct-Port AnalyzeUrl

**Files:**
- Port: `model/analyzeRule/AnalyzeUrl.kt`
- Create adapters under `legadohub/engine/compat/`
- Test: `engine-jvm/src/test/kotlin/legadohub/engine/port/AnalyzeUrlPortTest.kt`

- [ ] **Step 1: Copy upstream control flow first**

Do not rewrite option parsing from scratch. Start from upstream `AnalyzeUrl.kt`, then replace Android/app globals through constructor-injected runtime/config.

- [ ] **Step 2: Preserve Reading URL options**

Tests must cover:

```text
method
charset
headers
body
retry
type
webView
webJs
dnsIp
js
bodyJs
serverID
webViewDelayTime
proxy
```

- [ ] **Step 3: Preserve variable replacement**

Tests must cover:

```text
{{key}}
{{page}}
{{title}}
{{author}}
custom variables
```

## Task 6: Direct-Port AnalyzeRule And JS Extensions

**Files:**
- Port: `model/analyzeRule/AnalyzeRule.kt`
- Port: `model/analyzeRule/AnalyzeRuleHelper.kt`
- Port: `model/analyzeRule/JsExtensions.kt`
- Test: `engine-jvm/src/test/kotlin/legadohub/engine/port/AnalyzeRulePortTest.kt`
- Test: `engine-jvm/src/test/kotlin/legadohub/engine/port/JsExtensionsPortTest.kt`

- [ ] **Step 1: Add Rhino dependency and runtime wrapper**

Use Rhino first because Reading semantics and existing extension style are closer to Rhino than to Python simulation.

- [ ] **Step 2: Preserve selector behavior**

Tests must cover:

```text
CSS text/html/attr
XPath text/attr
JsonPath
Regex
fallback ruleA||ruleB
replace rule##pattern##replacement
```

- [ ] **Step 3: Preserve JS extension names**

Tests must cover at least:

```text
java.ajax
base64Encode
base64Decode
md5
```

If a helper cannot be implemented immediately, the test must assert a structured unsupported reason from the direct port, not silent empty output.

## Task 7: Direct-Port WebBook Flow

**Files:**
- Port: `model/webBook/WebBook.kt`
- Port: `model/webBook/BookList.kt`
- Port: `model/webBook/BookInfo.kt`
- Port: `model/webBook/BookChapterList.kt`
- Port: `model/webBook/BookContent.kt`
- Test: `engine-jvm/src/test/kotlin/legadohub/engine/port/WebBookPortChainTest.kt`

- [ ] **Step 1: Replace Android app dependencies with runtime adapters**

All network, cache, log, config, cookie, and WebView calls must go through `legadohub.engine.runtime`.

- [ ] **Step 2: Test complete chain**

Use one fake source and fake HTTP runtime:

```text
search -> detail -> toc -> content
```

Expected:

```text
Search returns a book with absolute bookUrl.
Detail returns tocUrl.
Toc returns at least one chapter with absolute chapterUrl.
Content returns non-empty chapter text.
Trace records each stage.
```

- [ ] **Step 3: Test failure classification**

Tests must classify:

```text
HTTP_4XX
HTTP_5XX
PARSE_EMPTY
WEBVIEW_REQUIRED
LOGIN_REQUIRED
JS_ERROR
SOURCE_TIMEOUT
```

- [ ] **Step 4: Keep content cleanup out of this task**

Do not port the full Reading `ContentProcessor` here. Keep only behavior needed for extraction correctness, such as fetching `nextContentUrl` pages or honoring simple source-defined cleanup already needed by current tests. Plan final cleanup in Python.

## Task 8: Kotlin Batch Execution

**Files:**
- Create: `engine-jvm/src/main/kotlin/legadohub/engine/batch/BatchSearchExecutor.kt`
- Create: `engine-jvm/src/main/kotlin/legadohub/engine/batch/BatchModels.kt`
- Test: `engine-jvm/src/test/kotlin/legadohub/engine/batch/BatchSearchExecutorTest.kt`

- [ ] **Step 1: Set defaults**

Defaults:

```text
batchSize = 20
globalConcurrency = 20
perHostConcurrency = 2
sourceTimeoutMillis = 15000
requestTimeoutMillis = 8000
```

- [ ] **Step 2: Emit progress events**

Events:

```text
BatchStarted
SourceStarted
SourceResult
SourceFailed
SourceTimedOut
BatchFinished
```

- [ ] **Step 3: Test concurrency**

Use fake runtimes and assert:

```text
Only first 20 enabled sources run by default.
Per-host active count never exceeds 2.
Timed out source returns SourceTimedOut.
Successful sources stream partial result events.
```

## Task 9: Bridge CLI

**Files:**
- Create: `engine-jvm/src/main/kotlin/legadohub/engine/bridge/EngineCli.kt`
- Create: `engine-jvm/src/main/kotlin/legadohub/engine/bridge/EngineBridgeModels.kt`
- Test: `engine-jvm/src/test/kotlin/legadohub/engine/bridge/EngineCliTest.kt`

- [ ] **Step 1: Implement commands**

Commands:

```text
version
parse-source <path>
batch-search <request-json-path>
```

- [ ] **Step 2: Print UTF-8 JSON**

`main` must set stdout and stderr to UTF-8:

```kotlin
System.setOut(PrintStream(System.out, true, StandardCharsets.UTF_8))
System.setErr(PrintStream(System.err, true, StandardCharsets.UTF_8))
```

- [ ] **Step 3: Test CLI output**

Tests must assert:

```text
version -> 0.0.1
parse-source XIU2 snapshot -> count 26
batch-search fake request -> progress and result JSON
```

## Task 10: Remove Self-Written Parser Path

**Files:**
- Delete or disable old self-written parser files listed above.
- Modify tests that referenced them.

- [ ] **Step 1: Search for old parser references**

Run:

```powershell
rg "AnalyzeRuleParser|AnalyzeUrlParser|WebBookPipeline|app/legado_engine" .
```

- [ ] **Step 2: Delete duplicate core code**

Delete old parser files after the direct port tests pass.

- [ ] **Step 3: Keep only bridge-compatible wrappers**

If Python needs stable output shapes, implement wrappers around the direct port, not compatibility layers around old parser behavior.

## Task 11: Final Verification

**Files:**
- Create: `docs/verification/phase-1-direct-kernel-port.md`

- [ ] **Step 1: Run JVM tests**

```powershell
$env:JAVA_HOME='C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot'
$env:Path="$env:JAVA_HOME\bin;$env:Path"
$env:GRADLE_OPTS=''
data\upstreams\luoyacheng-legado\gradlew.bat -p . :engine-jvm:test --no-daemon
```

Expected:

```text
BUILD SUCCESSFUL
```

- [ ] **Step 2: Run CLI smoke**

```powershell
java -jar engine-jvm\build\libs\engine-jvm-0.0.1.jar version
java -jar engine-jvm\build\libs\engine-jvm-0.0.1.jar parse-source data\sources\raw\by-site\legado\sub-xiu2_yuedu.json
```

Expected:

```text
0.0.1
JSON count = 26
```

- [ ] **Step 3: Write verification report**

Report must include:

```text
Upstream commit
Ported file list
Adapter list
Deleted old parser files
Test command outputs
CLI smoke outputs
Known unsupported source categories
Next Phase 2 bridge tasks
```

## Execution Rule

If implementation pressure appears, do not shorten this plan into a minimum parser. The shortcut is the old failed route. Phase 1 is allowed to be large because it is the foundation for all later source compatibility.
