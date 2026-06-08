package io.legado.app.model.analyzeRule

class RuleData : RuleDataInterface {
    override val variableMap: HashMap<String, String> = hashMapOf()
    private val bigVariableMap: HashMap<String, String> = hashMapOf()

    override fun putBigVariable(key: String, value: String?) {
        if (value == null) {
            bigVariableMap.remove(key)
        } else {
            bigVariableMap[key] = value
        }
    }

    override fun getBigVariable(key: String): String? = bigVariableMap[key]

    fun getVariable(): String? =
        variableMap.takeIf { it.isNotEmpty() }?.entries?.joinToString(
            prefix = "{",
            postfix = "}",
        ) { (key, value) ->
            """"${key.escapeJson()}":"${value.escapeJson()}""""
        }

    private fun String.escapeJson(): String =
        replace("\\", "\\\\").replace("\"", "\\\"")
}

interface RuleDataInterface {
    val variableMap: HashMap<String, String>

    fun putVariable(key: String, value: String?): Boolean {
        val keyExist = variableMap.contains(key)
        return when {
            value == null -> {
                variableMap.remove(key)
                putBigVariable(key, null)
                keyExist
            }

            value.length < 10000 -> {
                putBigVariable(key, null)
                variableMap[key] = value
                true
            }

            else -> {
                variableMap.remove(key)
                putBigVariable(key, value)
                keyExist
            }
        }
    }

    fun getVariable(key: String): String =
        variableMap[key] ?: getBigVariable(key) ?: ""

    fun putBigVariable(key: String, value: String?)

    fun getBigVariable(key: String): String?
}

