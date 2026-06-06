package legadohub.engine.pipeline

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.collections.shouldHaveSize
import io.kotest.matchers.shouldBe
import legadohub.engine.model.BookSource
import legadohub.engine.model.UnsupportedCode
import legadohub.engine.runtime.EngineHttpRequest
import legadohub.engine.runtime.EngineHttpResponse
import legadohub.engine.runtime.HttpRuntime
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject

class WebBookPipelineTest : StringSpec({
    val json = Json { ignoreUnknownKeys = true }

    "search executes AnalyzeUrl, HttpRuntime, and ruleSearch book list parsing" {
        var capturedRequest: EngineHttpRequest? = null
        val pipeline = WebBookPipeline(
            httpRuntime = object : HttpRuntime {
                override suspend fun execute(request: EngineHttpRequest): EngineHttpResponse {
                    capturedRequest = request
                    return EngineHttpResponse(
                        statusCode = 200,
                        body = """
                            <div class="book">
                              <a class="name" href="/book/1">凡人修仙传</a>
                              <span class="author">忘语</span>
                              <span class="kind">仙侠</span>
                            </div>
                            <div class="book">
                              <a class="name" href="/book/2">魔天记</a>
                              <span class="author">忘语</span>
                              <span class="kind">玄幻</span>
                            </div>
                        """.trimIndent(),
                        finalUrl = request.url,
                        elapsedMs = 12,
                    )
                }
            },
        )
        val source = BookSource(
            bookSourceName = "测试源",
            bookSourceUrl = "https://example.com",
            searchUrl = "/search?q={{key}}",
            ruleSearch = json.parseToJsonElement(
                """
                {
                  "bookList": ".book@outerHtml",
                  "name": ".name@text",
                  "author": ".author@text",
                  "kind": ".kind@text",
                  "bookUrl": ".name@href"
                }
                """.trimIndent(),
            ).jsonObject,
        )

        val result = pipeline.search(source, "凡人", 1)

        result.ok shouldBe true
        result.items shouldHaveSize 2
        result.items[0].name shouldBe "凡人修仙传"
        result.items[0].author shouldBe "忘语"
        result.items[0].bookUrl shouldBe "/book/1"
        result.items[0].sourceId shouldBe "https://example.com"
        capturedRequest?.url shouldBe "https://example.com/search?q=%E5%87%A1%E4%BA%BA"
        capturedRequest?.method shouldBe "GET"
    }

    "search returns structured unsupported when WebView is required" {
        val pipeline = WebBookPipeline(
            httpRuntime = object : HttpRuntime {
                override suspend fun execute(request: EngineHttpRequest): EngineHttpResponse {
                    error("HTTP should not run when WebView is required")
                }
            },
        )
        val source = BookSource(
            bookSourceName = "WebView 源",
            bookSourceUrl = "https://example.com",
            searchUrl = """https://example.com/search, {"webView":true}""",
            ruleSearch = json.parseToJsonElement("""{"bookList": ".book"}""").jsonObject,
        )

        val result = pipeline.search(source, "凡人", 1)

        result.ok shouldBe false
        result.unsupported.map { it.code }.contains(UnsupportedCode.WebViewRequired) shouldBe true
    }
})
