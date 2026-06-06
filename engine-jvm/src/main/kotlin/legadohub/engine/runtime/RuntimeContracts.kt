package legadohub.engine.runtime

import legadohub.engine.model.EngineStage
import legadohub.engine.model.TraceEvent
import legadohub.engine.model.UnsupportedReason

data class EngineHttpRequest(
    val url: String,
    val method: String,
    val headers: Map<String, String> = emptyMap(),
    val body: String? = null,
    val proxy: String? = null,
    val charset: String? = null,
    val timeoutMs: Long? = null,
)

data class EngineHttpResponse(
    val statusCode: Int,
    val headers: Map<String, List<String>> = emptyMap(),
    val body: String,
    val finalUrl: String? = null,
    val elapsedMs: Long = 0,
)

interface HttpRuntime {
    suspend fun execute(request: EngineHttpRequest): EngineHttpResponse
}

interface CookieStore {
    suspend fun getCookie(sourceId: String, domain: String): String?

    suspend fun putCookie(sourceId: String, domain: String, cookie: String)

    suspend fun removeCookie(sourceId: String, domain: String)
}

interface SourceVariableStore {
    suspend fun get(sourceId: String, key: String): String?

    suspend fun put(sourceId: String, key: String, value: String)
}

interface EngineCache {
    suspend fun get(key: String): String?

    suspend fun put(key: String, value: String, ttlSeconds: Long? = null)

    suspend fun delete(key: String)
}

data class WebViewRequest(
    val url: String,
    val headers: Map<String, String> = emptyMap(),
    val js: String? = null,
    val delayMs: Long = 0,
)

data class WebViewResult(
    val html: String? = null,
    val unsupported: UnsupportedReason? = null,
)

interface WebViewRuntime {
    suspend fun render(request: WebViewRequest): WebViewResult
}

class UnsupportedWebViewRuntime(
    private val reason: UnsupportedReason,
) : WebViewRuntime {
    override suspend fun render(request: WebViewRequest): WebViewResult =
        WebViewResult(unsupported = reason)
}

interface EngineLogger {
    fun trace(event: TraceEvent)

    fun unsupported(stage: EngineStage, sourceId: String, reason: UnsupportedReason)

    fun error(stage: EngineStage, sourceId: String, message: String, cause: Throwable? = null)
}
