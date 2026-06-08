package io.legado.app.data.entities

import java.util.concurrent.ConcurrentHashMap

/**
 * JVM port of Reading's BaseSource contract.
 *
 * Android, cache, cookie, and JS runtime calls are intentionally excluded from
 * this first model slice. They will be reattached through LegadoHub runtime
 * adapters when AnalyzeUrl/AnalyzeRule are ported.
 */
interface BaseSource {
    var concurrentRate: String?
    var loginUrl: String?
    var loginUi: String?
    var header: String?
    var enabledCookieJar: Boolean?
    var jsLib: String?

    fun getTag(): String

    fun getKey(): String

    fun getSource(): BaseSource? = this

    fun setVariable(variable: Any?) {
        putVariable(variable)
    }

    fun putVariable(variable: Any?) {
        if (variable == null) {
            sourceVariables.remove(getKey())
        } else {
            sourceVariables[getKey()] = variable.toSourceText()
        }
    }

    fun getVariable(): String =
        sourceVariables[getKey()].orEmpty()

    fun put(key: String, value: Any?): String {
        val text = value.toSourceText()
        sourceValues[valueKey(key)] = text
        return text
    }

    fun get(key: String): String =
        sourceValues[valueKey(key)].orEmpty()

    fun getLoginJs(): String? {
        val loginJs = loginUrl
        return when {
            loginJs == null -> null
            loginJs.startsWith("@js:") -> loginJs.substring(4)
            loginJs.startsWith("<js>") -> loginJs.substring(4, loginJs.lastIndexOf("<"))
            else -> loginJs
        }
    }

    private fun valueKey(key: String): String =
        "${getKey()}::$key"

    private fun Any?.toSourceText(): String =
        when (this) {
            null -> ""
            is Double -> if (this % 1.0 == 0.0) "%.0f".format(this) else toString()
            is Float -> if (this % 1.0f == 0.0f) "%.0f".format(this) else toString()
            else -> toString()
        }

    companion object {
        private val sourceVariables = ConcurrentHashMap<String, String>()
        private val sourceValues = ConcurrentHashMap<String, String>()
    }
}
