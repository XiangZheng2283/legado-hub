package io.legado.app.help

import io.legado.app.data.entities.BaseSource
import kotlinx.coroutines.delay
import java.util.concurrent.ConcurrentHashMap

class ConcurrentRateLimiter(private val source: BaseSource?) {
    suspend fun <T> withLimit(block: suspend () -> T): T {
        getConcurrentRecord()
        return block()
    }

    private suspend fun getConcurrentRecord(): ConcurrentRecord? {
        while (true) {
            val waitTime = fetchWaitTime() ?: return null
            if (waitTime == 0L) return records[sourceKey()]
            delay(waitTime)
        }
    }

    private fun fetchWaitTime(): Long? {
        val rate = source?.concurrentRate?.trim().orEmpty()
        if (rate.isBlank() || rate == "0") return null
        val key = sourceKey()
        var isNewRecord = false
        val record = records.computeIfAbsent(key) {
            isNewRecord = true
            parseRate(rate)
        }
        if (isNewRecord) return 0
        synchronized(record) {
            val nextTime = record.time + record.intervalMs
            val now = System.currentTimeMillis()
            if (now >= nextTime) {
                record.time = now
                record.frequency = 1
                return 0
            }
            if (record.frequency < record.accessLimit) {
                record.frequency += 1
                return 0
            }
            return nextTime - now
        }
    }

    private fun sourceKey(): String =
        source?.getKey().orEmpty()

    private fun parseRate(rate: String): ConcurrentRecord {
        val separator = rate.indexOf("/")
        return if (separator > 0) {
            ConcurrentRecord(
                time = System.currentTimeMillis(),
                accessLimit = rate.take(separator).toIntOrNull()?.coerceAtLeast(1) ?: 1,
                intervalMs = rate.substring(separator + 1).toLongOrNull()?.coerceAtLeast(0) ?: 0,
                frequency = 1,
            )
        } else {
            ConcurrentRecord(
                time = System.currentTimeMillis(),
                accessLimit = 1,
                intervalMs = rate.toLongOrNull()?.coerceAtLeast(0) ?: 0,
                frequency = 1,
            )
        }
    }

    companion object {
        private val records = ConcurrentHashMap<String, ConcurrentRecord>()

        fun clear(sourceKey: String? = null) {
            if (sourceKey == null) records.clear() else records.remove(sourceKey)
        }
    }
}

data class ConcurrentRecord(
    var time: Long,
    val accessLimit: Int,
    val intervalMs: Long,
    var frequency: Int,
)
