package io.legado.app.model.webBook

import io.legado.app.data.entities.Book
import io.legado.app.data.entities.BookChapter
import io.legado.app.data.entities.BookSource
import io.legado.app.model.analyzeRule.AnalyzeRule
import legadohub.engine.runtime.EngineCookieStore
import legadohub.engine.runtime.EngineHttpRuntime

object BookContent {
    fun analyzeContent(
        bookSource: BookSource,
        book: Book,
        bookChapter: BookChapter,
        baseUrl: String,
        redirectUrl: String,
        body: String,
        httpRuntime: EngineHttpRuntime? = null,
        cookieStore: EngineCookieStore? = null,
    ): String {
        val page = analyzeContentPage(
            bookSource = bookSource,
            book = book,
            bookChapter = bookChapter,
            baseUrl = baseUrl,
            redirectUrl = redirectUrl,
            body = body,
            httpRuntime = httpRuntime,
            cookieStore = cookieStore,
        )
        return postProcessContent(
            bookSource = bookSource,
            book = book,
            bookChapter = bookChapter,
            baseUrl = baseUrl,
            content = page.content,
            httpRuntime = httpRuntime,
            cookieStore = cookieStore,
        )
    }

    fun analyzeContentPage(
        bookSource: BookSource,
        book: Book,
        bookChapter: BookChapter,
        baseUrl: String,
        redirectUrl: String,
        body: String,
        httpRuntime: EngineHttpRuntime? = null,
        cookieStore: EngineCookieStore? = null,
    ): ContentPage {
        val contentRule = bookSource.getContentRule()
        val analyzeRule = AnalyzeRule(
            book,
            bookSource,
            httpRuntime = httpRuntime,
            cookieStore = cookieStore,
        ).setContent(body, baseUrl)
        analyzeRule.getString(contentRule.title)?.trim()?.takeIf { it.isNotBlank() }?.let {
            bookChapter.title = it
        }
        val content = analyzeRule.getString(contentRule.content)
            ?.trim()
            ?.ifBlank { null }
            ?: ""
        val nextUrls = analyzeRule.getStringList(contentRule.nextContentUrl, isUrl = true)
            .orEmpty()
            .map { it.trim() }
            .filter { it.isNotBlank() && it != redirectUrl }
        return ContentPage(content, nextUrls.distinct())
    }

    fun postProcessContent(
        bookSource: BookSource,
        book: Book,
        bookChapter: BookChapter,
        baseUrl: String,
        content: String,
        httpRuntime: EngineHttpRuntime? = null,
        cookieStore: EngineCookieStore? = null,
    ): String {
        val replaceRegex = bookSource.getContentRule().replaceRegex
            ?.takeIf { it.isNotBlank() }
            ?: return content
        return if (replaceRegex.startsWith("##")) {
            applyReplaceRegex(content, replaceRegex)
        } else {
            AnalyzeRule(
                book,
                bookSource,
                httpRuntime = httpRuntime,
                cookieStore = cookieStore,
            ).setContent(content, baseUrl).getString(replaceRegex, content) ?: content
        }.trim()
    }

    private fun applyReplaceRegex(content: String, replaceRegex: String): String {
        val body = replaceRegex.removePrefix("##")
        val marker = body.indexOf("##")
        val pattern = if (marker == -1) body else body.substring(0, marker)
        val replacement = if (marker == -1) "" else body.substring(marker + 2)
        if (pattern.isBlank()) return content
        return runCatching { Regex(pattern).replace(content, replacement) }.getOrDefault(content)
    }
}

data class ContentPage(
    val content: String,
    val nextUrls: List<String> = emptyList(),
)
