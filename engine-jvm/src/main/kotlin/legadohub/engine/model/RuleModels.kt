package legadohub.engine.model

import kotlinx.serialization.Serializable

@Serializable
data class SearchRule(
    val checkKeyWord: String? = null,
    val bookList: String? = null,
    val name: String? = null,
    val author: String? = null,
    val intro: String? = null,
    val kind: String? = null,
    val lastChapter: String? = null,
    val updateTime: String? = null,
    val bookUrl: String? = null,
    val coverUrl: String? = null,
    val wordCount: String? = null,
)
