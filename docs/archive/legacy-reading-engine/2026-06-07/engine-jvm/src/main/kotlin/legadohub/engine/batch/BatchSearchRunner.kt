package legadohub.engine.batch

import io.legado.app.data.entities.BookSource
import io.legado.app.model.webBook.WebBook
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.Serializable
import legadohub.engine.runtime.EngineHttpStatusException
import legadohub.engine.runtime.EngineHttpRuntime
import legadohub.engine.runtime.EngineSourceExecutionException
import legadohub.engine.runtime.EngineTraceEvent
import java.io.IOException
import java.net.ConnectException
import java.net.URI
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.Collections
import java.util.concurrent.atomic.AtomicInteger

@Serializable
data class BatchSearchConfig(
    val batchSize: Int = 20,
    val globalConcurrency: Int = 20,
    val perHostConcurrency: Int = 2,
    val sourceTimeoutMs: Long = 15_000,
    val requestTimeoutMs: Long = 8_000,
    val overallTimeoutMs: Long = 30_000,
)

@Serializable
data class BatchSearchEvent(
    val type: String,
    val sourceId: String? = null,
    val sourceName: String? = null,
    val stage: String? = null,
    val url: String? = null,
    val statusCode: Int? = null,
    val errorCode: String? = null,
    val message: String? = null,
    val elapsedMs: Long? = null,
    val completed: Int,
    val total: Int,
)

@Serializable
data class BatchSearchBookResult(
    val sourceId: String,
    val sourceName: String,
    val name: String,
    val author: String,
    val bookUrl: String,
    val latestChapterTitle: String? = null,
)

@Serializable
data class BatchSearchSummary(
    val keyword: String,
    val totalSources: Int,
    val completedSources: Int,
    val results: List<BatchSearchBookResult>,
    val events: List<BatchSearchEvent>,
)

