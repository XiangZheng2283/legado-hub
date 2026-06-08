# Phase 1 Direct Reading Kernel Port Verification

Date: 2026-06-06

## Scope

This report verifies the current Phase 1 Kotlin/JVM direct-port slice for LegadoHub.

The project direction is:

- Python/FastAPI remains the orchestration layer.
- `engine-jvm` owns Reading `BookSource` execution.
- The old self-written parser path is no longer the core engine path.
- `bookSourceUrl` remains the BookSource identity.
- XIU2/Yuedu remains the initial built-in source snapshot.

## Layer Boundary

The current architecture separates two concerns:

- `engine-jvm` owns BookSource execution and raw structured extraction. This includes request construction, rule-chain parsing, selector execution, extraction-critical JS helpers, cookies, source variables, trace, and failure classification.
- Python owns final article/content post-processing after extraction. This includes final `replaceRegex` policy, ad cleanup, paragraph normalization, user reading preferences, aggregation fallback, cache orchestration, and API/UI response shaping.

Boundary rule:

- Implement behavior in JVM when it is required to request a source, parse a source field, or return structured search/detail/toc/content/explore data.
- Implement behavior in Python when it only changes the final article text or presentation after source extraction.

## Upstream Baseline

Local upstream checkout:

```text
C:/Home/Workspace/UGit/legado-hub/data/upstreams/luoyacheng-legado
```

Verified command:

```powershell
git -C data\upstreams\luoyacheng-legado rev-parse HEAD
```

Verified output:

```text
44e07fea541287804cc58d0168940a756cd11cfd
```

## Ported Engine Surface

Current direct-port package surface:

- `io.legado.app.data.entities.BaseSource`
- `io.legado.app.data.entities.BookSource`
- `io.legado.app.data.entities.Book`
- `io.legado.app.data.entities.SearchBook`
- `io.legado.app.data.entities.BookChapter`
- `io.legado.app.data.entities.rule.*`
- `io.legado.app.data.entities.rule.ExploreKind`
- `io.legado.app.model.analyzeRule.RuleData`
- `io.legado.app.model.analyzeRule.RuleDataInterface`
- `io.legado.app.model.analyzeRule.RuleAnalyzer`
- `io.legado.app.model.analyzeRule.AnalyzeByJSoup`
- `io.legado.app.model.analyzeRule.AnalyzeByXPath`
- `io.legado.app.model.analyzeRule.AnalyzeByJSonPath`
- `io.legado.app.model.analyzeRule.AnalyzeByRegex`
- `io.legado.app.model.analyzeRule.AnalyzeUrl`
- `io.legado.app.model.analyzeRule.AnalyzeRule`
- `io.legado.app.help.JsExtensions`
- `io.legado.app.help.ConcurrentRateLimiter`
- `io.legado.app.utils.ChineseUtils`
- `io.legado.app.model.webBook.WebBook`
- `io.legado.app.model.webBook.BookList`
- `io.legado.app.model.webBook.BookInfo`
- `io.legado.app.model.webBook.BookChapterList`
- `io.legado.app.model.webBook.BookContent`

Current LegadoHub adapter surface:

- `legadohub.engine.runtime.EngineHttpRuntime`
- `legadohub.engine.runtime.EngineHttpStatusException`
- `legadohub.engine.runtime.EngineSourceExecutionException`
- `legadohub.engine.runtime.EngineTraceEvent`
- `legadohub.engine.runtime.EngineCookieStore`
- `legadohub.engine.runtime.EngineCacheV2`
- `legadohub.engine.runtime.EngineSourceVariableStore`
- `legadohub.engine.runtime.EngineLoggerV2`
- `legadohub.engine.runtime.WebViewRuntimeV2`
- `legadohub.engine.runtime.UnsupportedWebViewRuntimeV2`
- `legadohub.engine.runtime.OkHttpEngineRuntime`
- `legadohub.engine.runtime.StaticHttpRuntime`
- `legadohub.engine.batch.BatchSearchRunner`
- `legadohub.engine.bridge.EngineCli`

## Deleted Old Core Path

The old self-written parser files have been removed from the active engine source tree:

- `legadohub.engine.rule.AnalyzeRuleParser`
- `legadohub.engine.url.AnalyzeUrlParser`
- `legadohub.engine.pipeline.WebBookPipeline`
- Old parser/pipeline/source-header tests that only validated the deleted path

Search command:

```powershell
rg "AnalyzeRuleParser|AnalyzeUrlParser|WebBookPipeline" engine-jvm docs app tests -S
```

Current matches are documentation references only.

## Verified Behaviors

BookSource import:

- Parses single source JSON.
- Parses source arrays.
- Keeps Reading field names.
- Uses `bookSourceUrl` as identity.
- Imports XIU2/Yuedu snapshot as 26 independent `BookSource` objects.

