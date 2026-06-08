package legadohub.engine.runtime

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.shouldBe

class EngineRuntimeTest : StringSpec({
    "http runtime request preserves source id url proxy headers and timeout" {
        var captured: EngineHttpRequestV2? = null
        val runtime = object : EngineHttpRuntime {
            override suspend fun execute(request: EngineHttpRequestV2): EngineHttpResponseV2 {
                captured = request
                return EngineHttpResponseV2(statusCode = 200, body = "ok", finalUrl = request.url)
            }
        }

        val response = runtime.execute(
            EngineHttpRequestV2(
                sourceId = "https://example.com",
                url = "https://example.com/search",
                method = "POST",
                headers = mapOf("User-Agent" to "LegadoHub"),
                body = "q=test",
                proxy = "http://127.0.0.1:7890",
                timeoutMs = 8_000,
            ),
        )

        response.statusCode shouldBe 200
        captured?.sourceId shouldBe "https://example.com"
        captured?.url shouldBe "https://example.com/search"
        captured?.method shouldBe "POST"
        captured?.headers?.get("User-Agent") shouldBe "LegadoHub"
        captured?.proxy shouldBe "http://127.0.0.1:7890"
        captured?.timeoutMs shouldBe 8_000
    }

    "default WebView runtime returns structured unsupported result" {
        val result = UnsupportedWebViewRuntimeV2().render(
            WebViewRequestV2(
                sourceId = "https://example.com",
                url = "https://example.com",
            ),
        )

        result.ok shouldBe false
        result.errorCode shouldBe "WEBVIEW_REQUIRED"
        result.message shouldBe "This source requires WebView runtime"
    }
})
