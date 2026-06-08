package io.legado.app.data.entities.rule

import kotlinx.serialization.Serializable

@Serializable
data class ReviewRule(
    var reviewList: String? = null,
    var content: String? = null,
    var author: String? = null,
    var postTime: String? = null,
)
