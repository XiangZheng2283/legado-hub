package legadohub.engine.runtime

data class EngineHttpRequestV2(
    val sourceId: String,
    val url: String,
    val method: String = "GET",
    val headers: Map<String, String> = emptyMap(),
    val body: String? = null,
    val charset: String? = null,
    val proxy: String? = null,
    val timeoutMs: Long? = null,
)

data class EngineHttpResponseV2(
    val statusCode: Int,
    val body: String,
    val headers: Map<String, List<String>> = emptyMap(),
    val finalUrl: String? = null,
    val elapsedMs: Long = 0,
)

class EngineHttpStatusException(
    val statusCode: Int,
    val url: String,
    override val message: String = "HTTP $statusCode: $url",
) : RuntimeException(message)

class EngineSourceExecutionException(
    val errorCode: String,
    val stage: String? = null,
    val url: String? = null,
    override val message: String = errorCode,
    cause: Throwable? = null,
) : RuntimeException(message, cause)

data class EngineTraceEvent(
    val sourceId: String,
    val sourceName: String? = null,
    val stage: String,
    val type: String,
    val url: String? = null,
    val statusCode: Int? = null,
    val message: String? = null,
    val elapsedMs: Long? = null,
)

interface EngineHttpRuntime {
    suspend fun execute(request: EngineHttpRequestV2): EngineHttpResponseV2
}

interface EngineCookieStore {
    suspend fun get(sourceId: String, url: String): String?

    suspend fun put(sourceId: String, url: String, cookie: String)

    suspend fun remove(sourceId: String, url: String)
}

interface EngineCacheV2 {
    suspend fun get(key: String): String?

    suspend fun put(key: String, value: String, ttlSeconds: Long? = null)

    suspend fun remove(key: String)
}

interface EngineSourceVariableStore {
    suspend fun get(sourceId: String): String?

    suspend fun put(sourceId: String, value: String?)
}

interface EngineLoggerV2 {
    fun trace(sourceId: String, stage: String, message: String)

    fun warn(sourceId: String, stage: String, message: String)

    fun error(sourceId: String, stage: String, message: String, cause: Throwable? = null)
}

data class WebViewRequestV2(
    val sourceId: String,
    val url: String,
    val headers: Map<String, String> = emptyMap(),
    val js: String? = null,
    val delayMs: Long = 0,
)

data class WebViewResultV2(
    val ok: Boolean,
    val html: String? = null,
    val errorCode: String? = null,
    val message: String? = null,
)

interface WebViewRuntimeV2 {
    suspend fun render(request: WebViewRequestV2): WebViewResultV2
}

class UnsupportedWebViewRuntimeV2 : WebViewRuntimeV2 {
    override suspend fun render(request: WebViewRequestV2): WebViewResultV2 =
        WebViewResultV2(
            ok = false,
            errorCode = "WEBVIEW_REQUIRED",
            message = "This source requires WebView runtime",
        )
}
