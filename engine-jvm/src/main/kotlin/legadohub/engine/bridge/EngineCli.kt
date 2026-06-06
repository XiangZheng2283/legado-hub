package legadohub.engine.bridge

import legadohub.engine.port.BookSourcePortParser
import io.legado.app.data.entities.BookSource
import io.legado.app.model.webBook.WebBook
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.Json
import legadohub.engine.batch.BatchSearchConfig
import legadohub.engine.batch.BatchSearchRunner
import legadohub.engine.runtime.OkHttpEngineRuntime
import legadohub.engine.runtime.StaticHttpRuntime
import kotlinx.coroutines.withTimeout
import java.io.PrintStream
import java.nio.charset.StandardCharsets
import java.nio.file.Files
import java.nio.file.Path
import kotlin.system.exitProcess

object EngineCli {
    const val VERSION = "0.0.1"

    private val json = Json {
        prettyPrint = true
        explicitNulls = false
    }

    fun run(
        args: Array<String>,
        out: (String) -> Unit = ::println,
        err: (String) -> Unit = System.err::println,
    ): Int =
        when (args.firstOrNull()) {
            null, "help", "--help", "-h" -> {
                out(usage())
                0
            }

            "version", "--version", "-v" -> {
                out(VERSION)
                0
            }

            "parse-source" -> parseSource(args.drop(1), out, err)
            "batch-search" -> batchSearch(args.drop(1), out, err)
            "source-smoke" -> sourceSmoke(args.drop(1), out, err)
            else -> {
                err("未知命令: ${args.first()}")
                err(usage())
                2
            }
        }

    private fun parseSource(
        args: List<String>,
        out: (String) -> Unit,
        err: (String) -> Unit,
    ): Int {
        val pathText = args.firstOrNull()
        if (pathText.isNullOrBlank()) {
            err("parse-source 需要传入书源 JSON 文件路径")
            return 2
        }

        return runCatching {
            val sources = BookSourcePortParser().parseMany(Files.readString(Path.of(pathText)))
            SourceParseSummary(
                count = sources.size,
                sources = sources.map { source ->
                    SourceParseEntry(
                        sourceId = source.bookSourceUrl,
                        name = source.bookSourceName,
                        group = source.bookSourceGroup,
                        enabled = source.enabled,
                        enabledExplore = source.enabledExplore,
                        valid = source.bookSourceUrl.isNotBlank() && source.bookSourceName.isNotBlank(),
                        invalidReason = when {
                            source.bookSourceUrl.isBlank() -> "bookSourceUrl 不能为空"
                            source.bookSourceName.isBlank() -> "bookSourceName 不能为空"
                            else -> null
                        },
                    )
                },
            )
        }.fold(
            onSuccess = { summary ->
                out(json.encodeToString(summary))
                0
            },
            onFailure = { cause ->
                err("书源解析失败: ${cause.message}")
                1
            },
        )
    }

    private fun sourceSmoke(
        args: List<String>,
        out: (String) -> Unit,
        err: (String) -> Unit,
    ): Int {
        val sourcesPath = args.getOrNull(0)
        val selector = args.getOrNull(1)
        val keyword = args.getOrNull(2)
        val stageTimeoutMs = args.getOrNull(3)?.toLongOrNull() ?: 15_000L
        if (sourcesPath.isNullOrBlank() || selector.isNullOrBlank() || keyword.isNullOrBlank()) {
            err("source-smoke 需要传入书源 JSON 文件路径、书源 ID/名称片段和关键词")
            return 2
        }

        return runCatching {
            val sources = BookSourcePortParser().parseMany(Files.readString(Path.of(sourcesPath)))
            val source = selectSource(sources, selector)
                ?: error("未找到书源: $selector")
            runBlocking {
                runSourceSmoke(source.copy(respondTime = stageTimeoutMs), keyword, stageTimeoutMs)
            }
        }.fold(
            onSuccess = { summary ->
                out(json.encodeToString(summary))
                0
            },
            onFailure = { cause ->
                err("真实书源 smoke 失败: ${cause.message}")
                1
            },
        )
    }

    private fun selectSource(sources: List<BookSource>, selector: String): BookSource? =
        sources.firstOrNull { it.bookSourceUrl == selector || it.bookSourceName == selector }
            ?: sources.firstOrNull {
                it.bookSourceUrl.contains(selector, ignoreCase = true) ||
                    it.bookSourceName.contains(selector, ignoreCase = true)
            }

