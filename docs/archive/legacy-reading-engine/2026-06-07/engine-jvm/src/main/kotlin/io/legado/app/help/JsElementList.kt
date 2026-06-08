package io.legado.app.help

import org.jsoup.nodes.Element
import org.jsoup.select.Elements

class JsElementList(
    private val elements: Elements,
) {
    val length: Int
        get() = elements.size

    fun toArray(): Array<Element> =
        elements.toTypedArray()

    fun text(): String =
        elements.joinToString("\n") { it.text() }

    fun html(): String =
        elements.joinToString("\n") { it.html() }

    fun attr(name: String): String =
        elements.firstOrNull()?.attr(name).orEmpty()

    fun get(index: Int): Element? =
        elements.getOrNull(index)

    override fun toString(): String =
        text()
}