class BatchSearchRunner(
    private val runtime: EngineHttpRuntime,
    private val config: BatchSearchConfig = BatchSearchConfig(),
) {
    suspend fun search(
        sources: List<BookSource>,
        keyword: String,
        onEvent: suspend (BatchSearchEvent) -> Unit = {},
    ): BatchSearchSummary = withContext(Dispatchers.Default) {
        val enabledSources = sources.filter { it.enabled }.take(config.batchSize.coerceAtLeast(1))
        val total = enabledSources.size
        val events = Collections.synchronizedList(mutableListOf<BatchSearchEvent>())
        val results = Collections.synchronizedList(mutableListOf<BatchSearchBookResult>())
        val completed = AtomicInteger(0)
        val hostSemaphores = Collections.synchronizedMap(mutableMapOf<String, Semaphore>())

        suspend fun emit(event: BatchSearchEvent) {
            events += event
            onEvent(event)
        }

        withTimeoutOrNull(config.overallTimeoutMs) {
            coroutineScope {
                val globalSemaphore = Semaphore(config.globalConcurrency.coerceAtLeast(1))
                enabledSources.map { source ->
                    async {
                        globalSemaphore.withPermit {
                            val hostSemaphore = synchronized(hostSemaphores) {
                                hostSemaphores.getOrPut(hostKey(source.bookSourceUrl)) {
                                    Semaphore(config.perHostConcurrency.coerceAtLeast(1))
                                }
                            }
                            hostSemaphore.withPermit {
                                runSource(source, keyword, total, completed, results, ::emit)
                            }
                        }
                    }
                }.awaitAll()
            }
        } ?: emit(
            BatchSearchEvent(
                type = "batch_timeout",
                message = "overall timeout ${config.overallTimeoutMs}ms",
                completed = completed.get(),
                total = total,
            ),
        )

        emit(
            BatchSearchEvent(
                type = "batch_finished",
                message = "results=${results.size}",
                completed = completed.get(),
                total = total,
            ),
        )

        BatchSearchSummary(
            keyword = keyword,
            totalSources = total,
            completedSources = completed.get(),
            results = synchronized(results) { results.toList() },
            events = synchronized(events) { events.toList() },
        )
    }

    private suspend fun runSource(
        source: BookSource,
        keyword: String,
        total: Int,
        completed: AtomicInteger,
        results: MutableList<BatchSearchBookResult>,
        emit: suspend (BatchSearchEvent) -> Unit,
    ) {
        emit(
            BatchSearchEvent(
                type = "source_started",
                sourceId = source.bookSourceUrl,
                sourceName = source.bookSourceName,
                completed = completed.get(),
                total = total,
            ),
        )
        val sourceResults = runCatching {
            withTimeout(config.sourceTimeoutMs) {
                WebBook(
                    runtime = runtime,
                    onTrace = { trace ->
                        emit(trace.toBatchEvent(completed.get(), total))
                    },
                ).searchBookAwait(
                    source.copy(respondTime = config.requestTimeoutMs),
                    keyword,
                )
            }
        }
        val completedCount = completed.incrementAndGet()
        sourceResults.fold(
            onSuccess = { books ->
                val mapped = books.map {
                    BatchSearchBookResult(
                        sourceId = source.bookSourceUrl,
                        sourceName = source.bookSourceName,
                        name = it.name,
                        author = it.author,
                        bookUrl = it.bookUrl,
                        latestChapterTitle = it.latestChapterTitle,
                    )
                }
                results += mapped
                emit(
                    BatchSearchEvent(
                        type = if (mapped.isEmpty()) "source_failed" else "source_finished",
                        sourceId = source.bookSourceUrl,
                        sourceName = source.bookSourceName,
                        errorCode = if (mapped.isEmpty()) "PARSE_EMPTY" else null,
                        message = "results=${mapped.size}",
                        completed = completedCount,
                        total = total,
                    ),
                )
            },
            onFailure = { cause ->
                val errorCode = classifyFailure(cause)
                emit(
                    BatchSearchEvent(
                        type = if (errorCode == "SOURCE_TIMEOUT") "source_timed_out" else "source_failed",
                        sourceId = source.bookSourceUrl,
                        sourceName = source.bookSourceName,
                        errorCode = errorCode,
                        message = cause.message ?: cause::class.simpleName,
                        completed = completedCount,
                        total = total,
                    ),
                )
            },
        )
    }

    private fun hostKey(sourceUrl: String): String =
        runCatching { URI(sourceUrl).host }.getOrNull() ?: sourceUrl

    private fun classifyFailure(cause: Throwable): String =
        when (cause) {
            is TimeoutCancellationException -> "SOURCE_TIMEOUT"
            is EngineSourceExecutionException -> cause.errorCode
            is EngineHttpStatusException -> when (cause.statusCode) {
                in 400..499 -> "HTTP_4XX"
                in 500..599 -> "HTTP_5XX"
                else -> "HTTP_STATUS"
            }
            is SocketTimeoutException -> "SOURCE_TIMEOUT"
            is UnknownHostException -> "NETWORK_ERROR"
            is ConnectException -> classifyIoFailure(cause)
            is IOException -> classifyIoFailure(cause)
            else -> {
                val message = cause.message.orEmpty()
                val className = cause::class.qualifiedName.orEmpty()
                when {
                    "PROXY" in message.uppercase() || "Proxy" in className -> "PROXY_ERROR"
                    "WEBVIEW_REQUIRED" in message -> "WEBVIEW_REQUIRED"
                    "LOGIN_REQUIRED" in message -> "LOGIN_REQUIRED"
                    "timeout" in message.lowercase() || "timed out" in message.lowercase() -> "SOURCE_TIMEOUT"
                    "too many follow-up requests" in message.lowercase() -> "REDIRECT_LOOP"
                    "JS" in message.uppercase() || "Rhino" in className || "javascript" in className.lowercase() -> "JS_ERROR"
                    else -> "SOURCE_ERROR"
                }
            }
        }

    private fun classifyIoFailure(cause: IOException): String {
        val rawMessage = cause.message.orEmpty()
        val message = rawMessage.uppercase()
        val lowerMessage = rawMessage.lowercase()
        val className = cause::class.qualifiedName.orEmpty()
        return when {
            "PROXY" in message || "Proxy" in className -> "PROXY_ERROR"
            "too many follow-up requests" in lowerMessage -> "REDIRECT_LOOP"
            "timeout" in lowerMessage || "timed out" in lowerMessage -> "SOURCE_TIMEOUT"
            else -> "NETWORK_ERROR"
        }
    }

    private fun EngineTraceEvent.toBatchEvent(completed: Int, total: Int): BatchSearchEvent =
        BatchSearchEvent(
            type = "source_trace",
            sourceId = sourceId,
            sourceName = sourceName,
            stage = stage,
            url = url,
            statusCode = statusCode,
            message = message ?: type,
            elapsedMs = elapsedMs,
            completed = completed,
            total = total,
        )
}