    private suspend fun runSourceSmoke(
        source: BookSource,
        keyword: String,
        stageTimeoutMs: Long,
    ): SourceSmokeSummary {
        val webBook = WebBook(OkHttpEngineRuntime())
        var firstBook: io.legado.app.data.entities.Book? = null
        var firstChapter: io.legado.app.data.entities.BookChapter? = null

        val search = smokeStage(stageTimeoutMs) {
            val books = webBook.searchBookAwait(source, keyword)
            firstBook = books.firstOrNull()?.toBook()
            SourceSmokeStage(
                ok = books.isNotEmpty(),
                count = books.size,
                title = books.firstOrNull()?.name,
                url = books.firstOrNull()?.bookUrl,
                sample = books.take(3).joinToString(" | ") { "${it.name}/${it.author}" },
                elapsedMs = 0,
                message = if (books.isEmpty()) "搜索结果为空" else null,
                errorCode = if (books.isEmpty()) "PARSE_EMPTY" else null,
            )
        }

        val detail = firstBook?.let { book ->
            smokeStage(stageTimeoutMs) {
                val detailed = webBook.getBookInfoAwait(source, book)
                SourceSmokeStage(
                    ok = detailed.tocUrl.isNotBlank() || detailed.name.isNotBlank(),
                    title = detailed.name,
                    url = detailed.tocUrl.ifBlank { detailed.bookUrl },
                    sample = listOf(detailed.author, detailed.kind, detailed.latestChapterTitle)
                        .filterNot { it.isNullOrBlank() }
                        .joinToString(" | ")
                        .ifBlank { null },
                    elapsedMs = 0,
                )
            }
        }

        val toc = firstBook?.let { book ->
            smokeStage(stageTimeoutMs) {
                val chapters = webBook.getChapterListAwait(source, book)
                firstChapter = chapters.firstOrNull { !it.isVolume } ?: chapters.firstOrNull()
                SourceSmokeStage(
                    ok = chapters.isNotEmpty(),
                    count = chapters.size,
                    title = firstChapter?.title,
                    url = firstChapter?.url,
                    sample = chapters.take(3).joinToString(" | ") { it.title },
                    elapsedMs = 0,
                    message = if (chapters.isEmpty()) "目录为空" else null,
                    errorCode = if (chapters.isEmpty()) "PARSE_EMPTY" else null,
                )
            }
        }

        val content = firstBook?.let { book ->
            firstChapter?.let { chapter ->
                smokeStage(stageTimeoutMs) {
                    val text = webBook.getContentAwait(source, book, chapter)
                    SourceSmokeStage(
                        ok = text.isNotBlank(),
                        count = text.length,
                        title = chapter.title,
                        url = chapter.url,
                        sample = text.replace(Regex("\\s+"), " ").take(160),
                        elapsedMs = 0,
                        message = if (text.isBlank()) "正文为空" else null,
                        errorCode = if (text.isBlank()) "PARSE_EMPTY" else null,
                    )
                }
            }
        }

        val kinds = smokeStage(stageTimeoutMs) {
            val items = webBook.exploreKinds(source)
            val firstUsable = items.firstOrNull { !it.url.isNullOrBlank() }
            SourceSmokeStage(
                ok = items.isNotEmpty(),
                count = items.size,
                title = firstUsable?.title ?: items.firstOrNull()?.title,
                url = firstUsable?.url,
                sample = items.take(5).joinToString(" | ") { "${it.title}:${it.url.orEmpty()}" },
                elapsedMs = 0,
                message = if (items.isEmpty()) "发现分类为空" else null,
                errorCode = if (items.isEmpty()) "PARSE_EMPTY" else null,
            )
        }

        val explore = kinds.url?.takeIf { kinds.ok && it.isNotBlank() }?.let { url ->
            smokeStage(stageTimeoutMs) {
                val books = webBook.exploreBookAwait(source, url, page = 1)
                SourceSmokeStage(
                    ok = books.isNotEmpty(),
                    count = books.size,
                    title = books.firstOrNull()?.name,
                    url = books.firstOrNull()?.bookUrl,
                    sample = books.take(3).joinToString(" | ") { "${it.name}/${it.author}" },
                    elapsedMs = 0,
                    message = if (books.isEmpty()) "发现结果为空" else null,
                    errorCode = if (books.isEmpty()) "PARSE_EMPTY" else null,
                )
            }
        }

        return SourceSmokeSummary(
            sourceId = source.bookSourceUrl,
            sourceName = source.bookSourceName,
            keyword = keyword,
            search = search,
            detail = detail,
            toc = toc,
            content = content,
            exploreKinds = kinds,
            explore = explore,
        )
    }

