package legadohub.engine.source

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.collections.shouldContain
import io.kotest.matchers.maps.shouldContain
import io.kotest.matchers.shouldBe
import legadohub.engine.model.BookSource
import legadohub.engine.model.UnsupportedCode

class SourceHeaderParserTest : StringSpec({
    val parser = SourceHeaderParser(defaultUserAgent = "LegadoHub-Test-UA")

    "parses source header JSON and extracts proxy hint" {
        val result = parser.parse(
            BookSource(
                bookSourceName = "测试源",
                bookSourceUrl = "https://example.com",
                header = """{"User-Agent":"Custom-UA","Referer":"https://example.com","proxy":"http://127.0.0.1:7890"}""",
            ),
        )

        result.headers shouldContain ("User-Agent" to "Custom-UA")
        result.headers shouldContain ("Referer" to "https://example.com")
        result.proxy shouldBe "http://127.0.0.1:7890"
    }

    "adds default user agent when source header does not define one" {
        val result = parser.parse(
            BookSource(
                bookSourceName = "测试源",
                bookSourceUrl = "https://example.com",
                header = """{"Accept":"text/html"}""",
            ),
        )

        result.headers shouldContain ("User-Agent" to "LegadoHub-Test-UA")
    }

    "marks JavaScript header rules as unsupported" {
        val result = parser.parse(
            BookSource(
                bookSourceName = "测试源",
                bookSourceUrl = "https://example.com",
                header = "@js:JSON.stringify({})",
            ),
        )

        result.unsupported.map { it.code } shouldContain UnsupportedCode.ComplexJavaScript
    }

    "marks login headers as unsupported when login is required" {
        val result = parser.parse(
            BookSource(
                bookSourceName = "测试源",
                bookSourceUrl = "https://example.com",
                loginUrl = "https://example.com/login",
            ),
            hasLoginHeader = true,
        )

        result.unsupported.map { it.code } shouldContain UnsupportedCode.LoginRequired
    }
})
