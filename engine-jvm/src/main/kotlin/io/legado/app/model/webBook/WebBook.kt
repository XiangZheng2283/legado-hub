package io.legado.app.model.webBook

import io.legado.app.data.entities.Book
import io.legado.app.data.entities.BookChapter
import io.legado.app.data.entities.BookSource
import io.legado.app.data.entities.SearchBook
import io.legado.app.data.entities.rule.ExploreKind
import io.legado.app.model.analyzeRule.AnalyzeRule
import io.legado.app.model.analyzeRule.AnalyzeUrl
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json
import legadohub.engine.runtime.EngineCookieStore
import legadohub.engine.runtime.EngineHttpRequestV2
import legadohub.engine.runtime.EngineHttpRuntime
import legadohub.engine.runtime.EngineHttpStatusException
import legadohub.engine.runtime.EngineSourceExecutionException
import legadohub.engine.runtime.EngineTraceEvent

class WebBook(
    private val runtime: EngineHttpRuntime,
    private val cookieStore: EngineCookieStore? = null,
    private val onTrace: suspend (EngineTraceEvent) -> Unit = {},
) {
    suspend fun searchBookAwait(
        bookSource: BookSource,
        key: String,
        page: Int? = 1,
    ): ArrayList<SearchBook> {
        val searchUrl = requireNotNull(bookSource.searchUrl) { "搜索url不能为空" }
        val response = request(
            bookSource,
            AnalyzeUrl(
                mUrl = searchUrl,
                key = key,
                page = page,
                baseUrl = bookSource.bookSourceUrl,
                source = bookSource,
                httpRuntime = runtime,
                cookieStore = cookieStore,
            ),
            "search",
        )
        val baseUrl = response.finalUrl ?: response.urlFallback()
        emit(bookSource, "search.parse", "parse_started", url = baseUrl)
        return runCatching {
            BookList.analyzeBookList(
                bookSource,
                baseUrl,
                response.body,
                true,
                runtime,
                cookieStore,
            )
        }.onSuccess { books ->
            emit(bookSource, "search.parse", "parse_finished", url = baseUrl, message = "results=${books.size}")
        }.onFailure { cause ->
            emit(bookSource, "search.parse", "parse_failed", url = baseUrl, message = cause.message)
        }.getOrThrow()
    }

    fun exploreKinds(bookSource: BookSource): List<ExploreKind> {
        val exploreUrl = bookSource.exploreUrl?.trim().orEmpty()
        if (exploreUrl.isBlank()) return emptyList()
        val ruleText = when {
            exploreUrl.startsWith("@js:", true) -> {
                AnalyzeRule(source = bookSource, httpRuntime = runtime, cookieStore = cookieStore)
                    .setBaseUrl(bookSource.bookSourceUrl)
                    .evalJS(exploreUrl.substringAfter(":"))
                    ?.toString()
                    ?.trim()
                    .orEmpty()
            }

            exploreUrl.startsWith("<js>", true) -> {
                val js = exploreUrl.substringAfter("<js>").substringBeforeLast("<")
                AnalyzeRule(source = bookSource, httpRuntime = runtime, cookieStore = cookieStore)
                    .setBaseUrl(bookSource.bookSourceUrl)
                    .evalJS(js)
                    ?.toString()
                    ?.trim()
                    .orEmpty()
            }

            else -> exploreUrl
        }
        return parseExploreKinds(ruleText)
    }

    suspend fun exploreBookAwait(
        bookSource: BookSource,
        url: String,
        page: Int? = 1,
    ): ArrayList<SearchBook> {
        val response = request(
            bookSource,
            AnalyzeUrl(
                mUrl = url,
                page = page,
                baseUrl = bookSource.bookSourceUrl,
                source = bookSource,
                httpRuntime = runtime,
                cookieStore = cookieStore,
            ),
            "explore",
        )
        val baseUrl = response.finalUrl ?: response.urlFallback()
        emit(bookSource, "explore.parse", "parse_started", url = baseUrl)
        return runCatching {
            BookList.analyzeBookList(
                bookSource,
                baseUrl,
                response.body,
                false,
                runtime,
                cookieStore,
            )
        }.onSuccess { books ->
            emit(bookSource, "explore.parse", "parse_finished", url = baseUrl, message = "results=${books.size}")
        }.onFailure { cause ->
            emit(bookSource, "explore.parse", "parse_failed", url = baseUrl, message = cause.message)
        }.getOrThrow()
    }

    suspend fun getBookInfoAwait(
        bookSource: BookSource,
        book: Book,
        canReName: Boolean = true,
    ): Book {
        if (!book.infoHtml.isNullOrBlank()) {
            return BookInfo.analyzeBookInfo(
                bookSource,
                book,
                book.bookUrl,
                book.bookUrl,
                book.infoHtml!!,
                canReName,
                runtime,
                cookieStore,
            )
        }
        val response = request(
            bookSource,
            AnalyzeUrl(
                mUrl = book.bookUrl,
                baseUrl = bookSource.bookSourceUrl,
                source = bookSource,
                httpRuntime = runtime,
                cookieStore = cookieStore,
            ),
            "detail",
        )
        val redirectUrl = response.finalUrl ?: book.bookUrl
        emit(bookSource, "detail.parse", "parse_started", url = redirectUrl)
        return runCatching {
            BookInfo.analyzeBookInfo(
                bookSource = bookSource,
                book = book,
                baseUrl = book.bookUrl,
                redirectUrl = redirectUrl,
                body = response.body,
                canReName = canReName,
                httpRuntime = runtime,
                cookieStore = cookieStore,
            )
        }.onSuccess {
            emit(bookSource, "detail.parse", "parse_finished", url = redirectUrl, message = "tocUrl=${it.tocUrl}")
        }.onFailure { cause ->
            emit(bookSource, "detail.parse", "parse_failed", url = redirectUrl, message = cause.message)
        }.getOrThrow()
    }

    suspend fun getChapterListAwait(
        bookSource: BookSource,
        book: Book,
    ): List<BookChapter> {
        val body = book.tocHtml
        val tocUrl = book.tocUrl.ifBlank { book.bookUrl }
        val response = if (body.isNullOrBlank()) {
            request(
                bookSource,
                buildAnalyzeUrl(bookSource, tocUrl, bookSource.bookSourceUrl),
                "toc",
            )
        } else {
            null
        }
        val redirectUrl = response?.finalUrl ?: tocUrl
        val pageBody = body ?: response?.body.orEmpty()
        emit(bookSource, "toc.parse", "parse_started", url = redirectUrl)
        return runCatching {
            collectChapterPages(bookSource, book, tocUrl, redirectUrl, pageBody)
        }.onSuccess { chapters ->
            emit(bookSource, "toc.parse", "parse_finished", url = redirectUrl, message = "chapters=${chapters.size}")
        }.onFailure { cause ->
            emit(bookSource, "toc.parse", "parse_failed", url = redirectUrl, message = cause.message)
        }.getOrThrow()
    }

    suspend fun getContentAwait(
        bookSource: BookSource,
        book: Book,
        chapter: BookChapter,
    ): String {
        val response = request(
            bookSource,
            buildAnalyzeUrl(bookSource, chapter.url, bookSource.bookSourceUrl),
            "content",
        )
        val redirectUrl = response.finalUrl ?: chapter.url
        emit(bookSource, "content.parse", "parse_started", url = redirectUrl)
        return runCatching {
            collectContentPages(bookSource, book, chapter, chapter.url, redirectUrl, response.body)
        }.onSuccess { content ->
            emit(bookSource, "content.parse", "parse_finished", url = redirectUrl, message = "length=${content.length}")
        }.onFailure { cause ->
            emit(bookSource, "content.parse", "parse_failed", url = redirectUrl, message = cause.message)
        }.getOrThrow()
    }

    private suspend fun collectChapterPages(
        bookSource: BookSource,
        book: Book,
        baseUrl: String,
        redirectUrl: String,
        body: String,
    ): List<BookChapter> {
        val chapters = mutableListOf<BookChapter>()
        val pending = ArrayDeque<String>()
        val visited = linkedSetOf<String>()

        fun addPage(page: ChapterPage, currentUrl: String) {
            chapters += page.chapters
            visited += currentUrl
            page.nextUrls.filterNot { it in visited || it in pending }.forEach(pending::addLast)
        }

        addPage(
            BookChapterList.analyzeChapterPage(bookSource, book, baseUrl, redirectUrl, body, runtime, cookieStore),
            redirectUrl,
        )
        while (pending.isNotEmpty() && visited.size < MAX_NEXT_PAGES) {
            val nextUrl = pending.removeFirst()
            if (!visited.add(nextUrl)) continue
            val response = request(bookSource, buildAnalyzeUrl(bookSource, nextUrl, redirectUrl), "toc.next")
            val finalUrl = response.finalUrl ?: nextUrl
            val page = BookChapterList.analyzeChapterPage(
                bookSource = bookSource,
                book = book,
                baseUrl = nextUrl,
                redirectUrl = finalUrl,
                body = response.body,
                httpRuntime = runtime,
                cookieStore = cookieStore,
            )
            chapters += page.chapters
            page.nextUrls.filterNot { it in visited || it in pending }.forEach(pending::addLast)
        }
        val finalChapters = chapters.distinctBy { it.url.ifBlank { it.title } }.mapIndexed { index, chapter ->
            chapter.copy(index = index)
        }
        return BookChapterList.formatChapters(bookSource, book, finalChapters, runtime, cookieStore)
    }

    private suspend fun collectContentPages(
        bookSource: BookSource,
        book: Book,
        chapter: BookChapter,
        baseUrl: String,
        redirectUrl: String,
        body: String,
    ): String {
        val contents = mutableListOf<String>()
        val pending = ArrayDeque<String>()
        val visited = linkedSetOf<String>()

        fun addPage(page: ContentPage, currentUrl: String) {
            page.content.takeIf { it.isNotBlank() }?.let(contents::add)
            visited += currentUrl
            page.nextUrls.filterNot { it in visited || it in pending }.forEach(pending::addLast)
        }

        addPage(
            BookContent.analyzeContentPage(bookSource, book, chapter, baseUrl, redirectUrl, body, runtime, cookieStore),
            redirectUrl,
        )
        while (pending.isNotEmpty() && visited.size < MAX_NEXT_PAGES) {
            val nextUrl = pending.removeFirst()
            if (!visited.add(nextUrl)) continue
            val response = request(bookSource, buildAnalyzeUrl(bookSource, nextUrl, redirectUrl), "content.next")
            val finalUrl = response.finalUrl ?: nextUrl
            val page = BookContent.analyzeContentPage(
                bookSource = bookSource,
                book = book,
                bookChapter = chapter,
                baseUrl = nextUrl,
                redirectUrl = finalUrl,
                body = response.body,
                httpRuntime = runtime,
                cookieStore = cookieStore,
            )
            page.content.takeIf { it.isNotBlank() }?.let(contents::add)
            page.nextUrls.filterNot { it in visited || it in pending }.forEach(pending::addLast)
        }
        return BookContent.postProcessContent(
            bookSource = bookSource,
            book = book,
            bookChapter = chapter,
            baseUrl = baseUrl,
            content = contents.joinToString("\n"),
            httpRuntime = runtime,
            cookieStore = cookieStore,
        )
    }

    private fun buildAnalyzeUrl(
        bookSource: BookSource,
        url: String,
        baseUrl: String,
    ): AnalyzeUrl =
        AnalyzeUrl(
            mUrl = url,
            baseUrl = baseUrl,
            source = bookSource,
            httpRuntime = runtime,
            cookieStore = cookieStore,
        )

    private suspend fun request(
        bookSource: BookSource,
        analyzeUrl: AnalyzeUrl,
        stage: String,
    ): legadohub.engine.runtime.EngineHttpResponseV2 {
        val request = analyzeUrl.toRequestSpec(bookSource.respondTime)
        request.unsupported.firstOrNull()?.let { unsupported ->
            val errorCode = when {
                unsupported.code.startsWith("WEBVIEW", ignoreCase = true) -> "WEBVIEW_REQUIRED"
                unsupported.code == "BODY_JS_REQUIRED" -> "JS_ERROR"
                else -> unsupported.code
            }
            emit(
                bookSource,
                "$stage.request",
                "request_unsupported",
                url = request.url,
                message = unsupported.message,
            )
            throw EngineSourceExecutionException(
                errorCode = errorCode,
                stage = "$stage.request",
                url = request.url,
                message = unsupported.message,
            )
        }
        emit(bookSource, "$stage.request", "request_started", url = request.url)
        val sourceId = bookSource.bookSourceUrl
        val storedCookie = cookieStore?.get(sourceId, request.url)
        val headers = if (!storedCookie.isNullOrBlank() && "Cookie" !in request.headers) {
            request.headers + ("Cookie" to storedCookie)
        } else {
            request.headers
        }
        val response = runtime.execute(
            EngineHttpRequestV2(
                sourceId = sourceId,
                url = request.url,
                method = request.method,
                headers = headers,
                body = request.body,
                charset = request.charset,
                proxy = request.proxy,
                timeoutMs = request.timeoutMs,
            ),
        )
        val responseWithUrl = if (response.finalUrl == null) response.copy(finalUrl = request.url) else response
        responseWithUrl.headers.entries.firstOrNull { it.key.equals("Set-Cookie", true) }
            ?.value
            ?.firstOrNull()
            ?.let { cookieStore?.put(sourceId, responseWithUrl.finalUrl ?: request.url, it) }
        if (responseWithUrl.statusCode >= 400) {
            emit(
                bookSource,
                "$stage.request",
                "request_failed",
                url = responseWithUrl.finalUrl,
                statusCode = responseWithUrl.statusCode,
                elapsedMs = responseWithUrl.elapsedMs,
                message = "HTTP ${responseWithUrl.statusCode}",
            )
            throw EngineHttpStatusException(responseWithUrl.statusCode, responseWithUrl.finalUrl ?: request.url)
        }
        emit(
            bookSource,
            "$stage.request",
            "request_finished",
            url = responseWithUrl.finalUrl,
            statusCode = responseWithUrl.statusCode,
            elapsedMs = responseWithUrl.elapsedMs,
        )
        return responseWithUrl
    }

    private suspend fun emit(
        bookSource: BookSource,
        stage: String,
        type: String,
        url: String? = null,
        statusCode: Int? = null,
        message: String? = null,
        elapsedMs: Long? = null,
    ) {
        onTrace(
            EngineTraceEvent(
                sourceId = bookSource.bookSourceUrl,
                sourceName = bookSource.bookSourceName,
                stage = stage,
                type = type,
                url = url,
                statusCode = statusCode,
                message = message,
                elapsedMs = elapsedMs,
            ),
        )
    }

    private fun legadohub.engine.runtime.EngineHttpResponseV2.urlFallback(): String = finalUrl.orEmpty()

    private companion object {
        const val MAX_NEXT_PAGES = 50
        @OptIn(ExperimentalSerializationApi::class)
        val JSON = Json {
            ignoreUnknownKeys = true
            explicitNulls = false
            isLenient = true
            allowTrailingComma = true
        }

        fun parseExploreKinds(ruleText: String): List<ExploreKind> {
            val clean = ruleText.trim()
            if (clean.isBlank()) return emptyList()
            if (clean.startsWith("[")) {
                return JSON.decodeFromString(clean)
            }
            return clean
                .split(Regex("(&&|\\n)+"))
                .mapNotNull { item ->
                    val kind = item.trim()
                    if (kind.isBlank()) return@mapNotNull null
                    val parts = kind.split("::", limit = 2)
                    ExploreKind(title = parts.first().trim(), url = parts.getOrNull(1)?.trim())
                }
        }
    }
}
