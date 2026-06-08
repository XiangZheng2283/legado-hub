package io.legado.app.data.entities

import io.legado.app.model.analyzeRule.RuleDataInterface
import kotlinx.serialization.Serializable

@Serializable
data class SearchBook(
    var name: String = "",
    var author: String = "",
    var bookUrl: String = "",
    var origin: String = "",
    var originName: String = "",
    var originOrder: Int = 0,
    var coverUrl: String? = null,
    var intro: String? = null,
    var kind: String? = null,
    var wordCount: String? = null,
    var latestChapterTitle: String? = null,
    var updateTime: String? = null,
    var infoHtml: String? = null,
    var variable: String? = null,
    var type: Int = 0,
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

    fun toBook(): Book =
        Book(
            name = name,
            author = author,
            bookUrl = bookUrl,
            origin = origin,
            originName = originName,
            originOrder = originOrder,
            coverUrl = coverUrl,
            intro = intro,
            kind = kind,
            wordCount = wordCount,
            latestChapterTitle = latestChapterTitle,
            updateTime = updateTime,
            infoHtml = infoHtml,
            variable = variable,
            type = type,
        )
}

