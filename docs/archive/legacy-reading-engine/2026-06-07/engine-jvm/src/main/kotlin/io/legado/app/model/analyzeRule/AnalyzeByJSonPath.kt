package io.legado.app.model.analyzeRule

import com.jayway.jsonpath.JsonPath
import com.jayway.jsonpath.ReadContext

class AnalyzeByJSonPath(json: Any) {
    private val ctx: ReadContext = when (json) {
        is ReadContext -> json
        is String -> JsonPath.parse(json)
        else -> JsonPath.parse(json)
    }

    fun getString(rule: String): String? {
        val list = getStringList(rule)
        return when {
            list.isEmpty() -> null
            list.size == 1 -> list.first()
            else -> list.joinToString("\n")
        }
    }

    fun getStringList(rule: String): List<String> {
        if (rule.isBlank()) return emptyList()
        val analyzer = RuleAnalyzer(rule, code = true)
        val rules = analyzer.splitRule("&&", "||", "%%")
        val results = rules.mapNotNull { single ->
            readList(single).takeIf { it.isNotEmpty() }
        }.let { if (analyzer.elementsType == "||") it.take(1) else it }
        return if (analyzer.elementsType == "%%") {
            val merged = mutableListOf<String>()
            val max = results.maxOfOrNull { it.size } ?: 0
            for (index in 0 until max) {
                results.forEach { if (index < it.size) merged += it[index] }
            }
            merged
        } else {
            results.flatten()
        }
    }

    fun getList(rule: String): ArrayList<Any>? =
        runCatching {
            when (val value = ctx.read<Any>(rule)) {
                is ArrayList<*> -> ArrayList(value.filterNotNull())
                is List<*> -> ArrayList(value.filterNotNull())
                null -> arrayListOf()
                else -> arrayListOf(value)
            }
        }.getOrNull()

    private fun readList(rule: String): List<String> =
        runCatching {
            val replaced = RuleAnalyzer(rule, code = true).innerRule("{$.") { getString(it) }
            val target = replaced.ifEmpty { rule }
            when (val value = ctx.read<Any>(target)) {
                is List<*> -> value.mapNotNull { it?.toString() }
                null -> emptyList()
                else -> listOf(value.toString())
            }
        }.getOrDefault(emptyList())
}

