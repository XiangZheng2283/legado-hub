package io.legado.app.model.analyzeRule

/**
 * JVM port slice of Reading's RuleAnalyzer.
 *
 * It preserves the important rule-splitting contract: separators such as
 * `&&`, `||`, `%%`, `@`, and `##` must not split inside balanced brackets,
 * parentheses, or quoted strings.
 */
class RuleAnalyzer(
    private val data: String,
    private val code: Boolean = false,
) {
    var elementsType: String = ""
        private set

    fun reSetPos() {
        elementsType = ""
    }

    fun splitRule(vararg split: String): ArrayList<String> {
        if (data.isEmpty()) return arrayListOf("")
        val parts = arrayListOf<String>()
        var start = 0
        var pos = 0
        var squareDepth = 0
        var roundDepth = 0
        var curlyDepth = 0
        var inSingleQuote = false
        var inDoubleQuote = false

        while (pos < data.length) {
            val char = data[pos]
            if (char == '\\') {
                pos += 2
                continue
            }
            if (char == '\'' && !inDoubleQuote) {
                inSingleQuote = !inSingleQuote
                pos += 1
                continue
            }
            if (char == '"' && !inSingleQuote) {
                inDoubleQuote = !inDoubleQuote
                pos += 1
                continue
            }
            if (!inSingleQuote && !inDoubleQuote) {
                when (char) {
                    '[' -> squareDepth += 1
                    ']' -> squareDepth = (squareDepth - 1).coerceAtLeast(0)
                    '(' -> roundDepth += 1
                    ')' -> roundDepth = (roundDepth - 1).coerceAtLeast(0)
                    '{' -> if (code) curlyDepth += 1
                    '}' -> if (code) curlyDepth = (curlyDepth - 1).coerceAtLeast(0)
                }
                if (squareDepth == 0 && roundDepth == 0 && curlyDepth == 0) {
                    val hit = split.firstOrNull { token ->
                        data.regionMatches(pos, token, 0, token.length)
                    }
                    if (hit != null) {
                        if (elementsType.isEmpty()) elementsType = hit
                        if (hit == elementsType) {
                            parts += data.substring(start, pos).trim()
                            pos += hit.length
                            start = pos
                            continue
                        }
                    }
                }
            }
            pos += 1
        }

        parts += data.substring(start).trim()
        return parts.filterTo(arrayListOf()) { it.isNotEmpty() }
    }

    fun innerRule(
        inner: String,
        startStep: Int = 1,
        endStep: Int = 1,
        fr: (String) -> String?,
    ): String {
        val builder = StringBuilder()
        var start = 0
        var replaced = false
        while (true) {
            val marker = data.indexOf(inner, start)
            if (marker == -1) break
            val open = marker + startStep
            val end = findBalancedEnd(marker)
            if (end == -1 || end - endStep < open) {
                start = marker + inner.length
                continue
            }
            val value = fr(data.substring(open, end - endStep))
            if (!value.isNullOrEmpty()) {
                builder.append(data.substring(start, marker))
                builder.append(value)
                start = end
                replaced = true
            } else {
                start = marker + inner.length
            }
        }
        if (!replaced) return ""
        builder.append(data.substring(start))
        return builder.toString()
    }

    private fun findBalancedEnd(from: Int): Int {
        var pos = from
        var depth = 0
        var inSingleQuote = false
        var inDoubleQuote = false
        while (pos < data.length) {
            val char = data[pos]
            if (char == '\\') {
                pos += 2
                continue
            }
            if (char == '\'' && !inDoubleQuote) {
                inSingleQuote = !inSingleQuote
            } else if (char == '"' && !inSingleQuote) {
                inDoubleQuote = !inDoubleQuote
            } else if (!inSingleQuote && !inDoubleQuote) {
                if (char == '{') depth += 1
                if (char == '}') {
                    depth -= 1
                    if (depth == 0) return pos + 1
                }
            }
            pos += 1
        }
        return -1
    }
}

