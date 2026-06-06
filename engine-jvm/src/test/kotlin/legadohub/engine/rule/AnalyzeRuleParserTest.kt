package legadohub.engine.rule

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.collections.shouldContain
import io.kotest.matchers.shouldBe
import legadohub.engine.model.UnsupportedCode

class AnalyzeRuleParserTest : StringSpec({
    val parser = AnalyzeRuleParser()

    "extracts text with JSoup CSS selector" {
        val result = parser.analyze(
            AnalyzeRuleInput(
                content = """<div class="book"><a class="name" href="/b/1">凡人修仙传</a></div>""",
                rule = ".book .name@text",
            ),
        )

        result.values shouldBe listOf("凡人修仙传")
    }

    "extracts attributes with JSoup CSS selector" {
        val result = parser.analyze(
            AnalyzeRuleInput(
                content = """<div class="book"><a class="name" href="/b/1">凡人修仙传</a></div>""",
                rule = ".book .name@href",
            ),
        )

        result.values shouldBe listOf("/b/1")
    }

    "extracts values with JsonPath" {
        val result = parser.analyze(
            AnalyzeRuleInput(
                content = """{"items":[{"name":"三体"},{"name":"球状闪电"}]}""",
                rule = "$.items[*].name",
            ),
        )

        result.values shouldBe listOf("三体", "球状闪电")
    }

    "extracts regex capture groups" {
        val result = parser.analyze(
            AnalyzeRuleInput(
                content = "作者：忘语 字数：300万",
                rule = "regex:作者：(.+?)\\s",
            ),
        )

        result.values shouldBe listOf("忘语")
    }

    "uses fallback rule when the first rule has no result" {
        val result = parser.analyze(
            AnalyzeRuleInput(
                content = """<h1>雪中悍刀行</h1>""",
                rule = ".missing@text||h1@text",
            ),
        )

        result.values shouldBe listOf("雪中悍刀行")
    }

    "applies replacement rules after extraction" {
        val result = parser.analyze(
            AnalyzeRuleInput(
                content = """<p class="intro">作者：烽火戏诸侯</p>""",
                rule = ".intro@text##作者：##",
            ),
        )

        result.values shouldBe listOf("烽火戏诸侯")
    }

    "marks JavaScript rules as unsupported" {
        val result = parser.analyze(
            AnalyzeRuleInput(
                content = """<p>text</p>""",
                rule = "@js:result",
            ),
        )

        result.values shouldBe emptyList<String>()
        result.unsupported.map { it.code } shouldContain UnsupportedCode.ComplexJavaScript
    }
})
