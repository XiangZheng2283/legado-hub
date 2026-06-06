package io.legado.app.help

import legadohub.engine.runtime.EngineHttpResponseV2

class JsHttpResponse(
    private val response: EngineHttpResponseV2,
) {
    val url: String? get() = url()

    fun body(): String = response.body

    fun header(name: String): String? =
        response.headers.entries.firstOrNull { it.key.equals(name, ignoreCase = true) }
            ?.value
            ?.firstOrNull()

    fun headers(): Map<String, List<String>> = response.headers

    fun cookie(name: String): String? =
        response.headers.entries
            .filter { it.key.equals("Set-Cookie", ignoreCase = true) }
            .flatMap { it.value }
            .firstNotNullOfOrNull { cookie ->
                val pair = cookie.substringBefore(";")
                val key = pair.substringBefore("=").trim()
                val value = pair.substringAfter("=", missingDelimiterValue = "").trim()
                if (key == name) value else null
            }

    fun statusCode(): Int = response.statusCode

    fun code(): Int = response.statusCode

    fun message(): String =
        when (response.statusCode) {
            in 200..299 -> "OK"
            0 -> "UNSUPPORTED"
            else -> "HTTP ${response.statusCode}"
        }

    fun isSuccessful(): Boolean = response.statusCode in 200..299

    fun url(): String? = response.finalUrl

    fun callTime(): Long = response.elapsedMs

    fun raw(): JsHttpResponse = this

    override fun toString(): String =
        "Response{code=${response.statusCode}, url=${response.finalUrl.orEmpty()}}"
}