AnalyzeUrl:

- Executes Reading-style URL `@js:` and `<js>...</js>` fragments through the same Rhino-backed JS runtime used by `AnalyzeRule`.
- Evaluates embedded `{{...}}` URL expressions with `key`, `keyword`, `page`, and custom variables available as JS bindings.
- Resolves relative URLs.
- Handles GET query encoding and POST form body encoding.
- Preserves URL options including method, charset, headers, body, retry, type, proxy, serverID, webViewDelayTime.
- Executes URL option `js` to rewrite the final request URL before query/form encoding.
- Emits structured unsupported markers for webView/webJs/bodyJs/dnsIp requirements.

AnalyzeRule and JS:

- `AnalyzeRule` delegates selector work to `RuleAnalyzer` and `AnalyzeBy*` helpers.
- `RuleAnalyzer` covers balanced splitting for `&&`, `||`, `%%`, `@`, and quoted/bracketed rule text.
- `AnalyzeByJSoup` covers JSoup extraction, fallback, interleaving merge, `@CSS:` mode, `textNodes`, `ownText`, `html`, attributes, Reading-style indexes, ranges, exclusions, and negative indexes.
- `AnalyzeByJSonPath` covers fallback and interleaving merge over JsonPath values.
- `AnalyzeByXPath` covers XPath text and attribute extraction through Jsoup XPath.
- `AnalyzeByRegex` covers capture groups and chained extraction.
- CSS text/html/attr.
- XPath text/attr.
- JsonPath.
- Regex capture.
- Fallback `ruleA || ruleB`.
- Replace `rule##pattern##replacement`.
- Rhino execution for `@js:` / `<js>`.
- JS helper coverage for `base64Encode`, `base64Decode`, `md5`, `md5Encode`, `md5Encode16`, `hexEncodeToString`, `hexDecodeToString`, `encodeURI`, `timeFormat`, `timeFormatUTC`, `strToBytes`, `bytesToStr`, `randomUUID`, `androidId`, `toast`, `longToast`, `log`, and `logType`.
- JS crypto helper coverage includes AES/DES base64 encode/decode paths used by XIU2/Yuedu, including `AES/CBC/PKCS5Padding` and `DES/CBC/PKCS5Padding`.
- JS context exposes `baseUrl`, `src`, `book`, and `chapter` where available.
- `java.put(key, value)` / `java.get(key)` bridge `AnalyzeRule` variables and support special keys `bookName` and `title`.
- `java.t2s(text)` and `java.s2t(text)` are wired to the same quick-transfer Chinese conversion library used by upstream Reading.
- Source JS helpers expose `source.setVariable(value)`, `source.putVariable(value)`, `source.getVariable()`, `source.put(key, value)`, and `source.get(key)` through an in-memory JVM store.
- JS selector helpers include `java.getString(rule)`, `java.getElement(rule)`, and `java.setContent(content, baseUrl?)`.
- `java.getElement(rule)` returns a JVM wrapper usable from Rhino with `.length`, `.toArray()`, `.text()`, `.html()`, `.attr(name)`, and `.get(index)`.
- `java.ajax` returns structured unsupported text when no HTTP runtime is injected.
- `java.ajax` can execute through `EngineHttpRuntime` when `AnalyzeRule` or `WebBook` is constructed with runtime support.
- `java.ajax` supports Rhino JS object requests with `url`/`href`, `method`, `headers`, `body`, `charset`, `proxy`, `timeout`, and `timeoutMs`.
- `java.ajax(url, timeout)` maps the timeout overload into `EngineHttpRequestV2.timeoutMs`.
- `java.ajaxAll([...])` executes a Rhino JS array of URLs or request objects through `EngineHttpRuntime` and returns response wrappers with `.body()`, `.header(name)`, `.cookie(name)`, `.statusCode()`, and `.url()`.
- `java.ajaxTestAll([...], timeout)` executes the same request shapes as `ajaxAll` and applies the supplied timeout to each request.
- `java.connect(url)`, `java.connect(url, headerJson)`, and `java.connect(url, headerJson, timeout)` return response wrappers through the same runtime boundary.
- Source `concurrentRate` is applied to JS HTTP helpers through a JVM `ConcurrentRateLimiter`.
- `concurrentRate = N` and `concurrentRate = N/T` forms are parsed; `ajaxAll(..., true)` and `ajaxTestAll(..., timeout, true)` skip rate limiting like upstream's `skipRateLimit`.
- `java.ajax` bridges cookies through `EngineCookieStore`: stored cookies are attached to outgoing requests, and response `Set-Cookie` is written back.
- `java.get(url, headers)`, `java.head(url, headers)`, and `java.post(url, body, headers)` execute through `EngineHttpRuntime` and return response wrappers with `.body()`, `.header(name)`, `.headers()`, `.cookie(name)`, `.statusCode()`, `.code()`, `.message()`, `.isSuccessful()`, `.callTime()`, `.raw()`, and `.url()`.
- JS cookie bridge exposes `cookie.getCookie(url)`, `cookie.setCookie(url, cookie)`, `cookie.removeCookie(url)`, and `java.getCookie(url, key?)` over `EngineCookieStore`.
- Interactive helpers that need a user/browser runtime return structured unsupported values instead of missing-method crashes: `java.startBrowserAwait(...)` and `java.getVerificationCode(...)`.

