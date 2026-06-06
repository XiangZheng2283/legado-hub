package legadohub.engine.port

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.collections.shouldHaveSize
import io.kotest.matchers.shouldBe
import io.legado.app.data.entities.BookSource
import java.nio.file.Files
import java.nio.file.Path

class BookSourcePortTest : StringSpec({
    val parser = BookSourcePortParser()

    "ported BookSource keeps Reading identity behavior" {
        val source = BookSource(
            bookSourceName = "测试源",
            bookSourceUrl = "https://example.com",
            bookSourceGroup = "默认,测试",
        )
        val sameIdentity = source.copy(bookSourceName = "另一个名字")

        source.getTag() shouldBe "测试源"
        source.getKey() shouldBe "https://example.com"
        source.getDisPlayNameGroup() shouldBe "测试源 (默认,测试)"
        (source == sameIdentity) shouldBe true
    }

    "ported BookSource parses rule objects with Reading field names" {
        val source = parser.parseOne(
            """
            {
              "bookSourceName": "测试源",
              "bookSourceUrl": "https://example.com",
              "searchUrl": "/search?q={{key}}",
              "ruleSearch": {
                "bookList": ".book",
                "name": ".name@text",
                "bookUrl": ".name@href"
              },
              "ruleBookInfo": {
                "name": "h1@text",
                "tocUrl": ".toc@href"
              },
              "ruleToc": {
                "chapterList": ".chapter",
                "chapterName": "a@text"
              },
              "ruleContent": {
                "title": "h1@text",
                "content": "#content@text"
              }
            }
            """.trimIndent(),
        )

        source.getKey() shouldBe "https://example.com"
        source.getSearchRule().bookList shouldBe ".book"
        source.getBookInfoRule().tocUrl shouldBe ".toc@href"
        source.getTocRule().chapterName shouldBe "a@text"
        source.getContentRule().content shouldBe "#content@text"
    }

    "ported parser imports XIU2 Yuedu snapshot as independent BookSource objects" {
        val path = findRepoFile("data/sources/raw/by-site/legado/sub-xiu2_yuedu.json")

        val sources = parser.parseMany(Files.readString(path))

        sources shouldHaveSize 26
        sources.distinctBy { it.bookSourceUrl } shouldHaveSize 26
        sources.first().bookSourceName shouldBe "起点中文"
        sources.first().bookSourceUrl shouldBe "https://www.qidian.com"
    }
})

private fun findRepoFile(relativePath: String): Path {
    var current: Path? = Path.of("").toAbsolutePath()
    while (current != null) {
        val candidate = current.resolve(relativePath)
        if (Files.exists(candidate)) return candidate
        current = current.parent
    }
    return Path.of(relativePath)
}
