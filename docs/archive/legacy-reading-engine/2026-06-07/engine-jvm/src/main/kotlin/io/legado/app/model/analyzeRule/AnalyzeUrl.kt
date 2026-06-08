package io.legado.app.model.analyzeRule

import io.legado.app.constant.AppConst.UA_NAME
import io.legado.app.data.entities.BaseSource
import kotlinx.serialization.Serializable
import legadohub.engine.runtime.EngineCookieStore
import legadohub.engine.runtime.EngineHttpRuntime
import org.mozilla.javascript.Context
import org.mozilla.javascript.NativeJavaObject
import org.mozilla.javascript.Undefined
import java.net.URI
import java.net.URLEncoder
import java.nio.charset.Charset
import java.util.regex.Pattern
import kotlin.math.max

@Suppress("unused", "MemberVisibilityCanBePrivate")
class AnalyzeUrl(
    private val mUrl: String,
    private val key: String? = null,
    private val page: Int? = null,
    private var baseUrl: String = "",
    private val source: BaseSource? = null,
    headerMapF: Map<String, String>? = null,
    private val variables: Map<String, String> = emptyMap(),
    private val httpRuntime: EngineHttpRuntime? = null,
    private val cookieStore: EngineCookieStore? = null,
) {
    var ruleUrl: String = ""
        private set
    var url: String = ""
        private set
    var type: String? = null
        private set
    val headerMap = LinkedHashMap<String, String>()
    var body: String? = null
        private set
    var urlNoQuery: String = ""
        private set
    var encodedForm: String? = null
        private set
    var encodedQuery: String? = null
        private set
    var charset: String? = null
        private set
    var method: RequestMethod = RequestMethod.GET
        private set
    var proxy: String? = null
        private set
    var retry: Int = 0
        private set
    var useWebView: Boolean = false
        private set
    var webJs: String? = null
        private set
    var bodyJs: String? = null
        private set
    var dnsIp: String? = null
        private set
    var webViewDelayTime: Long = 0
        private set
    var serverID: Long? = null
        private set
    val unsupported: MutableList<AnalyzeUrlUnsupported> = mutableListOf()

    constructor(mUrl: String) : this(mUrl, null)

    init {
        val urlMatcher = paramPattern.matcher(baseUrl)
        if (urlMatcher.find()) baseUrl = baseUrl.substring(0, urlMatcher.start())
        headerMapF?.let {
            headerMap.putAll(it)
            if (it.containsKey("proxy")) {
                proxy = it["proxy"]
                headerMap.remove("proxy")
            }
        }
        if (!headerMap.containsKey(UA_NAME)) {
            headerMap[UA_NAME] = DEFAULT_USER_AGENT
        }
        initUrl()
    }

    fun initUrl() {
        ruleUrl = mUrl
        analyzeJs()
        replaceKeyPageJs()
        analyzeUrl()
    }

    fun toRequestSpec(readTimeoutMs: Long? = null): AnalyzeUrlRequest =
        AnalyzeUrlRequest(
            url = if (method == RequestMethod.GET && encodedQuery != null) {
                val base = urlNoQuery.ifBlank { url.substringBefore("?") }
                "$base?$encodedQuery"
            } else {
                url
            },
            method = method.name,
            headers = headerMap.toMap(),
            body = encodedForm ?: body,
            charset = charset,
            proxy = proxy,
            retry = retry,
            type = type,
            timeoutMs = readTimeoutMs,
            serverID = serverID,
            webViewDelayTime = webViewDelayTime,
            unsupported = unsupported.toList(),
        )

    private fun analyzeJs() {
        var start = 0
        val matcher = URL_JS_PATTERN.matcher(ruleUrl)
        var result = ruleUrl
        while (matcher.find()) {
            if (matcher.start() > start) {
                ruleUrl.substring(start, matcher.start()).trim().takeIf { it.isNotEmpty() }?.let {
                    result = it.replace("@result", result)
                }
            }
            result = jsValueToString(evalUrlJs(matcher.group(2) ?: matcher.group(1), result))
            start = matcher.end()
        }
        if (ruleUrl.length > start) {
            ruleUrl.substring(start).trim().takeIf { it.isNotEmpty() }?.let {
                result = it.replace("@result", result)
            }
        }
        ruleUrl = result
    }

    private fun replaceKeyPageJs() {
        if (ruleUrl.contains("{{") && ruleUrl.contains("}}")) {
            val url = RuleAnalyzer(ruleUrl).innerRule("{{", 2, 2) { expression ->
                jsValueToString(evalUrlJs(expression, result = null))
            }
            if (url.isNotEmpty()) ruleUrl = url
        }
        page?.let { currentPage ->
            val matcher = pagePattern.matcher(ruleUrl)
            while (matcher.find()) {
                val pages = matcher.group(1)!!.split(",")
                ruleUrl = if (currentPage < pages.size) {
                    ruleUrl.replace(matcher.group(), pages[currentPage - 1].trim())
                } else {
                    ruleUrl.replace(matcher.group(), pages.last().trim())
                }
            }
        }
        variables.forEach { (name, value) ->
            ruleUrl = ruleUrl.replace("{{$name}}", value)
        }
    }

    private fun evalUrlJs(jsStr: String, result: Any?): Any? {
        val bindings = buildMap<String, Any?> {
            key?.let {
                put("key", it)
                put("keyword", it)
            }
            page?.let { put("page", it) }
            putAll(variables)
        }
        return AnalyzeRule(
            source = source,
            httpRuntime = httpRuntime,
            cookieStore = cookieStore,
        ).setBaseUrl(baseUrl.ifBlank { source?.getKey() }).evalJS(jsStr, result, bindings)
    }

    private fun jsValueToString(value: Any?): String =
        when (value) {
            null, Undefined.instance -> ""
            is NativeJavaObject -> value.unwrap()?.toString().orEmpty()
            is Double -> if (value % 1.0 == 0.0) "%.0f".format(value) else value.toString()
            else -> Context.toString(value)
        }

    private fun analyzeUrl() {
        val urlMatcher = paramPattern.matcher(ruleUrl)
        val urlNoOption = if (urlMatcher.find()) ruleUrl.substring(0, urlMatcher.start()) else ruleUrl
        url = getAbsoluteUrl(baseUrl.ifBlank { source?.getKey().orEmpty() }, urlNoOption)
        getBaseUrl(url)?.let { baseUrl = it }
        if (urlNoOption.length != ruleUrl.length) {
            val urlOptionStr = ruleUrl.substring(urlMatcher.end())
            val urlOption = UrlOption.fromJson(urlOptionStr)
            urlOption?.let { option ->
                option.getMethod()?.let {
                    method = when (it.uppercase()) {
                        "POST" -> RequestMethod.POST
                        "HEAD" -> RequestMethod.HEAD
                        else -> RequestMethod.GET
                    }
                }
                option.getHeaderMap()?.forEach { entry ->
                    headerMap[entry.key.toString()] = entry.value.toString()
                }
                option.getBody()?.let { body = it }
                type = option.getType()
                charset = option.getCharset()
                retry = option.getRetry()
                useWebView = option.useWebView()
                webJs = option.getWebJs()
                bodyJs = option.getBodyJs()
                dnsIp = option.getDnsIp()
                option.getProxy()?.let { proxy = it }
                option.getJs()?.let { jsStr ->
                    jsValueToString(evalUrlJs(jsStr, url)).takeIf { it.isNotBlank() }?.let { rewrittenUrl ->
                        url = rewrittenUrl
                    }
                }
                if (useWebView) {
                    unsupported += AnalyzeUrlUnsupported(
                        code = "WEBVIEW_REQUIRED",
                        message = "URL option webView requires WebView runtime",
                        field = "webView",
                    )
                }
                if (webJs != null) {
                    unsupported += AnalyzeUrlUnsupported(
                        code = "WEBVIEW_JS_REQUIRED",
                        message = "URL option webJs requires WebView runtime",
                        field = "webJs",
                    )
                }
                if (bodyJs != null) {
                    unsupported += AnalyzeUrlUnsupported(
                        code = "BODY_JS_REQUIRED",
                        message = "URL option bodyJs requires JS runtime",
                        field = "bodyJs",
                    )
                }
                if (dnsIp != null) {
                    unsupported += AnalyzeUrlUnsupported(
                        code = "CUSTOM_DNS_REQUIRED",
                        message = "URL option dnsIp requires custom DNS runtime",
                        field = "dnsIp",
                    )
                }
                serverID = option.getServerID()
                webViewDelayTime = max(0, option.getWebViewDelayTime() ?: 0)
            }
        }
        urlNoQuery = url
        when (method) {
            RequestMethod.POST -> body?.let {
                if (!it.looksJson() && !it.looksXml() && headerMap["Content-Type"].isNullOrEmpty()) {
                    analyzeFields(it)
                }
            }

            else -> {
                val pos = url.indexOf('?')
                if (pos != -1) {
                    analyzeQuery(url.substring(pos + 1))
                    urlNoQuery = url.substring(0, pos)
                }
            }
        }
    }

    private fun analyzeFields(fieldsTxt: String) {
        encodedForm = encodeParams(fieldsTxt, charset, false)
    }

    private fun analyzeQuery(query: String) {
        encodedQuery = encodeParams(query, charset, true)
    }

    private fun encodeParams(params: String, charset: String?, isQuery: Boolean): String {
        val effectiveCharset = when {
            charset.isNullOrEmpty() -> Charsets.UTF_8
            charset == "escape" -> null
            else -> Charset.forName(charset)
        }
        if (isQuery && effectiveCharset != null && encodedQueryLooksEncoded(params)) {
            return params
        }
        return params.split("&").joinToString("&") { pair ->
            val key = pair.substringBefore("=")
            val value = pair.substringAfter("=", missingDelimiterValue = "")
            if ("=" in pair) {
                "${appendEncoded(key, effectiveCharset)}=${appendEncoded(value, effectiveCharset)}"
            } else {
                appendEncoded(key, effectiveCharset)
            }
        }
    }

    private fun appendEncoded(value: String, charset: Charset?): String =
        if (charset == null) {
            value.flatMap { char ->
                when (char) {
                    in 'A'..'Z', in 'a'..'z', in '0'..'9' -> listOf(char)
                    else -> "\\u%04x".format(char.code).toList()
                }
            }.joinToString("")
        } else {
            URLEncoder.encode(value, charset).replace("+", "%20")
        }

    @Serializable
    data class UrlOption(
        private var method: String? = null,
        private var charset: String? = null,
        private var headers: Map<String, String>? = null,
        private var body: String? = null,
        private var origin: String? = null,
        private var retry: Int? = null,
        private var type: String? = null,
        private var webView: kotlinx.serialization.json.JsonElement? = null,
        private var webJs: String? = null,
        private var dnsIp: String? = null,
        private var js: String? = null,
        private var bodyJs: String? = null,
        private var serverID: Long? = null,
        private var webViewDelayTime: Long? = null,
        private var proxy: String? = null,
    ) {
        fun setMethod(value: String?) {
            method = if (value.isNullOrBlank()) null else value
        }

        fun getMethod(): String? = method

        fun setCharset(value: String?) {
            charset = if (value.isNullOrBlank()) null else value
        }

        fun getCharset(): String? = charset

        fun setOrigin(value: String?) {
            origin = if (value.isNullOrBlank()) null else value
        }

        fun getOrigin(): String? = origin

        fun setRetry(value: String?) {
            retry = if (value.isNullOrEmpty()) null else value.toIntOrNull()
        }

        fun getRetry(): Int = retry ?: 0

        fun setType(value: String?) {
            type = if (value.isNullOrBlank()) null else value
        }

        fun getType(): String? = type

        fun useWebView(): Boolean =
            when (val value = webView?.toString()?.trim('"')) {
                null, "", "false" -> false
                else -> value != "null"
            }

        fun useWebView(boolean: Boolean) {
            webView = if (boolean) TRUE_JSON else null
        }

        fun setHeaders(value: String?) {
            headers = if (value.isNullOrBlank()) null else JSON.decodeFromString(value)
        }

        fun getHeaderMap(): Map<*, *>? = headers

        fun setBody(value: String?) {
            body = if (value.isNullOrBlank()) null else value
        }

        fun getBody(): String? = body

        fun setWebJs(value: String?) {
            webJs = if (value.isNullOrBlank()) null else value
        }

        fun getWebJs(): String? = webJs

        fun setDnsIp(value: String?) {
            dnsIp = if (value.isNullOrBlank()) null else value
        }

        fun getDnsIp(): String? = dnsIp

        fun setJs(value: String?) {
            js = if (value.isNullOrBlank()) null else value
        }

        fun getJs(): String? = js

        fun setBodyJs(value: String?) {
            bodyJs = if (value.isNullOrBlank()) null else value
        }

        fun getBodyJs(): String? = bodyJs

        fun setServerID(value: String?) {
            serverID = if (value.isNullOrBlank()) null else value.toLong()
        }

        fun getServerID(): Long? = serverID

        fun setWebViewDelayTime(value: String?) {
            webViewDelayTime = if (value.isNullOrBlank()) null else value.toLong()
        }

        fun getWebViewDelayTime(): Long? = webViewDelayTime

        fun getProxy(): String? = proxy

        companion object {
            fun fromJson(text: String): UrlOption? =
                runCatching { JSON.decodeFromString<UrlOption>(text) }.getOrNull()
        }
    }

    companion object {
        val paramPattern: Pattern = Pattern.compile("\\s*,\\s*(?=\\{)")
        private val pagePattern = Pattern.compile("<(.*?)>")
        private val URL_JS_PATTERN: Pattern = Pattern.compile("<js>([\\w\\W]*?)</js>|@js:([\\w\\W]*)", Pattern.CASE_INSENSITIVE)
        private val JSON = kotlinx.serialization.json.Json {
            ignoreUnknownKeys = true
            explicitNulls = false
            isLenient = true
        }
        private val TRUE_JSON = kotlinx.serialization.json.JsonPrimitive(true)
        private const val DEFAULT_USER_AGENT =
            "Mozilla/5.0 (Linux; Android 12; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"
    }
}

