package io.legado.app.model.analyzeRule

import org.jsoup.Jsoup
import org.jsoup.nodes.Element
import org.jsoup.select.Elements

class AnalyzeByJSoup(doc: Any) {
    private val element: Element = when (doc) {
        is Element -> doc
        else -> Jsoup.parse(doc.toString())
    }

    fun getElements(rule: String): Elements {
        if (rule.isBlank()) return Elements()
        val sourceRule = SourceRule(rule)
        val analyzer = RuleAnalyzer(sourceRule.elementsRule)
        val rules = analyzer.splitRule("&&", "||", "%%")
        val results = rules.map { singleRule ->
            if (sourceRule.isCss) {
                element.select(singleRule)
            } else {
                getElementsSingle(element, singleRule)
            }
        }.filter { it.isNotEmpty() }
            .takeIf { it.isNotEmpty() }
            ?.let { if (analyzer.elementsType == "||") listOf(it.first()) else it }
            ?: return Elements()

        return mergeElements(results, analyzer.elementsType)
    }

    fun getString(ruleStr: String): String? {
        val list = getStringList(ruleStr)
        return when {
            list.isEmpty() -> null
            list.size == 1 -> list.first()
            else -> list.joinToString("\n")
        }
    }

    fun getStringList(ruleStr: String): List<String> {
        if (ruleStr.isBlank()) return emptyList()
        val sourceRule = SourceRule(ruleStr)
        val analyzer = RuleAnalyzer(sourceRule.elementsRule)
        val rules = analyzer.splitRule("&&", "||", "%%")
        val results = rules.mapNotNull { singleRule ->
            val values = if (sourceRule.isCss) {
                val (selector, attr) = splitLast(singleRule)
                getResultLast(element.select(selector), attr)
            } else {
                getResultList(singleRule)
            }
            values.takeIf { it.isNotEmpty() }
        }.let { if (analyzer.elementsType == "||") it.take(1) else it }

        return mergeStrings(results, analyzer.elementsType)
    }

    private fun getResultList(ruleStr: String): List<String> {
        val parts = RuleAnalyzer(ruleStr).splitRule("@")
        if (parts.isEmpty()) return emptyList()
        var elements = Elements(element)
        for (index in 0 until parts.lastIndex) {
            val next = Elements()
            elements.forEach { next.addAll(getElementsSingle(it, parts[index])) }
            elements = next
        }
        return getResultLast(elements, parts.last())
    }

    private fun getElementsSingle(root: Element, rule: String): Elements {
        if (rule.isBlank()) return Elements(root)
        val indexRule = splitIndexRule(rule)
        val selected = when {
            indexRule.selector.isBlank() -> root.children()
            indexRule.selector.startsWith("class.") -> root.getElementsByClass(indexRule.selector.substringAfter("class."))
            indexRule.selector.startsWith("tag.") -> root.getElementsByTag(indexRule.selector.substringAfter("tag."))
            indexRule.selector.startsWith("id.") -> Elements(root.getElementById(indexRule.selector.substringAfter("id.")))
            else -> root.select(indexRule.selector)
        }
        if (indexRule.selectors.isEmpty()) return selected
        val indexes = indexRule.selectors
            .flatMap { it.resolve(selected.size) }
            .filter { it in 0 until selected.size }
            .toCollection(LinkedHashSet())
        return if (indexRule.exclude) {
            Elements(selected.filterIndexed { index, _ -> index !in indexes })
        } else {
            Elements(indexes.mapNotNull { selected.getOrNull(it) })
        }
    }

    private fun getResultLast(elements: Elements, lastRule: String): List<String> =
        when (lastRule) {
            "", "text" -> elements.mapNotNull { it.text().takeIf(String::isNotEmpty) }
            "textNodes" -> elements.mapNotNull { element ->
                element.textNodes()
                    .map { it.text().trim() }
                    .filter { it.isNotEmpty() }
                    .joinToString("\n")
                    .takeIf { it.isNotEmpty() }
            }
            "ownText" -> elements.mapNotNull { it.ownText().takeIf(String::isNotEmpty) }
            "html" -> elements.mapNotNull { it.html().takeIf(String::isNotEmpty) }
            "all", "outerHtml" -> elements.mapNotNull { it.outerHtml().takeIf(String::isNotEmpty) }
            else -> elements.mapNotNull { it.attr(lastRule).takeIf(String::isNotBlank) }.distinct()
        }

