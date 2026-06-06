package legadohub.engine.bridge

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.shouldBe
import java.nio.file.Files

class EngineCliTest : StringSpec({
    "version prints kernel version" {
        val output = mutableListOf<String>()

        val code = EngineCli.run(arrayOf("version"), out = output::add)

        code shouldBe 0
        output.single() shouldBe "0.0.1"
    }

    "parse-source prints direct-port source summary json" {
        val sourceFile = Files.createTempFile("legadohub-port-source-", ".json")
        Files.writeString(
            sourceFile,
            """
            [
              {
                "bookSourceName": "源 A",
                "bookSourceUrl": "https://a.example"
              },
              {
                "bookSourceName": "源 B",
                "bookSourceUrl": "https://b.example",
                "enabled": false
              }
            ]
            """.trimIndent(),
        )
        val output = mutableListOf<String>()

        val code = EngineCli.run(
            arrayOf("parse-source", sourceFile.toString()),
            out = output::add,
        )

        code shouldBe 0
        output.single().contains(""""count": 2""") shouldBe true
        output.single().contains(""""sourceId": "https://a.example"""") shouldBe true
        output.single().contains(""""enabled": false""") shouldBe true
    }

    "batch-search prints summary json with static responses" {
        val sourceFile = Files.createTempFile("legadohub-batch-source-", ".json")
        val responseFile = Files.createTempFile("legadohub-batch-response-", ".json")
        Files.writeString(
            sourceFile,
            """
            [
              {
                "bookSourceName": "源 A",
                "bookSourceUrl": "https://a.example",
                "searchUrl": "/search?q={{key}}",
                "ruleSearch": {
                  "bookList": ".book",
                  "name": ".name@text",
                  "author": ".author@text",
                  "bookUrl": ".name@href"
                }
              }
            ]
            """.trimIndent(),
        )
        Files.writeString(
            responseFile,
            """
            {
              "https://a.example/search?q=%E5%87%A1%E4%BA%BA": "<div class=\"book\"><a class=\"name\" href=\"/book/1\">凡人修仙传</a><span class=\"author\">忘语</span></div>"
            }
            """.trimIndent(),
        )
        val output = mutableListOf<String>()

        val code = EngineCli.run(
            arrayOf("batch-search", sourceFile.toString(), "凡人", responseFile.toString()),
            out = output::add,
        )

        code shouldBe 0
        output.single().contains(""""keyword": "凡人"""") shouldBe true
        output.single().contains(""""name": "凡人修仙传"""") shouldBe true
        output.single().contains(""""type": "batch_finished"""") shouldBe true
    }
})
