package legadohub.engine.model

import kotlinx.serialization.Serializable

@Serializable
data class SearchBook(
    val name: String,
    val author: String = "",
    val bookUrl: String = "",
    val intro: String = "",
    val kind: String = "",
    val lastChapter: String = "",
    val updateTime: String = "",
    val coverUrl: String = "",
    val wordCount: String = "",
    val sourceId: String = "",
    val sourceName: String = "",
)
