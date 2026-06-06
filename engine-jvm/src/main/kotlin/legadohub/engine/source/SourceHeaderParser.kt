package legadohub.engine.source

import legadohub.engine.model.BookSource
import legadohub.engine.model.UnsupportedCode
import legadohub.engine.model.UnsupportedReason
import kotlinx.serialization.json.Json

data class SourceHeaderParseResult(
    val headers: Map<String, String>,
    val proxy: String? = null,
    val unsupported: List<UnsupportedReason> = emptyList(),
)

class SourceHeaderParser(
    private val json: Json = BookSourceParser.defaultJson,
    private val defaultUserAgent: String = DEFAULT_USER_AGENT,
) {
    fun parse(source: BookSource, hasLoginHeader: Boolean = false): SourceHeaderParseResult {
        val unsupported = mutableListOf<UnsupportedReason>()
        val headers = linkedMapOf<String, String>()
        val rawHeader = source.header?.trim()

        if (!rawHeader.isNullOrBlank()) {
            when {
                rawHeader.startsWith("@js:", ignoreCase = true) ||
                    rawHeader.startsWith("<js>", ignoreCase = true) -> {
                    unsupported += UnsupportedReason(
                        code = UnsupportedCode.ComplexJavaScript,
                        message = "请求头依赖 JavaScript 执行，当前阶段仅结构化标记",
                        field = "header",
                    )
                }

                else -> headers.putAll(parseHeaderObject(rawHeader, unsupported))
            }
        }

        if (hasLoginHeader && !source.loginUrl.isNullOrBlank()) {
            unsupported += UnsupportedReason(
                code = UnsupportedCode.LoginRequired,
                message = "书源配置了登录入口，后端登录运行时尚未接入",
                field = "loginUrl",
            )
        }

        if (!headers.hasKeyIgnoreCase(USER_AGENT_HEADER)) {
            headers[USER_AGENT_HEADER] = defaultUserAgent
        }

        val proxy = headers.removeKeyIgnoreCase(PROXY_HEADER)
        return SourceHeaderParseResult(
            headers = headers,
            proxy = proxy,
            unsupported = unsupported,
        )
    }

    private fun parseHeaderObject(
        rawHeader: String,
        unsupported: MutableList<UnsupportedReason>,
    ): Map<String, String> {
        val parsed = runCatching {
            json.decodeFromString<Map<String, String>>(rawHeader)
        }
        return parsed.getOrElse { error ->
            unsupported += UnsupportedReason(
                code = UnsupportedCode.UnsupportedRuleSyntax,
                message = "请求头不是合法 JSON 对象：${error.message}",
                field = "header",
            )
            emptyMap()
        }
    }

    private fun MutableMap<String, String>.hasKeyIgnoreCase(key: String): Boolean =
        keys.any { it.equals(key, ignoreCase = true) }

    private fun MutableMap<String, String>.removeKeyIgnoreCase(key: String): String? {
        val actualKey = keys.firstOrNull { it.equals(key, ignoreCase = true) } ?: return null
        return remove(actualKey)
    }

    companion object {
        const val USER_AGENT_HEADER = "User-Agent"
        const val PROXY_HEADER = "proxy"
        const val DEFAULT_USER_AGENT =
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LegadoHub/0.1"
    }
}
