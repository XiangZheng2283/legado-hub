package io.legado.app.model.analyzeRule

import io.legado.app.data.entities.BaseSource
import io.legado.app.data.entities.Book
import io.legado.app.data.entities.BookChapter
import io.legado.app.help.ConcurrentRateLimiter
import io.legado.app.help.JsElementList
import io.legado.app.help.JsExtensions
import io.legado.app.help.JsHttpResponse
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import legadohub.engine.runtime.EngineHttpRequestV2
import legadohub.engine.runtime.EngineHttpResponseV2
import legadohub.engine.runtime.EngineHttpRuntime
import legadohub.engine.runtime.EngineCookieStore
import org.jsoup.nodes.Element
import org.jsoup.select.Elements
import org.mozilla.javascript.Context
import org.mozilla.javascript.NativeArray
import org.mozilla.javascript.NativeJavaObject
import org.mozilla.javascript.NativeObject
import org.mozilla.javascript.UniqueTag
import org.mozilla.javascript.Undefined
import java.net.URI

/**
 * JVM port slice of Reading's AnalyzeRule.
 *
 * The public entrypoint shape is kept close to upstream while selector work is
 * delegated to RuleAnalyzer and AnalyzeBy* helpers.
 */
@Suppress("unused", "MemberVisibilityCanBePrivate")
class AnalyzeRule(
    private var ruleData: RuleDataInterface? = null,
    private val source: BaseSource? = null,
    private val preUpdateJs: Boolean = false,
    private var isFromBookInfo: Boolean = false,
    private val httpRuntime: EngineHttpRuntime? = null,
    private val cookieStore: EngineCookieStore? = null,
) : JsExtensions {
    private var content: Any? = null
    private var baseUrl: String? = null
    private val localRuleData = RuleData()
    val unsupported: MutableList<AnalyzeRuleUnsupported> = mutableListOf()

    @JvmOverloads
    fun setContent(content: Any?, baseUrl: String? = null): AnalyzeRule {
        if (content == null) throw AssertionError("内容不可空（Content cannot be null）")
        this.content = content
        this.baseUrl = baseUrl
        return this
    }

    fun setBaseUrl(baseUrl: String?): AnalyzeRule {
        if (!baseUrl.isNullOrBlank()) this.baseUrl = baseUrl
        return this
    }

    @JvmOverloads
    fun getString(rule: String?, mContent: Any? = null, isUrl: Boolean = false): String? {
        val list = getStringList(rule, mContent, isUrl)
        return when {
            list.isNullOrEmpty() -> null
            list.size == 1 -> list.first()
            else -> list.joinToString("\n")
        }
    }

    @JvmOverloads
    fun getStringList(rule: String?, mContent: Any? = null, isUrl: Boolean = false): List<String>? {
        if (rule.isNullOrBlank()) return null
        val currentContent = mContent ?: content ?: return null
        val result = applyFallback(rule).flatMap { branch ->
            applyReplace(branch) { cleanRule ->
                evaluateRule(cleanRule, currentContent, isUrl)
            }
        }.filter { it.isNotBlank() }
        return result.ifEmpty { null }
    }

    fun splitSourceRule(rule: String?): List<String> =
        rule?.let { RuleAnalyzer(it).splitRule("&&") }.orEmpty()

    fun getElements(rule: String?): List<Any> {
        if (rule.isNullOrBlank()) return emptyList()
        val currentContent = content ?: return emptyList()
        val cleanRule = rule.trim()
        val jsPipeline = splitJsPipeline(cleanRule)
        if (jsPipeline.size == 1 && cleanRule.isJsRule()) {
            return jsValueToObjects(evalJS(cleanRule.extractJs(), currentContent))
        }
        if (jsPipeline.size > 1) {
            var currentValues: List<Any> = listOf(currentContent)
            jsPipeline.forEach { step ->
                currentValues = currentValues.flatMap { current ->
                    if (step.isJsRule()) {
                        jsValueToObjects(evalJS(step.extractJs(), current))
                    } else {
                        evaluateElementsOnly(step, current)
                    }
                }
            }
            return currentValues
        }
        return evaluateElementsOnly(cleanRule, currentContent)
    }

    private fun evaluateElementsOnly(rule: String, currentContent: Any): List<Any> {
        return when {
            rule.startsWith("xpath:", true) || rule.startsWith("xpath://", true) -> {
                AnalyzeByXPath(currentContent).getElements(rule.removePrefixIgnoreCase("xpath:"))
            }

            rule.startsWith("$") ->
                evaluateJsonPathElements(rule, currentContent)

            else ->
                AnalyzeByJSoup(currentContent).getElements(rule).toList()
        }
    }

    private fun evaluateJsonPathElements(rule: String, currentContent: Any): List<Any> {
        val analyzer = RuleAnalyzer(rule, code = true)
        val rules = analyzer.splitRule("&&", "||", "%%")
        val results = rules.mapNotNull { singleRule ->
            AnalyzeByJSonPath(currentContent).getList(singleRule)?.takeIf { it.isNotEmpty() }
        }.let { if (analyzer.elementsType == "||") it.take(1) else it }
        return if (analyzer.elementsType == "%%") {
            val merged = mutableListOf<Any>()
            val max = results.maxOfOrNull { it.size } ?: 0
            for (index in 0 until max) {
                results.forEach { if (index < it.size) merged += it[index] }
            }
            merged
        } else {
            results.flatten()
        }
    }

    fun getElement(rule: String): Any? {
        val elements = getElements(rule)
        if (elements.isEmpty()) return JsElementList(Elements())
        if (elements.all { it is Element }) {
            return JsElementList(Elements(elements.filterIsInstance<Element>()))
        }
        return if (elements.size == 1) elements.first() else elements
    }

    fun evalJS(jsStr: String, result: Any? = null, extraBindings: Map<String, Any?> = emptyMap()): Any? {
        val cx = Context.enter()
        return try {
            val scope = cx.initStandardObjects()
            scope.put("java", scope, this)
            scope.put("source", scope, source)
            scope.put("result", scope, result.toJsBinding())
            scope.put("baseUrl", scope, baseUrl)
            scope.put("src", scope, content)
            scope.put("cookie", scope, JsCookieBridge())
            (ruleData as? Book)?.let { scope.put("book", scope, it) }
            (ruleData as? BookChapter)?.let { scope.put("chapter", scope, it) }
            extraBindings.forEach { (name, value) ->
                scope.put(name, scope, value)
            }
            cx.evaluateString(scope, jsStr, "AnalyzeRule", 1, null)
        } finally {
            Context.exit()
        }
    }

    override fun getSource(): BaseSource? = source

    override fun getTag(): String? = source?.getTag()

    fun put(key: String, value: Any?): String {
        val text = value?.toString().orEmpty()
        variableTarget().putVariable(key, text)
        return text
    }

    fun get(key: String): String =
        when (key) {
            "bookName" -> (ruleData as? Book)?.name.orEmpty()
            "title" -> (ruleData as? BookChapter)?.title.orEmpty()
            else -> variableTarget().getVariable(key)
        }

    fun getCookie(tag: String): String =
        runBlocking { cookieStore?.get(sourceId(), absolutize(tag)).orEmpty() }

    fun getCookie(tag: String, key: String?): String {
        val cookie = getCookie(tag)
        if (key.isNullOrBlank()) return cookie
        return cookie.split(";")
            .map { it.trim() }
            .firstOrNull { it.substringBefore("=").trim() == key }
            ?.substringAfter("=", missingDelimiterValue = "")
            ?.trim()
            .orEmpty()
    }

    fun getVerificationCode(imageUrl: String): String =
        "UNSUPPORTED:getVerificationCode:$imageUrl"

    fun startBrowserAwait(url: String, title: String): JsHttpResponse =
        startBrowserAwait(url, title, refetchAfterSuccess = false, html = null)

    fun startBrowserAwait(url: String, title: String, refetchAfterSuccess: Boolean): JsHttpResponse =
        startBrowserAwait(url, title, refetchAfterSuccess, html = null)

    fun startBrowserAwait(
        url: String,
        title: String,
        refetchAfterSuccess: Boolean,
        html: String?,
    ): JsHttpResponse =
        JsHttpResponse(
            EngineHttpResponseV2(
                statusCode = 0,
                body = "UNSUPPORTED:startBrowserAwait:$url",
                finalUrl = absolutize(url),
            ),
        )

    @JvmOverloads
    fun get(urlStr: String, headers: Any?, timeout: Int? = null): JsHttpResponse =
        executeJsHttp("GET", urlStr, headers, body = null, timeoutMs = timeout?.toLong())

    @JvmOverloads
    fun head(urlStr: String, headers: Any?, timeout: Int? = null): JsHttpResponse =
        executeJsHttp("HEAD", urlStr, headers, body = null, timeoutMs = timeout?.toLong())

    @JvmOverloads
    fun post(urlStr: String, body: String, headers: Any?, timeout: Int? = null): JsHttpResponse =
        executeJsHttp("POST", urlStr, headers, body = body, timeoutMs = timeout?.toLong())

    fun connect(urlStr: String): JsHttpResponse =
        connect(urlStr, null, null)

    fun connect(urlStr: String, header: String?): JsHttpResponse =
        connect(urlStr, header, null)

    fun connect(urlStr: String, header: String?, callTimeout: Long?): JsHttpResponse =
        executeJsHttp("GET", urlStr, header, body = null, timeoutMs = callTimeout)

    override fun ajax(url: Any): String {
        return ajax(url, null)
    }

    fun ajax(url: Any, callTimeout: Long?): String {
        val request = buildAjaxRequest(url).let {
            if (callTimeout == null) it else it.copy(timeoutMs = callTimeout)
        }
        return executeAjaxRequest(request).body
    }

    fun ajaxAll(urlList: Any): Array<JsHttpResponse> =
        ajaxAll(urlList, false)

    @Suppress("UNUSED_PARAMETER")
    fun ajaxAll(urlList: Any, skipRateLimit: Boolean): Array<JsHttpResponse> {
        val requests = urlList.toAjaxRequests()
        return executeAjaxRequests(requests, skipRateLimit)
    }

    fun ajaxTestAll(urlList: Any, timeout: Int): Array<JsHttpResponse> =
        ajaxTestAll(urlList, timeout, false)

    @Suppress("UNUSED_PARAMETER")
    fun ajaxTestAll(urlList: Any, timeout: Int, skipRateLimit: Boolean): Array<JsHttpResponse> {
        val requests = urlList.toAjaxRequests().map { request ->
            request.copy(timeoutMs = timeout.toLong())
        }
        return executeAjaxRequests(requests, skipRateLimit)
    }

    private fun executeAjaxRequests(
        requests: List<EngineHttpRequestV2>,
        skipRateLimit: Boolean,
    ): Array<JsHttpResponse> {
        val runtime = httpRuntime
        return runBlocking {
            requests
                .map { request ->
                    async {
                        if (runtime == null) {
                            JsHttpResponse(
                                EngineHttpResponseV2(
                                    statusCode = 0,
                                    body = "UNSUPPORTED:java.ajax:${request.url}",
                                    finalUrl = request.url,
                                ),
                            )
                        } else {
                            JsHttpResponse(executeAjaxRequestAwait(runtime, request, skipRateLimit))
                        }
                    }
                }
                .awaitAll()
                .toTypedArray()
        }
    }

    private fun executeAjaxRequest(request: EngineHttpRequestV2): EngineHttpResponseV2 {
        val runtime = httpRuntime ?: return "UNSUPPORTED:java.ajax:${request.url}"
            .let { EngineHttpResponseV2(statusCode = 0, body = it, finalUrl = request.url) }
        return runBlocking {
            executeAjaxRequestAwait(runtime, request, skipRateLimit = false)
        }
    }

    private suspend fun executeAjaxRequestAwait(
        runtime: EngineHttpRuntime,
        request: EngineHttpRequestV2,
        skipRateLimit: Boolean,
    ): EngineHttpResponseV2 {
        if (!skipRateLimit) {
            return ConcurrentRateLimiter(source).withLimit {
                executeAjaxRequestNow(runtime, request)
            }
        }
        return executeAjaxRequestNow(runtime, request)
    }

    private suspend fun executeAjaxRequestNow(
        runtime: EngineHttpRuntime,
        request: EngineHttpRequestV2,
    ): EngineHttpResponseV2 {
        val sourceId = sourceId()
        val cookie = cookieStore?.get(sourceId, request.url)
        val requestWithCookie = if (!cookie.isNullOrBlank() && "Cookie" !in request.headers) {
            request.copy(headers = request.headers + ("Cookie" to cookie))
        } else {
            request
        }
        val response = runtime.execute(requestWithCookie)
        response.headers.entries.firstOrNull { it.key.equals("Set-Cookie", true) }
            ?.value
            ?.firstOrNull()
            ?.let { cookieStore?.put(sourceId, request.url, it) }
        return response
    }

    private fun executeJsHttp(
        method: String,
        urlStr: String,
        headers: Any?,
        body: String?,
        timeoutMs: Long?,
    ): JsHttpResponse {
        val runtime = httpRuntime ?: return JsHttpResponse(
            EngineHttpResponseV2(
                statusCode = 0,
                body = "UNSUPPORTED:java.${method.lowercase()}:$urlStr",
                finalUrl = absolutize(urlStr),
            ),
        )
        val analyzed = AnalyzeUrl(
            mUrl = urlStr,
            baseUrl = baseUrl.orEmpty(),
            source = source,
        ).toRequestSpec()
        val sourceId = sourceId()
        val headerMap = analyzed.headers + headers.toHeaderMap()
        val request = EngineHttpRequestV2(
            sourceId = sourceId,
            url = analyzed.url,
            method = method,
            headers = headerMap,
            body = body ?: analyzed.body,
            charset = analyzed.charset,
            proxy = analyzed.proxy,
            timeoutMs = timeoutMs ?: analyzed.timeoutMs,
        )
        return runBlocking {
            JsHttpResponse(executeAjaxRequestAwait(runtime, request, skipRateLimit = false))
        }
    }

    private fun buildAjaxRequest(url: Any): EngineHttpRequestV2 {
        val sourceId = sourceId()
        if (url is NativeObject) {
            val targetUrl = absolutize(url.readString("url") ?: url.readString("href").orEmpty())
            return EngineHttpRequestV2(
                sourceId = sourceId,
                url = targetUrl,
                method = url.readString("method")?.uppercase() ?: "GET",
                headers = url.readHeaders(),
                body = url.readString("body"),
                charset = url.readString("charset"),
                proxy = url.readString("proxy"),
                timeoutMs = url.readLong("timeoutMs") ?: url.readLong("timeout"),
            )
        }
        val urlStr = when (url) {
            is NativeArray -> url.get(0)?.toString().orEmpty()
            is Iterable<*> -> url.firstOrNull()?.toString().orEmpty()
            else -> url.toString()
        }
        val analyzed = AnalyzeUrl(
            mUrl = urlStr,
            baseUrl = baseUrl.orEmpty(),
            source = source,
        ).toRequestSpec()
        return EngineHttpRequestV2(
            sourceId = sourceId,
            url = analyzed.url,
            method = analyzed.method,
            headers = analyzed.headers,
            body = analyzed.body,
            charset = analyzed.charset,
            proxy = analyzed.proxy,
            timeoutMs = analyzed.timeoutMs,
        )
    }

    private fun Any.toAjaxRequests(): List<EngineHttpRequestV2> =
        when (this) {
            is NativeArray -> (0 until length.toInt()).mapNotNull { index ->
                get(index, this).takeUnlessMissing()?.let(::buildAjaxRequest)
            }

            is Array<*> -> mapNotNull { it?.let(::buildAjaxRequest) }
            is Iterable<*> -> mapNotNull { it?.let(::buildAjaxRequest) }
            is NativeJavaObject -> unwrap().toAjaxRequests()
            else -> listOf(buildAjaxRequest(this))
        }

    private fun Any?.takeUnlessMissing(): Any? =
        when (this) {
            null, Undefined.instance, UniqueTag.NOT_FOUND -> null
            else -> this
        }

    private fun variableTarget(): RuleDataInterface = ruleData ?: localRuleData

    private fun sourceId(): String = source?.getKey() ?: baseUrl ?: "AnalyzeRule"

    private fun NativeObject.readString(key: String): String? =
        get(key, this).toCleanString()

    private fun NativeObject.readLong(key: String): Long? =
        readString(key)?.toLongOrNull()

    private fun NativeObject.readHeaders(): Map<String, String> {
        val headersValue = get("headers", this)
        if (headersValue !is NativeObject) return emptyMap()
        return headersValue.ids.mapNotNull { id ->
            val key = id.toString()
            val value = headersValue.get(key, headersValue).toCleanString()
            value?.let { key to it }
        }.toMap()
    }

    private fun Any?.toHeaderMap(): Map<String, String> =
        when (this) {
            null, Undefined.instance, UniqueTag.NOT_FOUND -> emptyMap()
            is NativeObject -> ids.mapNotNull { id ->
                val key = id.toString()
                val value = get(key, this).toCleanString()
                value?.let { key to it }
            }.toMap()
            is Map<*, *> -> entries.mapNotNull { (key, value) ->
                val headerName = key?.toString() ?: return@mapNotNull null
                val headerValue = value?.toString() ?: return@mapNotNull null
                headerName to headerValue
            }.toMap()
            is String -> runCatching {
                JSON.decodeFromString<Map<String, String>>(this)
            }.getOrDefault(emptyMap())
            is NativeJavaObject -> unwrap().toHeaderMap()
            else -> emptyMap()
        }

    private fun Any?.toCleanString(): String? {
        val rawValue = when (this) {
            null, Undefined.instance, UniqueTag.NOT_FOUND -> return null
            is NativeJavaObject -> unwrap()
            else -> this
        }
        val value = Context.toString(rawValue).trim()
        return value.takeIf { it.isNotBlank() && it != "undefined" && it != "null" }
    }

    private fun applyFallback(rule: String): List<String> =
        RuleAnalyzer(rule).splitRule("||").ifEmpty { listOf(rule) }

    private fun applyReplace(
        rule: String,
        evaluator: (String) -> List<String>,
    ): List<String> {
        val firstMarker = rule.indexOf("##")
        if (firstMarker == -1) return evaluator(rule)
        val secondMarker = rule.indexOf("##", firstMarker + 2)
        if (secondMarker == -1) return evaluator(rule)
        val cleanRule = rule.substring(0, firstMarker).trim()
        val pattern = rule.substring(firstMarker + 2, secondMarker).trim().toRegex()
        val replacement = rule.substring(secondMarker + 2).trim()
        return evaluator(cleanRule).map { pattern.replace(it, replacement).trim() }
    }

    private fun evaluateRule(rule: String, currentContent: Any, isUrl: Boolean): List<String> {
        val jsPipeline = splitJsPipeline(rule)
        if (jsPipeline.size == 1) return evaluateSingleRule(rule, currentContent, isUrl)
        var currentValues: List<Any> = listOf(currentContent)
        jsPipeline.forEachIndexed { index, step ->
            val isLast = index == jsPipeline.lastIndex
            currentValues = currentValues.flatMap { current ->
                if (step.isJsRule()) {
                    jsValueToObjects(evalJS(step.extractJs(), current))
                } else if (isLast) {
                    evaluateSingleRule(step, current, isUrl)
                } else {
                    evaluateSingleRule(step, current, false)
                }
            }
        }
        return currentValues.mapNotNull { value ->
            value.toCleanString()?.let { if (isUrl) absolutize(it) else it }
        }
    }

    private fun evaluateSingleRule(rule: String, currentContent: Any, isUrl: Boolean): List<String> =
        when {
            rule.startsWith("@js:", true) ->
                listOf(jsValueToString(evalJS(rule.extractJs(), currentContent)))

            rule.startsWith("<js>", true) -> {
                listOf(jsValueToString(evalJS(rule.extractJs(), currentContent)))
            }

            rule.startsWith("xpath:", true) ->
                AnalyzeByXPath(currentContent).getStringList(rule.removePrefixIgnoreCase("xpath:"))

            rule.startsWith("xpath://", true) ->
                AnalyzeByXPath(currentContent).getStringList(rule.removePrefixIgnoreCase("xpath:"))

            rule.startsWith("$") ->
                AnalyzeByJSonPath(currentContent).getStringList(rule)

            rule.startsWith("regex:", true) ->
                evaluateRegex(rule.removePrefixIgnoreCase("regex:"), currentContent)

            else ->
                evaluateHtml(rule, currentContent, isUrl)
        }

    private fun splitJsPipeline(rule: String): List<String> {
        val steps = mutableListOf<String>()
        var rest = rule.trim()
        while (rest.isNotEmpty()) {
            val token = findNextJsToken(rest)
            if (token == null) {
                steps += rest
                break
            }
            if (token.index > 0) {
                rest.substring(0, token.index).trim().takeIf { it.isNotEmpty() }?.let(steps::add)
                rest = rest.substring(token.index).trim()
                continue
            }
            if (token.text.equals("@js:", true)) {
                steps += rest
                break
            }
            val closeStart = rest.indexOf("</js>", ignoreCase = true)
            if (closeStart == -1) {
                steps += rest
                break
            }
            val closeEnd = closeStart + "</js>".length
            steps += rest.substring(0, closeEnd).trim()
            rest = rest.substring(closeEnd).trim()
        }
        return steps
    }

    private fun findNextJsToken(value: String): JsToken? {
        var squareDepth = 0
        var roundDepth = 0
        var inSingleQuote = false
        var inDoubleQuote = false
        var index = 0
        while (index < value.length) {
            val char = value[index]
            if (char == '\\') {
                index += 2
                continue
            }
            if (char == '\'' && !inDoubleQuote) {
                inSingleQuote = !inSingleQuote
                index += 1
                continue
            }
            if (char == '"' && !inSingleQuote) {
                inDoubleQuote = !inDoubleQuote
                index += 1
                continue
            }
            if (!inSingleQuote && !inDoubleQuote) {
                when (char) {
                    '[' -> squareDepth += 1
                    ']' -> squareDepth = (squareDepth - 1).coerceAtLeast(0)
                    '(' -> roundDepth += 1
                    ')' -> roundDepth = (roundDepth - 1).coerceAtLeast(0)
                }
                if (squareDepth == 0 && roundDepth == 0) {
                    if (value.regionMatches(index, "<js>", 0, "<js>".length, ignoreCase = true)) {
                        return JsToken(index, "<js>")
                    }
                    if (value.regionMatches(index, "@js:", 0, "@js:".length, ignoreCase = true)) {
                        return JsToken(index, "@js:")
                    }
                }
            }
            index += 1
        }
        return null
    }

    private fun String.isJsRule(): Boolean =
        startsWith("@js:", true) || startsWith("<js>", true)

    private fun String.extractJs(): String =
        when {
            startsWith("@js:", true) -> substringAfter(":", missingDelimiterValue = "")
            startsWith("<js>", true) -> substringAfter("<js>").substringBeforeLast("</js>")
            else -> this
        }

    private fun Any?.toJsBinding(): Any? =
        when (this) {
            is List<*> -> if (size == 1) firstOrNull() else toTypedArray()
            else -> this
        }

    private fun jsValueToObjects(value: Any?): List<Any> {
        val unwrapped = when (value) {
            is NativeJavaObject -> value.unwrap()
            else -> value
        }
        return when (unwrapped) {
            null, Undefined.instance -> emptyList()
            is JsElementList -> unwrapped.toArray().toList()
            is Elements -> unwrapped.toList()
            is NativeArray -> (0 until unwrapped.length.toInt()).mapNotNull { index ->
                unwrapped.get(index, unwrapped).takeUnlessMissing()?.let {
                    if (it is NativeJavaObject) it.unwrap() else it
                }
            }
            is Array<*> -> unwrapped.filterNotNull()
            is Iterable<*> -> unwrapped.filterNotNull()
            else -> listOf(unwrapped)
        }
    }

    private fun evaluateHtml(rule: String, currentContent: Any, isUrl: Boolean): List<String> =
        AnalyzeByJSoup(currentContent).getStringList(rule).map { value ->
            if (isUrl) absolutize(value) else value
        }

    private fun evaluateRegex(pattern: String, currentContent: Any): List<String> {
        val parts = RuleAnalyzer(pattern).splitRule("&&").toTypedArray()
        return AnalyzeByRegex.getElements(currentContent.toString(), parts).map { groups ->
            groups.getOrNull(1) ?: groups.firstOrNull().orEmpty()
        }.toList()
    }

    private fun jsValueToString(value: Any?): String =
        when (value) {
            null, Undefined.instance -> ""
            is NativeJavaObject -> value.unwrap()?.toString().orEmpty()
            else -> Context.toString(value)
        }

    private fun absolutize(url: String): String {
        if (url.isBlank()) return ""
        if (url.startsWith("http://", true) || url.startsWith("https://", true)) return url
        val base = baseUrl ?: return url
        return runCatching { URI(base).resolve(url).toString() }.getOrDefault(url)
    }

    private fun String.removePrefixIgnoreCase(prefix: String): String =
        if (startsWith(prefix, true)) substring(prefix.length) else this

    inner class JsCookieBridge {
        fun getCookie(url: String): String =
            this@AnalyzeRule.getCookie(url)

        fun setCookie(url: String, cookie: String) {
            runBlocking { cookieStore?.put(sourceId(), absolutize(url), cookie) }
        }

        fun removeCookie(url: String) {
            runBlocking { cookieStore?.remove(sourceId(), absolutize(url)) }
        }
    }

    private companion object {
        val JSON = Json {
            ignoreUnknownKeys = true
        }

        data class JsToken(
            val index: Int,
            val text: String,
        )
    }
}

data class AnalyzeRuleUnsupported(
    val code: String,
    val message: String,
    val rule: String? = null,
)