WebBook flow:

- Fake HTTP runtime verifies search -> detail -> toc -> content.
- Explore/ranking execution now has a direct `WebBook.exploreBookAwait(source, url, page)` entrypoint.
- Explore category parsing supports plain Reading forms such as `title::url` separated by newlines/`&&`.
- Explore category parsing supports JSON array forms for `ExploreKind` fields needed by the backend contract: `title`, `url`, `type`, `action`, `chars`, `default`, and `viewName`.
- Explore requests execute through `AnalyzeUrl`, including page replacement and runtime/cookie wiring, then parse results through `ruleExplore`.
- Search URL rules execute through `AnalyzeUrl`, including `@js:` URL rules and embedded `{{...}}` expressions.
- Search returns absolute `bookUrl`.
- Detail fills `tocUrl`.
- Toc returns chapters with absolute URLs.
- Content returns chapter body text.
- Toc follows `nextTocUrl` pages through the WebBook runtime, merges chapters, deduplicates by URL/title, and reindexes the final list.
- Toc applies `tocRule.formatJs` after merge/reindex with `index`, `chapter`, `title`, and `gInt` bindings.
- Content follows `nextContentUrl` pages through the WebBook runtime and merges page content.
- Current JVM code applies common Reading `replaceRegex` forms after merge as a provisional compatibility helper, but final article cleanup policy belongs to the Python post-processing layer.
- Source rules can call `@js:java.ajax(...)` during WebBook search and receive HTTP runtime response bodies.
- Normal WebBook HTTP requests also use `EngineCookieStore`: stored cookies are attached before request, and response `Set-Cookie` is written back.
- The same `EngineCookieStore` is passed into `AnalyzeRule`, so normal requests and `java.ajax` share one source cookie context.
- Emits stage trace events for `search/detail/toc/content` request and parse phases.
- Converts HTTP status `>= 400` into `EngineHttpStatusException` before parsing.

Batch execution:

- Accepts a list of sources.
- Filters disabled sources.
- Defaults to `batchSize=20`.
- Defaults to `globalConcurrency=20`.
- Defaults to `perHostConcurrency=2`.
- Emits `source_started`, `source_finished`, `source_failed`, `source_timed_out`, `batch_timeout`, `batch_finished`.
- Emits `source_trace` events with `stage`, `url`, `statusCode`, `message`, and `elapsedMs` from the direct-port WebBook kernel.
- Classifies empty parse results as `PARSE_EMPTY`.
- Classifies HTTP 4xx as `HTTP_4XX` and HTTP 5xx as `HTTP_5XX`.
- Classifies WebView-required source requests as `WEBVIEW_REQUIRED` before calling the HTTP runtime.
- Classifies source JS login markers as `LOGIN_REQUIRED`.
- Classifies source JS runtime failures as `JS_ERROR`.
- Classifies unknown host / normal IO failures as `NETWORK_ERROR`.
- Classifies proxy-related IO failures as `PROXY_ERROR`.
- Enforces source timeout and request timeout config.

Bridge CLI:

- `version`
- `parse-source <path>`
- `batch-search <sources-path> <keyword> [static-responses-json]`

## Verification Commands And Results

JVM tests:

```powershell
$env:JAVA_HOME='C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot'
$env:Path="$env:JAVA_HOME\bin;$env:Path"
$env:GRADLE_OPTS=''
data\upstreams\luoyacheng-legado\gradlew.bat -p . :engine-jvm:test --no-daemon
```

Note: `quick-transfer-core` is resolved through JitPack. On this machine, running Gradle with
`-Dhttps.proxyHost=192.168.31.233 -Dhttps.proxyPort=7890` caused a JitPack TLS handshake failure;
the verified command above intentionally leaves `GRADLE_OPTS` empty.

Verified targeted result:

