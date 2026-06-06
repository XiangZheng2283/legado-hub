package legadohub.engine.url

import legadohub.engine.model.UnsupportedCode
import legadohub.engine.model.UnsupportedReason
import legadohub.engine.source.BookSourceParser
import legadohub.engine.source.SourceHeaderParser
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.Charset

class AnalyzeUrlParser(
    private val headerParser: SourceHeaderParser = SourceHeaderParser(),
    private val json: Json = BookSourceParser.defaultJson,
) {
    fun parse(input: AnalyzeUrlInput): AnalyzedUrl {
        val unsupported = mutableListOf<UnsupportedReason>()
        val headerResult = input.source?.let {
            headerParser.parse(it, input.hasLoginHeader)
        }
        unsupported += headerResult?.unsupported.orEmpty()

        val headers = linkedMapOf<String, String>()
        headerResult?.headers?.let(headers::putAll)
        var proxy = headerResult?.proxy
        var ruleUrl = input.ruleUrl.trim()

        if (ruleUrl.contains("@js:", ignoreCase = true) || ruleUrl.contains("<js>", ignoreCase = true)) {
            unsupported += UnsupportedReason(
                code = UnsupportedCode.ComplexJavaScript,
                message = "URL 规则包含 @js 或 <js>，当前阶段仅结构化标记",
                field = "searchUrl",
            )
        }

        ruleUrl = replaceSimpleInlineVariables(ruleUrl, input, unsupported)
        ruleUrl = replacePageAlternatives(ruleUrl, input.page)

        val (urlWithoutOption, optionText) = splitUrlOption(ruleUrl)
        var method = AnalyzeHttpMethod.GET
        var body: String? = null
        var charset: String? = null
        var type: String? = null
        var retry = 0
        var useWebView = false
        var webJs: String? = null
        var bodyJs: String? = null
        var dnsIp: String? = null
        var serverID: Long? = null
        var webViewDelayTime = 0L
        var url = absolutize(input.baseUrl, urlWithoutOption)

        if (!optionText.isNullOrBlank()) {
            val option = parseOption(optionText, unsupported)
            if (option != null) {
                method = option.method ?: method
                headers.putAll(option.headers)
                body = option.body
                charset = option.charset
                type = option.type
                retry = option.retry
                useWebView = option.useWebView
                webJs = option.webJs
                bodyJs = option.bodyJs
                dnsIp = option.dnsIp
                serverID = option.serverID
                webViewDelayTime = option.webViewDelayTime
                option.proxy?.let { proxy = it }
                if (option.js != null) {
                    unsupported += UnsupportedReason(
                        code = UnsupportedCode.ComplexJavaScript,
                        message = "URL option.js 需要 JavaScript 改写 URL",
                        field = "urlOption.js",
                    )
                }
            }
        }

        if (useWebView) {
            unsupported += UnsupportedReason(
                code = UnsupportedCode.WebViewRequired,
                message = "URL option.webView 要求 WebView 运行时",
                field = "urlOption.webView",
            )
        }
        if (bodyJs != null) {
            unsupported += UnsupportedReason(
                code = UnsupportedCode.ComplexJavaScript,
                message = "URL option.bodyJs 需要 JavaScript 处理响应正文",
                field = "urlOption.bodyJs",
            )
        }

        var urlNoQuery = url
        var encodedQuery: String? = null
        var encodedForm: String? = null
        if (method == AnalyzeHttpMethod.POST) {
            if (body != null && shouldEncodeForm(body, headers)) {
                encodedForm = encodeParams(body, charset)
            }
        } else {
            val queryStart = url.indexOf('?')
            if (queryStart >= 0) {
                urlNoQuery = url.substring(0, queryStart)
                encodedQuery = encodeParams(url.substring(queryStart + 1), charset)
                url = "$urlNoQuery?$encodedQuery"
            }
        }

        return AnalyzedUrl(
            originalRuleUrl = input.ruleUrl,
            ruleUrl = ruleUrl,
            url = url,
            urlNoQuery = urlNoQuery,
            method = method,
            headers = headers,
            body = body,
            encodedForm = encodedForm,
            encodedQuery = encodedQuery,
            charset = charset,
            type = type,
            proxy = proxy,
            retry = retry,
            useWebView = useWebView,
            webJs = webJs,
            bodyJs = bodyJs,
            dnsIp = dnsIp,
            serverID = serverID,
            webViewDelayTime = webViewDelayTime,
            unsupported = unsupported,
        )
    }

    private fun replaceSimpleInlineVariables(
        ruleUrl: String,
        input: AnalyzeUrlInput,
        unsupported: MutableList<UnsupportedReason>,
    ): String =
        INLINE_VARIABLE_PATTERN.replace(ruleUrl) { match ->
            val expression = match.groupValues[1].trim()
            val value = when (expression) {
                "key" -> input.key
                "page" -> input.page?.toString()
                "title" -> input.title
                "author" -> input.author
                else -> input.variables[expression]
            }
            if (value != null) {
                value
            } else {
                unsupported += UnsupportedReason(
                    code = UnsupportedCode.ComplexJavaScript,
                    message = "内嵌表达式 {{$expression}} 需要 JavaScript 求值",
                    field = "inlineVariable",
                )
                ""
            }
        }

    private fun replacePageAlternatives(ruleUrl: String, page: Int?): String {
        if (page == null || ruleUrl.contains("<js>", ignoreCase = true)) return ruleUrl
        return PAGE_PATTERN.replace(ruleUrl) { match ->
            val pages = match.groupValues[1].split(",").map { it.trim() }.filter { it.isNotEmpty() }
            if (pages.isEmpty()) {
                match.value
            } else {
                pages.getOrElse(page - 1) { pages.last() }
            }
        }
    }

    private fun splitUrlOption(ruleUrl: String): Pair<String, String?> {
        val match = URL_OPTION_PATTERN.find(ruleUrl) ?: return ruleUrl to null
        return ruleUrl.substring(0, match.range.first) to ruleUrl.substring(match.range.last + 1)
    }

    private fun parseOption(
        optionText: String,
        unsupported: MutableList<UnsupportedReason>,
    ): UrlOption? =
        runCatching {
            val optionJson = json.parseToJsonElement(optionText).jsonObject
            UrlOption.from(optionJson)
        }.getOrElse { error ->
            unsupported += UnsupportedReason(
                code = UnsupportedCode.UnsupportedRuleSyntax,
                message = "URL option 不是合法 JSON 对象：${error.message}",
                field = "urlOption",
            )
            null
        }

    private fun absolutize(baseUrl: String, url: String): String =
        runCatching {
            when {
                url.startsWith("http://", ignoreCase = true) ||
                    url.startsWith("https://", ignoreCase = true) -> url
                baseUrl.isBlank() -> url
                else -> URI(baseUrl).resolve(url).toString()
            }
        }.getOrDefault(url)

    private fun shouldEncodeForm(body: String, headers: Map<String, String>): Boolean {
        if (body.trimStart().startsWith("{") || body.trimStart().startsWith("[")) return false
        if (body.trimStart().startsWith("<")) return false
        return headers.none { it.key.equals("Content-Type", ignoreCase = true) }
    }

    private fun encodeParams(params: String, charsetName: String?): String {
        val charset = charsetName
            ?.takeUnless { it.equals("escape", ignoreCase = true) }
            ?.let { Charset.forName(it) }
            ?: Charsets.UTF_8
        return params.split("&").joinToString("&") { pair ->
            val index = pair.indexOf("=")
            if (index < 0) {
                encodeComponent(pair, charset)
            } else {
                val key = pair.substring(0, index)
                val value = pair.substring(index + 1)
                "${encodeComponent(key, charset)}=${encodeComponent(value, charset)}"
            }
        }
    }

    private fun encodeComponent(value: String, charset: Charset): String =
        URLEncoder.encode(value, charset)

    private data class UrlOption(
        val method: AnalyzeHttpMethod? = null,
        val charset: String? = null,
        val headers: Map<String, String> = emptyMap(),
        val body: String? = null,
        val retry: Int = 0,
        val type: String? = null,
        val useWebView: Boolean = false,
        val webJs: String? = null,
        val dnsIp: String? = null,
        val js: String? = null,
        val bodyJs: String? = null,
        val serverID: Long? = null,
        val webViewDelayTime: Long = 0,
        val proxy: String? = null,
    ) {
        companion object {
            fun from(json: JsonObject): UrlOption =
                UrlOption(
                    method = json.string("method")?.uppercase()?.let {
                        when (it) {
                            "POST" -> AnalyzeHttpMethod.POST
                            "HEAD" -> AnalyzeHttpMethod.HEAD
                            else -> AnalyzeHttpMethod.GET
                        }
                    },
                    charset = json.string("charset"),
                    headers = json.headers(),
                    body = json.body(),
                    retry = json.int("retry") ?: 0,
                    type = json.string("type"),
                    useWebView = json.booleanLike("webView"),
                    webJs = json.string("webJs"),
                    dnsIp = json.string("dnsIp"),
                    js = json.string("js"),
                    bodyJs = json.string("bodyJs"),
                    serverID = json.long("serverID"),
                    webViewDelayTime = json.long("webViewDelayTime") ?: 0,
                    proxy = json.string("proxy"),
                )

            private fun JsonObject.string(key: String): String? =
                (this[key] as? JsonPrimitive)?.contentOrNull?.takeIf { it.isNotBlank() }

            private fun JsonObject.int(key: String): Int? =
                (this[key] as? JsonPrimitive)?.intOrNull

            private fun JsonObject.long(key: String): Long? =
                (this[key] as? JsonPrimitive)?.longOrNull

            private fun JsonObject.booleanLike(key: String): Boolean =
                when (val value = this[key]) {
                    null -> false
                    is JsonPrimitive -> value.booleanOrNull ?: value.contentOrNull
                        ?.let { it.isNotBlank() && !it.equals("false", ignoreCase = true) }
                        ?: false
                    else -> true
                }

            private fun JsonObject.headers(): Map<String, String> {
                val value = this["headers"] ?: return emptyMap()
                return when (value) {
                    is JsonObject -> value.mapValues { (_, v) -> v.toPlainString() }
                    is JsonPrimitive -> runCatching {
                        BookSourceParser.defaultJson.decodeFromString<Map<String, String>>(
                            value.contentOrNull.orEmpty(),
                        )
                    }.getOrDefault(emptyMap())
                    else -> emptyMap()
                }
            }

            private fun JsonObject.body(): String? {
                val value = this["body"] ?: return null
                return when (value) {
                    is JsonPrimitive -> value.contentOrNull
                    else -> value.toString()
                }
            }

            private fun JsonElement.toPlainString(): String =
                (this as? JsonPrimitive)?.contentOrNull ?: toString()
        }
    }

    companion object {
        private val INLINE_VARIABLE_PATTERN = Regex("\\{\\{(.*?)}}")
        private val PAGE_PATTERN = Regex("<([^<>]+)>")
        private val URL_OPTION_PATTERN = Regex("\\s*,\\s*(?=\\{)")
    }
}
