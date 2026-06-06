package legadohub.engine.port

import io.legado.app.data.entities.BookSource
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.json.Json

class BookSourcePortParser(
    private val json: Json = defaultJson,
) {
    fun parseOne(text: String): BookSource =
        json.decodeFromString<BookSource>(text)

    fun parseMany(text: String): List<BookSource> {
        val trimmed = text.trim()
        if (trimmed.isEmpty()) return emptyList()
        return if (trimmed.startsWith("[")) {
            json.decodeFromString<List<BookSource>>(trimmed)
        } else {
            listOf(parseOne(trimmed))
        }
    }

    companion object {
        @OptIn(ExperimentalSerializationApi::class)
        val defaultJson: Json = Json {
            ignoreUnknownKeys = true
            explicitNulls = false
            isLenient = true
            allowTrailingComma = true
        }
    }
}