enum class RequestMethod {
    GET,
    POST,
    HEAD,
}

@Serializable
data class AnalyzeUrlRequest(
    val url: String,
    val method: String,
    val headers: Map<String, String>,
    val body: String? = null,
    val charset: String? = null,
    val proxy: String? = null,
    val retry: Int = 0,
    val type: String? = null,
    val timeoutMs: Long? = null,
    val serverID: Long? = null,
    val webViewDelayTime: Long = 0,
    val unsupported: List<AnalyzeUrlUnsupported> = emptyList(),
)

@Serializable
data class AnalyzeUrlUnsupported(
    val code: String,
    val message: String,
    val field: String? = null,
)

private fun getAbsoluteUrl(baseUrl: String, url: String): String {
    if (url.startsWith("http://", true) || url.startsWith("https://", true)) return url
    if (baseUrl.isBlank()) return url
    return runCatching { URI(baseUrl).resolve(url).toString() }.getOrDefault(url)
}

private fun getBaseUrl(url: String): String? =
    runCatching {
        val uri = URI(url)
        "${uri.scheme}://${uri.host}"
    }.getOrNull()

private fun encodeUrl(value: String): String =
    URLEncoder.encode(value, Charsets.UTF_8).replace("+", "%20")

private fun String.looksJson(): Boolean =
    trim().let { it.startsWith("{") || it.startsWith("[") }

private fun String.looksXml(): Boolean =
    trim().startsWith("<")

private fun encodedQueryLooksEncoded(value: String): Boolean =
    Regex("%[0-9A-Fa-f]{2}").containsMatchIn(value)
