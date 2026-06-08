package io.legado.app.model.webBook

import io.legado.app.data.entities.Book
import io.legado.app.data.entities.BookChapter
import io.legado.app.data.entities.BookSource
import io.legado.app.model.analyzeRule.AnalyzeRule
import legadohub.engine.runtime.EngineCookieStore
import legadohub.engine.runtime.EngineHttpRuntime

object BookChapterList {
    fun analyzeChapterList(
        bookSource: BookSource,
        book: Book,
        baseUrl: String,
        redirectUrl: String,
        body: String,
        httpRuntime: EngineHttpRuntime? = null,
        cookieStore: EngineCookieStore? = null,
    ): List<BookChapter> {
        val chapters = analyzeChapterPage(
            bookSource = bookSource,
            book = book,
            baseUrl = baseUrl,
            redirectUrl = redirectUrl,
            body = body,
            httpRuntime = httpRuntime,
            cookieStore = cookieStore,
        ).chapters.distinctBy { it.url.ifBlank { it.title } }.mapIndexed { index, chapter ->
            chapter.copy(index = index)
        }
        return formatChapters(bookSource, book, chapters, httpRuntime, cookieStore)
    }

    fun analyzeChapterPage(
        bookSource: BookSource,
        book: Book,
        baseUrl: String,
        redirectUrl: String,
        body: String,
        httpRuntime: EngineHttpRuntime? = null,
        cookieStore: EngineCookieStore? = null,
    ): ChapterPage {
        val tocRule = bookSource.getTocRule()
        val analyzeRule = AnalyzeRule(
            book,
            bookSource,
            httpRuntime = httpRuntime,
            cookieStore = cookieStore,
        ).setContent(body, baseUrl)
        val elements = analyzeRule.getElements(tocRule.chapterList)
        val chapters = elements.mapIndexedNotNull { index, element ->
            val title = analyzeRule.getString(tocRule.chapterName, element)?.trim().orEmpty()
            if (title.isBlank()) return@mapIndexedNotNull null
            val url = analyzeRule.getString(tocRule.chapterUrl, element, isUrl = true)
                ?.trim()
                ?.ifBlank { null }
                ?: redirectUrl
            BookChapter(
                title = title,
                url = url,
                index = index,
                baseUrl = baseUrl,
                isVolume = analyzeRule.getString(tocRule.isVolume, element)?.toBooleanStrictOrNull() ?: false,
                isVip = analyzeRule.getString(tocRule.isVip, element)?.toBooleanStrictOrNull() ?: false,
                isPay = analyzeRule.getString(tocRule.isPay, element)?.toBooleanStrictOrNull() ?: false,
                updateTime = analyzeRule.getString(tocRule.updateTime, element)?.trim()?.ifBlank { null },
            )
        }
        val nextUrls = analyzeRule.getStringList(tocRule.nextTocUrl, isUrl = true)
            .orEmpty()
            .map { it.trim() }
            .filter { it.isNotBlank() && it != redirectUrl }
        return ChapterPage(
            chapters = chapters.distinctBy { it.url.ifBlank { it.title } },
            nextUrls = nextUrls.distinct(),
        )
    }

    fun formatChapters(
        bookSource: BookSource,
        book: Book,
        chapters: List<BookChapter>,
        httpRuntime: EngineHttpRuntime? = null,
        cookieStore: EngineCookieStore? = null,
    ): List<BookChapter> {
        val formatJs = bookSource.getTocRule().formatJs?.takeIf { it.isNotBlank() }
            ?: return chapters
        var gInt = 0
        val analyzeRule = AnalyzeRule(
            book,
            bookSource,
            httpRuntime = httpRuntime,
            cookieStore = cookieStore,
        ).setBaseUrl(book.tocUrl.ifBlank { book.bookUrl }.ifBlank { bookSource.bookSourceUrl })
        return chapters.mapIndexed { index, chapter ->
            val formatted = runCatching {
                analyzeRule.evalJS(
                    formatJs,
                    result = null,
                    extraBindings = mapOf(
                        "gInt" to gInt,
                        "index" to index + 1,
                        "chapter" to chapter,
                        "title" to chapter.title,
                    ),
                )?.toString()
            }.getOrNull()
            gInt += 1
            if (formatted.isNullOrBlank()) chapter else chapter.copy(title = formatted)
        }
    }
}

data class ChapterPage(
    val chapters: List<BookChapter>,
    val nextUrls: List<String> = emptyList(),
)
