# Luoyacheng Legado 上游源码基线

> 本文固定 LegadoHub 新内核重构的阅读源码基准。旧的 Python 近似解析器路线只保留为历史实现，不再作为语义真相。

## 基准信息

- 上游仓库：`https://github.com/Luoyacheng/legado.git`
- 本地路径：`C:/Home/Workspace/UGit/legado-hub/data/upstreams/luoyacheng-legado`
- 当前 commit：`44e07fea541287804cc58d0168940a756cd11cfd`
- 许可：GPL-3.0。若后续直接复制或改写上游核心代码，需要按 GPL-3.0 处理派生代码的授权边界。

## 必读源码入口

- `app/src/main/java/io/legado/app/data/entities/BookSource.kt`
  - 书源最小单位。
  - `bookSourceUrl` 是主键和相等性依据。
  - `bookSourceGroup` 是展示和筛选分组，不参与身份判定。
- `app/src/main/java/io/legado/app/data/entities/BaseSource.kt`
  - header、login、cookie、jsLib、source 变量等运行时能力入口。
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeUrl.kt`
  - URL、请求方式、header、body、charset、WebView、JS、cookie、proxy 的核心语义。
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeRule.kt`
  - 规则执行总入口，负责 CSS/XPath/JsonPath/Regex/JS/fallback/replace 等组合语义。
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByJSoup.kt`
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByXPath.kt`
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByJSonPath.kt`
- `app/src/main/java/io/legado/app/model/analyzeRule/AnalyzeByRegex.kt`
- `app/src/main/java/io/legado/app/model/webBook/WebBook.kt`
  - search/detail/toc/content/explore 的上层执行流程。
- `app/src/main/java/io/legado/app/ui/association/ImportBookSourceViewModel.kt`
  - 书源订阅导入、更新、去重、覆盖的行为参考。
- `modules/web/`
  - 后台第二阶段的信息架构参考，不直接照搬 UI。

## Phase 1 抽取策略

LegadoHub 不把 Android App 直接作为服务端运行，而是建立独立 `engine-jvm`：

- 保留阅读规则字段和 JSON 名称。
- 以 `bookSourceUrl` 作为唯一稳定身份。
- 把 Android 依赖替换为后端接口：`HttpRuntime`、`CookieStore`、`SourceVariableStore`、`EngineCache`、`WebViewRuntime`、`EngineLogger`。
- WebView、登录、复杂 JavaScript 在第一批内核中不能静默失败，必须返回结构化 `UnsupportedReason`。
- 每个 search/detail/toc/content/explore 执行结果都要带 trace、unsupported、error、latencyMs。

## Android 依赖替换表

| 阅读依赖 | 后端替换 |
| --- | --- |
| Room / Parcelable / Android Context | Kotlin/JVM data model + 后端数据库映射 |
| OkHttp helpers | `HttpRuntime` |
| CookieStore / CookieManager | `CookieStore` 接口 |
| CacheManager | `EngineCache` |
| RhinoScriptEngine | 后续独立 JS runtime；当前阶段复杂 JS 结构化 unsupported |
| BackstageWebView | `WebViewRuntime` |
| AppConfig.userAgent | `SourceHeaderParser.DEFAULT_USER_AGENT` 或后端配置 |
| AppLog / Debug | `EngineLogger` + `TraceEvent` |

## 验收命令

```powershell
git -C data\upstreams\luoyacheng-legado remote -v
git -C data\upstreams\luoyacheng-legado rev-parse HEAD

# 需要本机有 JDK。若没有系统 Gradle，使用上游 wrapper 运行当前仓库。
$env:JAVA_HOME = "<JDK 根目录>"
$env:Path = "$env:JAVA_HOME\bin;$env:Path"
data\upstreams\luoyacheng-legado\gradlew.bat -p . :engine-jvm:test
```

## 当前已知环境状态

截至本次执行，`java` 和 `gradle` 均未在 PATH 中找到，常见 `Program Files` JDK/JBR 路径也未发现可用 JDK。`engine-jvm` 测试文件已经落地，但运行测试需要先安装或指定 JDK。
