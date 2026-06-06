package legadohub.engine.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

/**
 * 阅读 BookSource 的后端内核表示。
 *
 * 字段命名保持与阅读 JSON 一致，避免导入和调试时丢失原始语义。
 */
@Serializable
data class BookSource(
    val bookSourceUrl: String = "",
    val bookSourceName: String = "",
    val bookSourceGroup: String? = null,
    val bookSourceType: Int = 0,
    val bookUrlPattern: String? = null,
    val customOrder: Int = 0,
    val enabled: Boolean = true,
    val enabledExplore: Boolean = true,
    val jsLib: String? = null,
    val enabledCookieJar: Boolean? = true,
    val concurrentRate: String? = null,
    val header: String? = null,
    val loginUrl: String? = null,
    val loginUi: String? = null,
    val loginCheckJs: String? = null,
    val coverDecodeJs: String? = null,
    val bookSourceComment: String? = null,
    val variableComment: String? = null,
    val lastUpdateTime: Long = 0,
    val respondTime: Long = 180000L,
    val weight: Int = 0,
    val exploreUrl: String? = null,
    val exploreScreen: String? = null,
    val ruleExplore: JsonElement? = null,
    val searchUrl: String? = null,
    val ruleSearch: JsonElement? = null,
    val ruleBookInfo: JsonElement? = null,
    val ruleToc: JsonElement? = null,
    val ruleContent: JsonElement? = null,
    val ruleReview: JsonElement? = null,
    val eventListener: Boolean = false,
    val customButton: Boolean = false,
) {
    val sourceId: String
        get() = bookSourceUrl

    fun validate(): BookSourceValidation =
        when {
            bookSourceUrl.isBlank() -> BookSourceValidation.Invalid("bookSourceUrl 不能为空")
            bookSourceName.isBlank() -> BookSourceValidation.Invalid("bookSourceName 不能为空")
            else -> BookSourceValidation.Valid
        }

    fun displayNameWithGroup(): String =
        if (bookSourceGroup.isNullOrBlank()) {
            bookSourceName
        } else {
            "$bookSourceName ($bookSourceGroup)"
        }
}

@Serializable
sealed interface BookSourceValidation {
    @Serializable
    @SerialName("valid")
    data object Valid : BookSourceValidation

    @Serializable
    @SerialName("invalid")
    data class Invalid(val reason: String) : BookSourceValidation
}
