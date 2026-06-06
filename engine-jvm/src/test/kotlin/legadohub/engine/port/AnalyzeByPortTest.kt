package legadohub.engine.port

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.collections.shouldContainExactly
import io.kotest.matchers.shouldBe
import io.legado.app.model.analyzeRule.AnalyzeByJSonPath
import io.legado.app.model.analyzeRule.AnalyzeByJSoup
import io.legado.app.model.analyzeRule.AnalyzeByRegex
import io.legado.app.model.analyzeRule.RuleAnalyzer

class AnalyzeByPortTest : StringSpec({
    "RuleAnalyzer does not split separators inside selectors and quoted text" {
        RuleAnalyzer("""a[href*='a||b']@text||.fallback@text""")
            .splitRule("||") shouldContainExactly listOf("""a[href*='a||b']@text""", ".fallback@text")

        RuleAnalyzer("""div[data-x="a&&b"]@text&&span@text""")
            .splitRule("&&") shouldContainExactly listOf("""div[data-x="a&&b"]@text""", "span@text")
    }

    "AnalyzeByJSoup supports fallback and interleaving merge" {
        val analyzer = AnalyzeByJSoup(
            """
            <main>
              <a class="name" href="/book/1">凡人修仙传</a>
              <span class="author">忘语</span>
              <a class="name" href="/book/2">魔天记</a>
              <span class="author">忘语</span>
            </main>
            """.trimIndent(),
        )

        analyzer.getString(".missing@text||.name@text") shouldBe "凡人修仙传\n魔天记"
        analyzer.getStringList(".name@text%%.author@text") shouldContainExactly listOf(
            "凡人修仙传",
            "忘语",
            "魔天记",
            "忘语",
        )
    }

    "AnalyzeByJSoup supports CSS mode and text node extraction" {
        val analyzer = AnalyzeByJSoup(
            """
            <main>
              <p class="intro">第一段 <b>加粗</b> 第二段</p>
            </main>
            """.trimIndent(),
        )

        analyzer.getString("@CSS:.intro@ownText") shouldBe "第一段 第二段"
        analyzer.getStringList(".intro@textNodes") shouldContainExactly listOf("第一段\n第二段")
    }

    "AnalyzeByJSoup supports Reading index ranges and exclusions" {
        val analyzer = AnalyzeByJSoup(
            """
            <ul>
              <li>第一章</li>
              <li>第二章</li>
              <li>第三章</li>
              <li>第四章</li>
            </ul>
            """.trimIndent(),
        )

        analyzer.getStringList("tag.li.0:2@text") shouldContainExactly listOf("第一章", "第二章", "第三章")
        analyzer.getStringList("tag.li!1@text") shouldContainExactly listOf("第一章", "第三章", "第四章")
        analyzer.getStringList("li[0,2]@text") shouldContainExactly listOf("第一章", "第三章")
        analyzer.getStringList("li[1:2]@text") shouldContainExactly listOf("第二章", "第三章")
        analyzer.getStringList("li[!1]@text") shouldContainExactly listOf("第一章", "第三章", "第四章")
        analyzer.getStringList("li[-1]@text") shouldContainExactly listOf("第四章")
    }

    "AnalyzeByJsonPath supports fallback and interleaving merge" {
        val analyzer = AnalyzeByJSonPath(
            """
            {
              "names": ["凡人修仙传", "魔天记"],
              "authors": ["忘语", "忘语"]
            }
            """.trimIndent(),
        )

        analyzer.getString("$.missing || $.names[*]") shouldBe "凡人修仙传\n魔天记"
        analyzer.getStringList("$.names[*]%%$.authors[*]") shouldContainExactly listOf(
            "凡人修仙传",
            "忘语",
            "魔天记",
            "忘语",
        )
    }

    "AnalyzeByRegex supports chained extraction" {
        AnalyzeByRegex.getElements(
            "书名：凡人修仙传 作者：忘语\n书名：魔天记 作者：忘语",
            arrayOf("书名：(.*?) 作者：(.*?)(?:\\n|$)"),
        ).map { it[1] } shouldContainExactly listOf("凡人修仙传", "魔天记")
    }
})
