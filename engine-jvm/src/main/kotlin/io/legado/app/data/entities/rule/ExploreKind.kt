package io.legado.app.data.entities.rule

import kotlinx.serialization.Serializable

/**
 * JVM port slice of Reading's discovery category model.
 *
 * UI-only style fields are intentionally omitted from the engine contract.
 */
@Serializable
data class ExploreKind(
    val title: String = "",
    val url: String? = null,
    val type: String = Type.url,
    val action: String? = null,
    val chars: List<String?>? = null,
    val default: String? = null,
    var viewName: String? = null,
) {
    object Type {
        const val url = "url"
        const val text = "text"
        const val button = "button"
        const val toggle = "toggle"
        const val select = "select"
    }
}
