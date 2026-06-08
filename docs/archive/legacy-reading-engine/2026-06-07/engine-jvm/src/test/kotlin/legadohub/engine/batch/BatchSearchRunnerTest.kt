package legadohub.engine.batch

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.collections.shouldContain
import io.kotest.matchers.collections.shouldHaveSize
import io.kotest.matchers.shouldBe
import io.legado.app.data.entities.BookSource
import io.legado.app.data.entities.rule.SearchRule
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import legadohub.engine.runtime.StaticHttpRuntime
import legadohub.engine.runtime.EngineHttpRequestV2
import legadohub.engine.runtime.EngineHttpResponseV2
import legadohub.engine.runtime.EngineHttpRuntime
import java.io.IOException
import java.net.UnknownHostException

class BatchSearchRunnerTest : StringSpec({
    "batch search runs enabled sources and records progress events" {
        val sourceA = batchSource("源 A", "https://a.example")
        val sourceB = batchSource("源 B", "https://b.example", enabled = false)
        val runtime = StaticHttpRuntime(
            mapOf(
                "https://a.example/search?q=%E5%87%A1%E4%BA%BA" to """
                    <div class="book">
                      <a class="name" href="/book/1">凡人修仙传</a>
                      <span class="author">忘语</span>
                    </div>
                """.trimIndent(),
            ),
        )
        val seenEvents = mutableListOf<String>()

        val summary = runBlocking {
            BatchSearchRunner(runtime, BatchSearchConfig(globalConcurrency = 20)).search(
                listOf(sourceA, sourceB),
                "凡人",
            ) { event ->
                seenEvents += event.type
            }
        }

        summary.totalSources shouldBe 1
        summary.completedSources shouldBe 1
        summary.results shouldHaveSize 1
        summary.results.first().name shouldBe "凡人修仙传"
        seenEvents shouldContain "source_started"
        seenEvents shouldContain "source_finished"
        seenEvents shouldContain "batch_finished"
        summary.events.map { it.type } shouldContain "source_trace"
        summary.events.mapNotNull { it.stage } shouldContain "search.request"
        summary.events.mapNotNull { it.stage } shouldContain "search.parse"
    }

    "batch search limits default batch to 20 enabled sources" {
        val sources = (1..21).map { index ->
            batchSource("源 $index", "https://s$index.example")
        }
        val runtime = StaticHttpRuntime(
            (1..20).associate { index ->
                "https://s$index.example/search?q=%E5%87%A1%E4%BA%BA" to """
                    <div class="book">
                      <a class="name" href="/book/$index">凡人修仙传 $index</a>
                      <span class="author">忘语</span>
                    </div>
                """.trimIndent()
            },
        )

        val summary = runBlocking {
            BatchSearchRunner(runtime).search(sources, "凡人")
        }

        summary.totalSources shouldBe 20
        summary.completedSources shouldBe 20
        summary.results shouldHaveSize 20
    }

    "batch search classifies empty parse results as PARSE_EMPTY" {
        val source = batchSource("空源", "https://empty.example")
        val runtime = StaticHttpRuntime(
            mapOf("https://empty.example/search?q=%E5%87%A1%E4%BA%BA" to "<main></main>"),
        )

        val summary = runBlocking {
            BatchSearchRunner(runtime).search(listOf(source), "凡人")
        }

        summary.results shouldHaveSize 0
        summary.events.last { it.type == "source_failed" }.errorCode shouldBe "PARSE_EMPTY"
    }

    "batch search classifies HTTP 4xx and 5xx failures" {
        val runtime = object : EngineHttpRuntime {
            override suspend fun execute(request: EngineHttpRequestV2): EngineHttpResponseV2 =
                EngineHttpResponseV2(
                    statusCode = if (request.url.contains("a.example")) 404 else 503,
                    body = "",
                    finalUrl = request.url,
                )
        }

        val summary = runBlocking {
            BatchSearchRunner(runtime).search(
                listOf(
                    batchSource("四零四源", "https://a.example"),
                    batchSource("五零三源", "https://b.example"),
                ),
                "凡人",
            )
        }

        summary.results shouldHaveSize 0
        summary.events.mapNotNull { it.statusCode } shouldContain 404
        summary.events.mapNotNull { it.statusCode } shouldContain 503
        summary.events.filter { it.type == "source_failed" }.map { it.errorCode } shouldContain "HTTP_4XX"
        summary.events.filter { it.type == "source_failed" }.map { it.errorCode } shouldContain "HTTP_5XX"
    }

    "batch search classifies WebView required before runtime request" {
        val source = batchSource("WebView 源", "https://webview.example").copy(
            searchUrl = "/search?q={{key}}, {\"webView\":true}",
        )
        val runtime = object : EngineHttpRuntime {
            override suspend fun execute(request: EngineHttpRequestV2): EngineHttpResponseV2 {
                error("runtime should not be called for WebView-required source")
            }
        }

        val summary = runBlocking {
            BatchSearchRunner(runtime).search(listOf(source), "凡人")
        }

        summary.events.last { it.type == "source_failed" }.errorCode shouldBe "WEBVIEW_REQUIRED"
        summary.events.map { it.type } shouldContain "source_trace"
        summary.events.map { it.message } shouldContain "URL option webView requires WebView runtime"
    }

    "batch search classifies login required and JS errors from source JS" {
        val runtime = StaticHttpRuntime(emptyMap())
        val summary = runBlocking {
            BatchSearchRunner(runtime).search(
                listOf(
                    batchSource("登录源", "https://login.example").copy(searchUrl = "@js:throw 'LOGIN_REQUIRED'"),
                    batchSource("脚本源", "https://js.example").copy(searchUrl = "@js:missing.call()"),
                ),
                "凡人",
            )
        }

        summary.events.filter { it.type == "source_failed" }.map { it.errorCode } shouldContain "LOGIN_REQUIRED"
        summary.events.filter { it.type == "source_failed" }.map { it.errorCode } shouldContain "JS_ERROR"
    }

    "batch search classifies network proxy and source timeout failures" {
        val runtime = object : EngineHttpRuntime {
            override suspend fun execute(request: EngineHttpRequestV2): EngineHttpResponseV2 =
                when {
                    "network.example" in request.url -> throw UnknownHostException("network.example")
                    "proxy.example" in request.url -> throw IOException("proxy refused")
                    else -> {
                        delay(200)
                        EngineHttpResponseV2(statusCode = 200, body = "", finalUrl = request.url)
                    }
                }
        }

        val summary = runBlocking {
            BatchSearchRunner(
                runtime,
                BatchSearchConfig(sourceTimeoutMs = 50, requestTimeoutMs = 50),
            ).search(
                listOf(
                    batchSource("网络源", "https://network.example"),
                    batchSource("代理源", "https://proxy.example"),
                    batchSource("超时源", "https://timeout.example"),
                ),
                "凡人",
            )
        }

        summary.events.filter { it.type == "source_failed" }.map { it.errorCode } shouldContain "NETWORK_ERROR"
        summary.events.filter { it.type == "source_failed" }.map { it.errorCode } shouldContain "PROXY_ERROR"
        summary.events.filter { it.type == "source_timed_out" }.map { it.errorCode } shouldContain "SOURCE_TIMEOUT"
    }
})

private fun batchSource(
    name: String,
    url: String,
    enabled: Boolean = true,
): BookSource =
    BookSource(
        bookSourceName = name,
        bookSourceUrl = url,
        enabled = enabled,
        searchUrl = "/search?q={{key}}",
        ruleSearch = SearchRule(
            bookList = ".book",
            name = ".name@text",
            author = ".author@text",
            bookUrl = ".name@href",
        ),
    )
