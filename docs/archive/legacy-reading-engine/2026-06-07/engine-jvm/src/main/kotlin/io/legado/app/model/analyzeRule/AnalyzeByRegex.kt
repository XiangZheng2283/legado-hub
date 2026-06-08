package io.legado.app.model.analyzeRule

object AnalyzeByRegex {
    fun getElement(res: String, regs: Array<String>, index: Int = 0): List<String>? {
        val regex = regs.getOrNull(index)?.toRegex() ?: return null
        val matches = regex.findAll(res).toList()
        if (matches.isEmpty()) return null
        if (index + 1 == regs.size) {
            val match = matches.first()
            return if (match.groupValues.size > 1) match.groupValues else listOf(match.value)
        }
        return getElement(matches.joinToString("") { it.value }, regs, index + 1)
    }

    fun getElements(res: String, regs: Array<String>, index: Int = 0): List<List<String>> {
        val regex = regs.getOrNull(index)?.toRegex() ?: return emptyList()
        val matches = regex.findAll(res).toList()
        if (matches.isEmpty()) return emptyList()
        if (index + 1 == regs.size) {
            return matches.map { match ->
                if (match.groupValues.size > 1) match.groupValues else listOf(match.value)
            }
        }
        return getElements(matches.joinToString("") { it.value }, regs, index + 1)
    }
}

