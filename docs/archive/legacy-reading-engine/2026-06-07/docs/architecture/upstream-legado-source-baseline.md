# Luoyacheng Legado Upstream Source Baseline

> This document fixes the upstream semantic baseline for the direct Kotlin/JVM port. It supersedes the old Python approximate parser route and the self-written Kotlin parser route.

## Baseline

- Upstream repository: `https://github.com/Luoyacheng/legado.git`
- Local checkout: `C:/Home/Workspace/UGit/legado-hub/data/upstreams/luoyacheng-legado`
- Locked commit: `44e07fea541287804cc58d0168940a756cd11cfd`
- License: GPL-3.0. Directly copied or modified upstream kernel code must be treated as GPL-derived code.

Verify:

```powershell
git -C data\upstreams\luoyacheng-legado rev-parse HEAD
```

Expected:

```text
44e07fea541287804cc58d0168940a756cd11cfd
```

## Direct-Port Source Files

These upstream files are the first semantic truth set. Port them into `engine-jvm` instead of recreating equivalent behavior from scratch.

### Source Models

- `app/src/main/java/io/legado/app/data/entities/BaseSource.kt`
- `app/src/main/java/io/legado/app/data/entities/BookSource.kt`
- `app/src/main/java/io/legado/app/data/entities/rule/SearchRule.kt`
- `app/src/main/java/io/legado/app/data/entities/rule/BookInfoRule.kt`
- `app/src/main/java/io/legado/app/data/entities/rule/TocRule.kt`
- `app/src/main/java/io/legado/app/data/entities/rule/ContentRule.kt`

Required identity rule:

```text
BookSource identity = bookSourceUrl
```

Do not group or deduplicate by website host.

### AnalyzeUrl And AnalyzeRule

- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeUrl.kt`
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeRule.kt`
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeRuleHelper.kt`
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByJSoup.kt`
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByXPath.kt`
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByJSonPath.kt`
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByRegex.kt`
- `app/src/main/java/io/legado/app/model/analyzeRule/JsExtensions.kt`

Required behavior coverage:

```text
CSS
XPath
JsonPath
Regex
fallback ruleA||ruleB
replace rule##pattern##replacement
<js> / @js
java.ajax
base64/md5 and common JS helpers
```

### Web Book Flow

- `app/src/main/java/io/legado/app/model/webBook/WebBook.kt`
- `app/src/main/java/io/legado/app/model/webBook/BookList.kt`
- `app/src/main/java/io/legado/app/model/webBook/BookInfo.kt`
- `app/src/main/java/io/legado/app/model/webBook/BookChapterList.kt`
- `app/src/main/java/io/legado/app/model/webBook/BookContent.kt`

Required chain:

```text
search -> detail -> toc -> content
```

### Import And Web UI References

- `app/src/main/java/io/legado/app/ui/association/ImportBookSourceViewModel.kt`
  - Reference for subscription import, update, deduplication, and overwrite behavior.
- `modules/web/`
  - Reference for later web admin information architecture only. Do not copy its UI directly.

## Android-To-Backend Replacement Table

| Upstream dependency | LegadoHub JVM replacement |
| --- | --- |
| `android.util.Log` | `EngineLogger` |
| `android.content.Context` | `EngineConfig` or removed call site |
| `android.webkit.WebView` | `WebViewRuntime` |
| Room entities / DAO | Serializable engine models + Python persistence mapping |
| Parcelable | Removed on JVM |
| AppConfig | `EngineConfig` |
| AppLog / Debug | `EngineLogger` + trace events |
| CookieStore / CookieManager | `EngineCookieStore` |
| CacheManager | `EngineCache` |
| OkHttp helpers | `EngineHttpRuntime` backed by OkHttp |
| RhinoScriptEngine / JS setup | `EngineJsRuntime` with upstream `JsExtensions` |
| BackstageWebView | `WebViewRuntime`, default unsupported until backend WebView is selected |

## Engine Port Principles

1. Start from upstream code, then adapt dependencies.
2. Preserve package/class/function names when that reduces diff from upstream.
3. Prefer compatibility shims over semantic rewrites.
4. Delete self-written parser files once direct-port equivalents compile.
5. Return structured unsupported results for missing backend capabilities.
6. Tests must prove the direct-port path, not just wrapper behavior.

## Current Local Environment

- Java 17 installed at:

```text
C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot
```

- On this machine, Gradle dependency resolution for JitPack-backed dependencies has been verified with an empty `GRADLE_OPTS`. The proxy form caused TLS handshake failures against JitPack during Phase 1 verification.

```powershell
$env:JAVA_HOME='C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot'
$env:Path="$env:JAVA_HOME\bin;$env:Path"
$env:GRADLE_OPTS=''
```

Validation command:

```powershell
data\upstreams\luoyacheng-legado\gradlew.bat -p . :engine-jvm:test --no-daemon
```
