package io.legado.app.data.entities

import io.legado.app.model.analyzeRule.RuleDataInterface
import kotlinx.serialization.Serializable

@Serializable
data class BookChapter(
    var title: String = "",
    var url: String = "",
    var index: Int = 0,
    var baseUrl: String? = null,
    var isVolume: Boolean = false,
    var isVip: Boolean = false,
    var isPay: Boolean = false,
    var updateTime: String? = null,
    override val variableMap: HashMap<String, String> = hashMapOf(),
) : RuleDataInterface {
    private val bigVariableMap: HashMap<String, String> = hashMapOf()

    override fun putBigVariable(key: String, value: String?) {
        if (value == null) {
            bigVariableMap.remove(key)
        } else {
            bigVariableMap[key] = value
        }
    }

    override fun getBigVariable(key: String): String? = bigVariableMap[key]
}

