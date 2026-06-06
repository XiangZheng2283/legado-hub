package io.legado.app.model.webBook

import io.legado.app.data.entities.Book
import io.legado.app.data.entities.BookSource
import io.legado.app.model.analyzeRule.AnalyzeRule
import legadohub.engine.runtime.EngineCookieStore
import legadohub.engine.runtime.EngineHttpRuntime

object BookInfo {
    fun analyzeBookInfo(
        bookSource: BookSource,
        book: Book,
        baseUrl: String,
        redirectUrl: String,
        body: String,
        canReName: Boolean = true,
        httpRuntime: EngineHttpRuntime? = null,
        cookieStore: EngineCookieStore? = null,
    ): Book {
        val infoRule = bookSource.getBookInfoRule()
        val analyzeRule = AnalyzeRule(
            book,
            bookSource,
            httpRuntime = httpRuntime,
            cookieStore = cookieStore,
        ).setContent(body, baseUrl)
        val target = infoRule.init?.takeIf { it.isNotBlank() }?.let {
            analyzeRule.getElements(it).firstOrNull()
        } ?: body

        analyzeRule.getString(infoRule.name, target)?.trim()?.takeIf { it.isNotBlank() }?.let {
            if (canReName || book.name.isBlank()) book.name = it
        }
        analyzeRule.getString(infoRule.author, target)?.trim()?.takeIf { it.isNotBlank() }?.let {
            if (canReName || book.author.isBlank()) book.author = it
        }
        book.intro = analyzeRule.getString(infoRule.intro, target)?.trim()?.ifBlank { book.intro }
        book.kind = analyzeRule.getString(infoRule.kind, target)?.trim()?.ifBlank { book.kind }
        book.latestChapterTitle = analyzeRule.getString(infoRule.lastChapter, target)?.trim()?.ifBlank {
            book.latestChapterTitle
        }
        book.updateTime = analyzeRule.getString(infoRule.updateTime, target)?.trim()?.ifBlank { book.updateTime }
        book.wordCount = analyzeRule.getString(infoRule.wordCount, target)?.trim()?.ifBlank { book.wordCount }
        book.coverUrl = analyzeRule.getString(infoRule.coverUrl, target, isUrl = true)?.trim()?.ifBlank {
            book.coverUrl
        }
        book.tocUrl = analyzeRule.getString(infoRule.tocUrl, target, isUrl = true)
            ?.trim()
            ?.ifBlank { null }
            ?: redirectUrl
        if (book.tocUrl == redirectUrl || book.tocUrl == baseUrl) {
            book.tocHtml = body
        }
        return book
    }
}