    private suspend fun smokeStage(
        timeoutMs: Long,
        block: suspend () -> SourceSmokeStage,
    ): SourceSmokeStage {
        val startedAt = System.currentTimeMillis()
        return runCatching {
            withTimeout(timeoutMs) {
                block()
            }.copy(elapsedMs = System.currentTimeMillis() - startedAt)
        }.getOrElse { cause ->
            SourceSmokeStage(
                ok = false,
                errorCode = classifySmokeFailure(cause),
                message = cause.message ?: cause::class.simpleName,
                elapsedMs = System.currentTimeMillis() - startedAt,
            )
        }
    }

    private fun classifySmokeFailure(cause: Throwable): String {
        val message = cause.message.orEmpty()
        val className = cause::class.qualifiedName.orEmpty()
        val lowerMessage = message.lowercase()
        val lowerClassName = className.lowercase()
        return when {
            "WEBVIEW_REQUIRED" in message -> "WEBVIEW_REQUIRED"
            "LOGIN_REQUIRED" in message -> "LOGIN_REQUIRED"
            "PROXY" in message.uppercase() || "Proxy" in className -> "PROXY_ERROR"
            "HTTP 4" in message -> "HTTP_4XX"
            "HTTP 5" in message -> "HTTP_5XX"
            "too many follow-up requests" in lowerMessage -> "REDIRECT_LOOP"
            "timeout" in lowerMessage || "timed out" in lowerMessage || "timeoutexception" in lowerClassName ->
                "SOURCE_TIMEOUT"
            "handshake" in lowerMessage ||
                "unable to resolve host" in lowerMessage ||
                "unknownhost" in lowerClassName ||
                "ssl" in lowerClassName ||
                "socket" in lowerClassName ->
                "NETWORK_ERROR"
            "JS" in message.uppercase() || "javascript" in lowerClassName || "rhino" in lowerClassName -> "JS_ERROR"
            else -> "SOURCE_ERROR"
        }
    }

    private fun batchSearch(
        args: List<String>,
        out: (String) -> Unit,
        err: (String) -> Unit,
    ): Int {
        val sourcesPath = args.getOrNull(0)
        val keyword = args.getOrNull(1)
        if (sourcesPath.isNullOrBlank() || keyword.isNullOrBlank()) {
            err("batch-search 需要传入书源 JSON 文件路径和关键词")
            return 2
        }
        val staticResponsesPath = args.getOrNull(2)
        return runCatching {
            val sources = BookSourcePortParser().parseMany(Files.readString(Path.of(sourcesPath)))
            val runtime = if (staticResponsesPath.isNullOrBlank()) {
                OkHttpEngineRuntime()
            } else {
                val raw = json.decodeFromString<JsonObject>(Files.readString(Path.of(staticResponsesPath)))
                StaticHttpRuntime(raw.mapValues { it.value.jsonPrimitive.content })
            }
            runBlocking {
                BatchSearchRunner(
                    runtime = runtime,
                    config = BatchSearchConfig(),
                ).search(sources, keyword)
            }
        }.fold(
            onSuccess = { summary ->
                out(json.encodeToString(summary))
                0
            },
            onFailure = { cause ->
                err("批量搜索失败: ${cause.message}")
                1
            },
        )
    }

    private fun usage(): String =
        """
        LegadoHub Engine $VERSION

        Commands:
          version
          parse-source <path>
          batch-search <sources-path> <keyword> [static-responses-json]
          source-smoke <sources-path> <source-id-or-name> <keyword> [stage-timeout-ms]
        """.trimIndent()
}

fun main(args: Array<String>) {
    System.setOut(PrintStream(System.out, true, StandardCharsets.UTF_8))
    System.setErr(PrintStream(System.err, true, StandardCharsets.UTF_8))
    exitProcess(EngineCli.run(args))
}
