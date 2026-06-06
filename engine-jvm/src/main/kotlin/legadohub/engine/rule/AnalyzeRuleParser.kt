package legadohub.engine.rule

import com.jayway.jsonpath.JsonPath
import legadohub.engine.model.UnsupportedCode
import legadohub.engine.model.UnsupportedReason
import org.jsoup.Jsoup

class AnalyzeRuleParser {
    fun analyze(input: AnalyzeRuleInput): AnalyzeRuleResult {
        val unsupported = mutableListOf<UnsupportedReason>()
        val rules = input.rule.split(FALLBACK_SEPARATOR)
            .map { it.trim() }
            .filter { it.isNotEmpty() }

        for (rule in rules) {
            val result = analyzeOne(input.content, rule, unsupported)
            if (result.isNotEmpty()) {
                return AnalyzeRuleResult(result, unsupported)
            }
        }

        return AnalyzeRuleResult(emptyList(), unsupported)
    }

    private fun analyzeOne(
        content: String,
        rawRule: String,
        unsupported: MutableList<UnsupportedReason>,
    ): List<String> {
        if (rawRule.contains("@js", ignoreCase = true) || rawRule.contains("<js>", ignoreCase = true)) {
            unsupported += UnsupportedReason(
                code = UnsupportedCode.ComplexJavaScript,
                message = "规则包含 JavaScript，当前阶段仅结构化标记",
                field = "rule",
            )
            return emptyList()
        }

        val (rule, replacements) = splitReplacements(rawRule)
        val values = when {
            rule.startsWith("$") -> analyzeJsonPath(content, rule, unsupported)
            rule.startsWith("regex:", ignoreCase = true) -> analyzeRegex(content, rule.removePrefix("regex:"))
            rule.startsWith("xpath:", ignoreCase = true) -> {
                unsupported += UnsupportedReason(
                    code = UnsupportedCode.UnsupportedRuleSyntax,
                    message = "XPath 后续接入独立 HTML XPath 适配器，当前阶段先结构化标记",
                    field = "rule",
                )
                emptyList()
            }
            else -> analyzeCss(content, rule)
        }

        return values.map { value ->
            replacements.fold(value) { current, replacement ->
                replacement.pattern.replace(current, replacement.replacement)
            }
        }.filter { it.isNotBlank() }
    }

    private fun analyzeCss(content: String, rule: String): List<String> {
        val (selector, operation) = splitOperation(rule)
        if (selector.isBlank()) return emptyList()
        val elements = Jsoup.parse(content).select(selector)
        return elements.mapNotNull { element ->
            when {
                operation == null || operation == "text" -> element.text()
                operation == "html" -> element.html()
                operation == "outerHtml" -> element.outerHtml()
                operation.startsWith("attr.") -> element.attr(operation.removePrefix("attr."))
                else -> element.attr(operation).ifBlank {
                    element.selectFirst(operation)?.text().orEmpty()
                }
            }.takeIf { it.isNotBlank() }
        }
    }

    private fun analyzeJsonPath(
        content: String,
        rule: String,
        unsupported: MutableList<UnsupportedReason>,
    ): List<String> =
        runCatching {
            when (val value = JsonPath.parse(content).read<Any?>(rule)) {
                null -> emptyList()
                is Iterable<*> -> value.mapNotNull { it?.toString() }
                is Array<*> -> value.mapNotNull { it?.toString() }
                else -> listOf(value.toString())
            }
        }.getOrElse { error ->
            unsupported += UnsupportedReason(
                code = UnsupportedCode.UnsupportedRuleSyntax,
                message = "JsonPath 执行失败：${error.message}",
                field = "rule",
            )
            emptyList()
        }

    private fun analyzeRegex(content: String, pattern: String): List<String> =
        Regex(pattern, RegexOption.DOT_MATCHES_ALL)
            .findAll(content)
            .map { match ->
                if (match.groupValues.size > 1) {
                    match.groupValues[1]
                } else {
                    match.value
                }
            }
            .toList()

    private fun splitOperation(rule: String): Pair<String, String?> {
        val at = rule.lastIndexOf('@')
        if (at <= 0 || at == rule.lastIndex) return rule to null
        return rule.substring(0, at).trim() to rule.substring(at + 1).trim()
    }

    private fun splitReplacements(rule: String): Pair<String, List<ReplacementRule>> {
        val parts = splitKeepingTrailingEmpty(rule, REPLACE_SEPARATOR)
        if (parts.size < 3) return rule to emptyList()

        val baseRule = parts.first().trim()
        val replacements = mutableListOf<ReplacementRule>()
        var index = 1
        while (index + 1 < parts.size) {
            replacements += ReplacementRule(
                pattern = Regex(parts[index], RegexOption.DOT_MATCHES_ALL),
                replacement = parts[index + 1],
            )
            index += 2
        }
        return baseRule to replacements
    }

    private fun splitKeepingTrailingEmpty(value: String, delimiter: String): List<String> {
        val parts = mutableListOf<String>()
        var start = 0
        while (true) {
            val index = value.indexOf(delimiter, start)
            if (index < 0) {
                parts += value.substring(start)
                return parts
            }
            parts += value.substring(start, index)
            start = index + delimiter.length
        }
    }

    private data class ReplacementRule(
        val pattern: Regex,
        val replacement: String,
    )

    companion object {
        private const val FALLBACK_SEPARATOR = "||"
        private const val REPLACE_SEPARATOR = "##"
    }
}
