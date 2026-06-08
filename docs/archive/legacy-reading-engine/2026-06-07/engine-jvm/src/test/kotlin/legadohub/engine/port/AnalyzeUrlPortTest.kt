package legadohub.engine.port

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.collections.shouldContain
import io.kotest.matchers.shouldBe
import io.legado.app.data.entities.BookSource
import io.legado.app.model.analyzeRule.AnalyzeUrl

class AnalyzeUrlPortTest : StringSpec({
    "ported AnalyzeUrl replaces key page and resolves relative url" {
        val source = BookSource(
            bookSourceName = "测试源",
            bookSourceUrl = "https://example.com",
        )

        val analyzeUrl = AnalyzeUrl(
            mUrl = "/search?q={{key}}&page={{page}}",
            key = "凡人修仙传",
            page = 2,
            baseUrl = source.bookSourceUrl,
            source = source,
        )

        val request = analyzeUrl.toRequestSpec()

        request.method shouldBe "GET"
        request.url shouldBe "https://example.com/search?q=%E5%87%A1%E4%BA%BA%E4%BF%AE%E4%BB%99%E4%BC%A0&page=2"
        analyzeUrl.urlNoQuery shouldBe "https://example.com/search"
        request.headers["User-Agent"]?.isNotBlank() shouldBe true
    }

    "ported AnalyzeUrl parses Reading url options" {
        val analyzeUrl = AnalyzeUrl(
            mUrl = """
                https://example.com/search, {
                  "method": "POST",
                  "charset": "UTF-8",
                  "headers": {"X-Test": "1"},
                  "body": "q={{key}}&page={{page}}",
                  "retry": 2,
                  "type": "text",
                  "proxy": "http://127.0.0.1:7890",
                  "serverID": 9,
                  "webViewDelayTime": 150
                }
            """.trimIndent(),
            key = "凡人",
            page = 3,
        )

        val request = analyzeUrl.toRequestSpec(readTimeoutMs = 8_000)

        request.method shouldBe "POST"
        request.url shouldBe "https://example.com/search"
        request.body shouldBe "q=%E5%87%A1%E4%BA%BA&page=3"
        request.charset shouldBe "UTF-8"
        request.headers["X-Test"] shouldBe "1"
        request.proxy shouldBe "http://127.0.0.1:7890"
        request.retry shouldBe 2
        request.type shouldBe "text"
        request.serverID shouldBe 9
        request.webViewDelayTime shouldBe 150
        request.timeoutMs shouldBe 8_000
    }

    "ported AnalyzeUrl executes url option js to rewrite final request url" {
        val analyzeUrl = AnalyzeUrl(
            mUrl = """
                https://example.com/search?q={{key}}, {
                  "js": "result.replace('/search', '/rewritten') + '&page=' + page"
                }
            """.trimIndent(),
            key = "凡人",
            page = 2,
        )

        val request = analyzeUrl.toRequestSpec()

        request.url shouldBe "https://example.com/rewritten?q=%E5%87%A1%E4%BA%BA&page=2"
        analyzeUrl.urlNoQuery shouldBe "https://example.com/rewritten"
    }

    "ported AnalyzeUrl marks runtime-only url options as unsupported" {
        val analyzeUrl = AnalyzeUrl(
            mUrl = """
                https://example.com/search, {
                  "webView": true,
                  "webJs": "document.body.innerText",
                  "bodyJs": "result",
                  "dnsIp": "127.0.0.1"
                }
            """.trimIndent(),
        )

        val codes = analyzeUrl.toRequestSpec().unsupported.map { it.code }

        codes shouldContain "WEBVIEW_REQUIRED"
        codes shouldContain "WEBVIEW_JS_REQUIRED"
        codes shouldContain "BODY_JS_REQUIRED"
        codes shouldContain "CUSTOM_DNS_REQUIRED"
    }

    "ported AnalyzeUrl keeps proxy from source header out of headers" {
        val analyzeUrl = AnalyzeUrl(
            mUrl = "https://example.com",
            headerMapF = mapOf(
                "proxy" to "http://127.0.0.1:7890",
                "Cookie" to "a=b",
            ),
        )

        val request = analyzeUrl.toRequestSpec()

        request.proxy shouldBe "http://127.0.0.1:7890"
        request.headers["proxy"] shouldBe null
        request.headers["Cookie"] shouldBe "a=b"
    }
})