```powershell
data\upstreams\luoyacheng-legado\gradlew.bat -p . :engine-jvm:test --tests legadohub.engine.port.AnalyzeRulePortTest --no-daemon
data\upstreams\luoyacheng-legado\gradlew.bat -p . :engine-jvm:test --tests legadohub.engine.port.AnalyzeUrlPortTest --no-daemon
data\upstreams\luoyacheng-legado\gradlew.bat -p . :engine-jvm:test --tests legadohub.engine.port.WebBookPortTest --no-daemon
data\upstreams\luoyacheng-legado\gradlew.bat -p . :engine-jvm:test --tests legadohub.engine.port.WebBookPortTest --tests legadohub.engine.batch.BatchSearchRunnerTest --no-daemon
```

```text
BUILD SUCCESSFUL in 1m 22s
BUILD SUCCESSFUL in 1m
BUILD SUCCESSFUL in 1m 13s
BUILD SUCCESSFUL in 1m 11s
BUILD SUCCESSFUL in 43s
BUILD SUCCESSFUL in 1m 5s
BUILD SUCCESSFUL in 1m 16s
BUILD SUCCESSFUL in 59s
BUILD SUCCESSFUL in 1m 9s
BUILD SUCCESSFUL in 1m 12s
BUILD SUCCESSFUL in 1m 12s
BUILD SUCCESSFUL in 1m 11s
BUILD SUCCESSFUL in 1m 17s
BUILD SUCCESSFUL in 1m 13s
BUILD SUCCESSFUL in 1m 5s
```

Latest verified full result:

```text
BUILD SUCCESSFUL in 20s
```

Note: the latest run was fully up-to-date. The command still verifies the current test graph and Gradle/JDK wiring.

CLI version smoke:

```powershell
& 'C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot\bin\java.exe' -jar engine-jvm\build\libs\engine-jvm-0.0.1.jar version
```

Verified output:

```text
0.0.1
```

CLI source import smoke:

```powershell
& 'C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot\bin\java.exe' -jar engine-jvm\build\libs\engine-jvm-0.0.1.jar parse-source data\sources\raw\by-site\legado\sub-xiu2_yuedu.json
```

Verified result:

```text
count = 26
```

Note: running `java` without setting `JAVA_HOME`/`PATH` fails on this machine. Use the explicit Java path above or set:

```powershell
$env:JAVA_HOME='C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot'
$env:Path="$env:JAVA_HOME\bin;$env:Path"
```

CLI batch search smoke with static responses:

```powershell
java -jar engine-jvm\build\libs\engine-jvm-0.0.1.jar batch-search <temp-source-json> "凡人" <temp-static-responses-json>
```

Verified result:

```text
keyword = 凡人
totalSources = 1
completedSources = 1
result = 凡人修仙传 / 忘语 / https://a.example/book/1
events = source_started, source_finished, batch_finished
```

Current CLI batch search output also includes `source_trace` events for:

- `search.request` request start and finish
- `search.parse` parse start and finish

## Known Gaps

This is not yet a full upstream Reading kernel port.

Remaining Phase 1 deep-port work:

- Continue tightening `RuleAnalyzer` and `AnalyzeBy*` against upstream behavior, especially nested chained rules and broader edge cases beyond the current regression corpus.
- Port a broader subset of upstream `JsExtensions`; deterministic helpers, selector helpers, and simplified/traditional conversion now cover the first XIU2/Yuedu slice, but WebView/browser helpers, file/archive helpers, font helpers, full crypto API parity, and response-wrapper edge cases are still incomplete.
- Continue expanding `java.ajax` compatibility toward full upstream behavior: remaining `AnalyzeUrl` option parity, timeout nuance, and deeper error classification.
- Add persistent cookie jar and source-variable implementations behind `EngineCookieStore` / `EngineSourceVariableStore`; current Phase 1 bridge contracts and in-memory tests are complete, but no durable store is wired yet.
- Expand WebBook behavior beyond the current direct-port slice where it affects source execution: login check JS, durable source variables, complex redirects, and extraction-critical rule behavior.
- Expand explore category compatibility beyond the current backend slice: upstream `InfoMap`, UI filter state, cache invalidation, and complex JS-driven category mutation are not fully ported yet.
- Do not continue a full upstream `ContentProcessor` port in JVM. Final title/content cleanup parity should be planned as Python article post-processing unless it is required for source extraction.
- Keep expanding HTTP failure classification beyond the current structured set, including captcha blocks and parse failures with rule context.
- Keep WebView sources structured as `WEBVIEW_REQUIRED` until a backend WebView runtime is selected.
- Add real-source compatibility regression only after the direct-port internals are deeper; current WebBook tests use static HTTP responses.

## Next Phase 1 Tasks

1. Expand nested chained-rule compatibility against upstream examples.
2. Add more HTTP response-wrapper edge cases and JS selector helper tests for common upstream helpers used by XIU2/Yuedu sources.
3. Plan Python article post-processing as a separate package instead of growing JVM content cleanup.
4. Only after the above, begin Phase 2 Python bridge rewiring.
