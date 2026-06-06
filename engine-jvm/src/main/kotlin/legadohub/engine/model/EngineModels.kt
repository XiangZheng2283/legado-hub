package legadohub.engine.model

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

@Serializable
data class EngineRequest(
    val stage: EngineStage,
    val source: BookSource,
    val keyword: String? = null,
    val page: Int = 1,
    val url: String? = null,
    val variables: Map<String, String> = emptyMap(),
)

@Serializable
enum class EngineStage {
    Search,
    Detail,
    Toc,
    Content,
    Explore,
}

@Serializable
data class EngineResult<T>(
    val ok: Boolean,
    val data: T? = null,
    val items: List<T> = emptyList(),
    val trace: List<TraceEvent> = emptyList(),
    val unsupported: List<UnsupportedReason> = emptyList(),
    val error: String? = null,
    val latencyMs: Long = 0,
)

@Serializable
data class TraceEvent(
    val stage: EngineStage,
    val type: String,
    val message: String,
    val sourceId: String,
    val url: String? = null,
    val elapsedMs: Long? = null,
    val payload: JsonElement? = null,
)

@Serializable
data class UnsupportedReason(
    val code: UnsupportedCode,
    val message: String,
    val field: String? = null,
)

@Serializable
enum class UnsupportedCode {
    WebViewRequired,
    LoginRequired,
    ComplexJavaScript,
    AndroidRuntimeDependency,
    UnsupportedRuleSyntax,
}