    private fun splitLast(rule: String): Pair<String, String> {
        val parts = RuleAnalyzer(rule).splitRule("@")
        return if (parts.size < 2) rule to "text" else parts.dropLast(1).joinToString("@") to parts.last()
    }

    private fun splitIndexRule(rule: String): IndexRule {
        val bracketStart = rule.lastIndexOf("[")
        if (rule.endsWith("]") && bracketStart != -1) {
            val body = rule.substring(bracketStart + 1, rule.length - 1).trim()
            val exclude = body.startsWith("!")
            val selectors = body.removePrefix("!")
                .split(",")
                .mapNotNull { parseIndexSelector(it.trim()) }
            return IndexRule(rule.substring(0, bracketStart), exclude, selectors)
        }

        val oldStyle = OLD_INDEX_REGEX.matchEntire(rule)
        if (oldStyle != null) {
            val selector = oldStyle.groupValues[1]
            val exclude = oldStyle.groupValues[2] == "!"
            val selectors = listOfNotNull(parseIndexSelector(oldStyle.groupValues[3]))
            return IndexRule(selector, exclude, selectors)
        }

        return IndexRule(rule, false, emptyList())
    }

    private fun parseIndexSelector(value: String): IndexSelector? {
        if (value.isBlank()) return null
        val parts = value.split(":").map { it.trim() }
        return when (parts.size) {
            1 -> parts[0].toIntOrNull()?.let { IndexSelector(it, it) }
            2, 3 -> {
                val start = parts[0].takeIf { it.isNotEmpty() }?.toIntOrNull()
                val end = parts[1].takeIf { it.isNotEmpty() }?.toIntOrNull()
                val step = parts.getOrNull(2)?.takeIf { it.isNotEmpty() }?.toIntOrNull() ?: 1
                IndexSelector(start, end, step.coerceAtLeast(1))
            }
            else -> null
        }
    }

    private fun mergeElements(results: List<Elements>, type: String): Elements {
        val merged = Elements()
        if (type == "%%") {
            val max = results.maxOfOrNull { it.size } ?: 0
            for (index in 0 until max) {
                results.forEach { if (index < it.size) merged.add(it[index]) }
            }
        } else {
            results.forEach { merged.addAll(it) }
        }
        return merged
    }

    private fun mergeStrings(results: List<List<String>>, type: String): List<String> {
        if (type != "%%") return results.flatten()
        val merged = mutableListOf<String>()
        val max = results.maxOfOrNull { it.size } ?: 0
        for (index in 0 until max) {
            results.forEach { if (index < it.size) merged += it[index] }
        }
        return merged
    }

    private class SourceRule(ruleStr: String) {
        var isCss = false
        val elementsRule: String = if (ruleStr.startsWith("@CSS:", true)) {
            isCss = true
            ruleStr.substring(5).trim()
        } else {
            ruleStr
        }
    }

    private data class IndexRule(
        val selector: String,
        val exclude: Boolean,
        val selectors: List<IndexSelector>,
    )

    private data class IndexSelector(
        val start: Int?,
        val end: Int?,
        val step: Int = 1,
    ) {
        fun resolve(size: Int): List<Int> {
            if (size <= 0) return emptyList()
            val resolvedStart = resolveIndex(start ?: 0, size).coerceIn(0, size - 1)
            val resolvedEnd = resolveIndex(end ?: (size - 1), size).coerceIn(0, size - 1)
            return if (resolvedStart <= resolvedEnd) {
                (resolvedStart..resolvedEnd step step).toList()
            } else {
                (resolvedStart downTo resolvedEnd step step).toList()
            }
        }

        private fun resolveIndex(index: Int, size: Int): Int =
            if (index < 0) size + index else index
    }

    companion object {
        private val OLD_INDEX_REGEX = Regex("""^(.+)([.!])(-?\d+(?::-?\d+(?::-?\d+)?)?)$""")
    }
}
