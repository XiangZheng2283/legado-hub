package legadohub.engine.url

import legadohub.engine.model.BookSource
import legadohub.engine.model.UnsupportedReason

data class AnalyzeUrlInput(
    val ruleUrl: String,
    val key: String? = null,
    val page: Int? = null,
    val title: String? = null,
    val author: String? = null,
    val baseUrl: String = "",
    val source: BookSource? = null,
    val variables: Map<String, String> = emptyMap(),
    val hasLoginHeader: Boolean = true,
)

data class AnalyzedUrl(
    val originalRuleUrl: String,
    val ruleUrl: String,
    val url: String,
    val urlNoQuery: String,
    val method: AnalyzeHttpMethod,
    val headers: Map<String, String>,
    val body: String? = null,
    val encodedForm: String? = null,
    val encodedQuery: String? = null,
    val charset: String? = null,
    val type: String? = null,
    val proxy: String? = null,
    val retry: Int = 0,
    val useWebView: Boolean = false,
    val webJs: String? = null,
    val bodyJs: String? = null,
    val dnsIp: String? = null,
    val serverID: Long? = null,
    val webViewDelayTime: Long = 0,
    val unsupported: List<UnsupportedReason> = emptyList(),
)

enum class AnalyzeHttpMethod {
    GET,
    POST,
    HEAD,
}
