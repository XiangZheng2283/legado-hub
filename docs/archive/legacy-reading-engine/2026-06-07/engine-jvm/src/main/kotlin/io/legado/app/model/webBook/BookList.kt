package io.legado.app.model.webBook

import io.legado.app.data.entities.BookSource
import io.legado.app.data.entities.SearchBook
import io.legado.app.data.entities.rule.BookListRule
import io.legado.app.model.analyzeRule.AnalyzeRule
import legadohub.engine.runtime.EngineCookieStore
import legadohub.engine.runtime.EngineHttpRuntime
import java.net.URI

object BookList {
    fun analyzeBookList(
        bookSource: BookSource,
        baseUrl: String,
        body: String,
        isSearch: Boolean = true,
        httpRuntime: EngineHttpRuntime? = null,
        cookieStore: EngineCookieStore? = null,
    ): ArrayList<SearchBook> {
        val analyzeRule = AnalyzeRule(
            source = bookSource,
            httpRuntime = httpRuntime,
            cookieStore = cookieStore,
        ).setContent(body, baseUrl)
        val bookListRule: BookListRule = if (isSearch) {
            bookSource.getSearchRule()
        } else {
            bookSource.getExploreRule()
        }
        val ruleList = bookListRule.bookList.orEmpty()
        val elements = analyzeRule.getElements(ruleList)
        val books = ArrayList<SearchBook>()

        if (elements.isEmpty()) {
            parseSearchBook(bookSource, analyzeRule, body, baseUrl, bookListRule)?.let(books::add)
            return books
        }

        elements.forEach { element ->
            parseSearchBook(bookSource, analyzeRule, element, baseUrl, bookListRule)?.let(books::add)
        }
        return ArrayList(books.distinctBy { it.origin to it.bookUrl })
    }

    private fun parseSearchBook(
        bookSource: BookSource,
        analyzeRule: AnalyzeRule,
        item: Any,
        baseUrl: String,
        rule: BookListRule,
    ): SearchBook? {
        val name = analyzeRule.getString(rule.name, item)?.trim().orEmpty()
        if (name.isBlank()) return null
        val bookUrl = analyzeRule.getString(rule.bookUrl, item, isUrl = true)
            ?.trim()
            ?.ifBlank { null }
            ?: baseUrl
        return SearchBook(
            name = name,
            author = analyzeRule.getString(rule.author, item)?.trim().orEmpty(),
            bookUrl = absoluteUrl(baseUrl, bookUrl),
            origin = bookSource.bookSourceUrl,
            originName = bookSource.bookSourceName,
            originOrder = bookSource.customOrder,
            coverUrl = analyzeRule.getString(rule.coverUrl, item, isUrl = true)?.trim()?.ifBlank { null },
            intro = analyzeRule.getString(rule.intro, item)?.trim()?.ifBlank { null },
            kind = analyzeRule.getString(rule.kind, item)?.trim()?.ifBlank { null },
            wordCount = analyzeRule.getString(rule.wordCount, item)?.trim()?.ifBlank { null },
            latestChapterTitle = analyzeRule.getString(rule.lastChapter, item)?.trim()?.ifBlank { null },
            updateTime = analyzeRule.getString(rule.updateTime, item)?.trim()?.ifBlank { null },
            type = bookSource.bookSourceType,
        )
    }

    private fun absoluteUrl(baseUrl: String, url: String): String =
        runCatching { URI(baseUrl).resolve(url).toString() }.getOrDefault(url)
}
