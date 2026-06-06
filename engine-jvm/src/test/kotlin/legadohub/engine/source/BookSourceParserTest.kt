package legadohub.engine.source

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.collections.shouldHaveSize
import io.kotest.matchers.shouldBe
import legadohub.engine.model.BookSourceValidation

class BookSourceParserTest : StringSpec({
    val parser = BookSourceParser()

    "parses one Reading BookSource object" {
        val source = parser.parseOne(
            """
            {
              "bookSourceName": "测试源",
              "bookSourceUrl": "https://example.com",
              "bookSourceGroup": "默认,测试",
              "enabled": true,
              "enabledExplore": false,
              "searchUrl": "/search?q={{key}}",
              "ruleSearch": {
                "bookList": "class.item",
                "name": "class.name@text"
              }
            }
            """.trimIndent()
        )

        source.bookSourceName shouldBe "测试源"
        source.bookSourceUrl shouldBe "https://example.com"
        source.sourceId shouldBe "https://example.com"
        source.bookSourceGroup shouldBe "默认,测试"
        source.enabledExplore shouldBe false
        source.displayNameWithGroup() shouldBe "测试源 (默认,测试)"
        source.validate() shouldBe BookSourceValidation.Valid
    }

    "parses a Reading BookSource array as independent sources" {
        val sources = parser.parseMany(
            """
            [
              {
                "bookSourceName": "源 A",
                "bookSourceUrl": "https://a.example"
              },
              {
                "bookSourceName": "源 B",
                "bookSourceUrl": "https://b.example"
              }
            ]
            """.trimIndent()
        )

        sources shouldHaveSize 2
        sources[0].sourceId shouldBe "https://a.example"
        sources[1].sourceId shouldBe "https://b.example"
    }

    "keeps bookSourceUrl as the sole identity even when names match" {
        val sources = parser.parseMany(
            """
            [
              {
                "bookSourceName": "同名源",
                "bookSourceUrl": "https://site.example/a"
              },
              {
                "bookSourceName": "同名源",
                "bookSourceUrl": "https://site.example/b"
              }
            ]
            """.trimIndent()
        )

        sources[0].sourceId shouldBe "https://site.example/a"
        sources[1].sourceId shouldBe "https://site.example/b"
    }

    "reports missing bookSourceUrl as invalid" {
        val source = parser.parseOne(
            """
            {
              "bookSourceName": "坏源"
            }
            """.trimIndent()
        )

        source.validate() shouldBe BookSourceValidation.Invalid("bookSourceUrl 不能为空")
    }
})
