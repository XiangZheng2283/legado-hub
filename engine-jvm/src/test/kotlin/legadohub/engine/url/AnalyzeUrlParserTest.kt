package legadohub.engine.url

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.collections.shouldContain
import io.kotest.matchers.maps.shouldContain
import io.kotest.matchers.shouldBe
import legadohub.engine.model.BookSource
import legadohub.engine.model.UnsupportedCode

class AnalyzeUrlParserTest : StringSpec({
    val parser = AnalyzeUrlParser()

    "replaces simple Reading inline variables and page alternatives" {
        val result = parser.parse(
            AnalyzeUrlInput(
                ruleUrl = "/search/{{key}}/<1,2,3>?author={{author}}",
                key = "凡人修仙传",
                author = "忘语",
                page = 2,
                baseUrl = "https://example.com/books/",
            ),
        )

        result.url shouldBe "https://example.com/search/凡人修仙传/2?author=%E5%BF%98%E8%AF%AD"
        result.urlNoQuery shouldBe "https://example.com/search/凡人修仙传/2"
        result.encodedQuery shouldBe "author=%E5%BF%98%E8%AF%AD"
    }

    "merges source headers and URL option headers with proxy hint" {
        val result = parser.parse(
            AnalyzeUrlInput(
                ruleUrl = """https://example.com/search?q={{key}}, {"headers":{"Accept":"application/json","X-Trace":"1"},"proxy":"http://127.0.0.1:7890"}""",
                key = "测试",
                source = BookSource(
                    bookSourceName = "测试源",
                    bookSourceUrl = "https://example.com",
                    header = """{"Accept":"text/html","Referer":"https://example.com"}""",
                ),
            ),
        )

        result.headers shouldContain ("Accept" to "application/json")
        result.headers shouldContain ("Referer" to "https://example.com")
        result.headers shouldContain ("X-Trace" to "1")
        result.proxy shouldBe "http://127.0.0.1:7890"
    }

    "parses POST body and encodes form fields" {
        val result = parser.parse(
            AnalyzeUrlInput(
                ruleUrl = """https://example.com/api, {"method":"POST","body":"kw={{key}}&page={{page}}","charset":"UTF-8"}""",
                key = "三体",
                page = 3,
            ),
        )

        result.method shouldBe AnalyzeHttpMethod.POST
        result.body shouldBe "kw=三体&page=3"
        result.encodedForm shouldBe "kw=%E4%B8%89%E4%BD%93&page=3"
    }

    "keeps JSON POST body without form encoding" {
        val result = parser.parse(
            AnalyzeUrlInput(
                ruleUrl = """https://example.com/api, {"method":"POST","headers":{"Content-Type":"application/json"},"body":{"kw":"三体"}}""",
            ),
        )

        result.method shouldBe AnalyzeHttpMethod.POST
        result.body shouldBe """{"kw":"三体"}"""
        result.encodedForm shouldBe null
    }

    "marks WebView and JavaScript URL options as unsupported" {
        val result = parser.parse(
            AnalyzeUrlInput(
                ruleUrl = """https://example.com, {"webView":true,"bodyJs":"result","js":"url"}""",
            ),
        )

        result.useWebView shouldBe true
        result.unsupported.map { it.code } shouldContain UnsupportedCode.WebViewRequired
        result.unsupported.map { it.code } shouldContain UnsupportedCode.ComplexJavaScript
    }
})
