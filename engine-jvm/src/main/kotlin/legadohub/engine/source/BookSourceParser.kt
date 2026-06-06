package legadohub.engine.source

import legadohub.engine.model.BookSource
import kotlinx.serialization.ExperimentalSerializationApi
import kotlinx.serialization.json.Json

class BookSourceParser(
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
            listOf(json.decodeFromString<BookSource>(trimmed))
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
