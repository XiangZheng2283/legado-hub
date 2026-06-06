package io.legado.app.model.analyzeRule

import org.jsoup.Jsoup
import org.jsoup.nodes.Element

class AnalyzeByXPath(doc: Any) {
    private val element: Element = when (doc) {
        is Element -> doc
        else -> Jsoup.parse(doc.toString())
    }

    fun getElements(xPath: String): List<Element> {
        val analyzer = RuleAnalyzer(xPath)
        val rules = analyzer.splitRule("&&", "||", "%%")
        val results = rules.map { rule -> element.selectXpath(normalize(rule)) }
            .filter { it.isNotEmpty() }
            .let { if (analyzer.elementsType == "||") it.take(1) else it }
        return if (analyzer.elementsType == "%%") {
            val merged = mutableListOf<Element>()
            val max = results.maxOfOrNull { it.size } ?: 0
            for (index in 0 until max) {
                results.forEach { if (index < it.size) merged += it[index] }
            }
            merged
        } else {
            results.flatten()
        }
    }

    fun getStringList(xPath: String): List<String> {
        val normalized = normalize(xPath)
        return when {
            normalized.endsWith("/text()") -> {
                val path = normalized.removeSuffix("/text()")
                AnalyzeByXPath(element).getElements(path).map { it.text() }
            }
            "/@" in normalized -> {
                val path = normalized.substringBeforeLast("/@")
                val attr = normalized.substringAfterLast("/@")
                AnalyzeByXPath(element).getElements(path).map { it.attr(attr) }
            }
            else -> getElements(normalized).map { it.text() }
        }
    }

    fun getString(rule: String): String? =
        getStringList(rule).takeIf { it.isNotEmpty() }?.joinToString("\n")

    private fun normalize(rule: String): String =
        if (rule.startsWith("//")) rule else "//$rule"
}

