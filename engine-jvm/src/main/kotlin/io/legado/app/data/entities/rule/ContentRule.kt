package io.legado.app.data.entities.rule

import kotlinx.serialization.Serializable

@Serializable
data class ContentRule(
    var content: String? = null,
    var subContent: String? = null,
    var title: String? = null,
    var nextContentUrl: String? = null,
    var webJs: String? = null,
    var sourceRegex: String? = null,
    var replaceRegex: String? = null,
    var imageStyle: String? = null,
    var imageDecode: String? = null,
    var payAction: String? = null,
    var callBackJs: String? = null,
)
