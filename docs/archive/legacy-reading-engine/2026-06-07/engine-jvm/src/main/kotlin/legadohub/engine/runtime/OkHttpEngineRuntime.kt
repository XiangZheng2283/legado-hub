package legadohub.engine.runtime

import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.net.InetSocketAddress
import java.net.Proxy
import java.util.concurrent.TimeUnit

class OkHttpEngineRuntime(
    private val baseClient: OkHttpClient = OkHttpClient.Builder().build(),
) : EngineHttpRuntime {
    override suspend fun execute(request: EngineHttpRequestV2): EngineHttpResponseV2 {
        val client = baseClient.newBuilder()
            .readTimeout(request.timeoutMs ?: 30_000, TimeUnit.MILLISECONDS)
            .connectTimeout(request.timeoutMs ?: 30_000, TimeUnit.MILLISECONDS)
            .apply {
                request.proxy?.let { proxy(proxyFrom(it)) }
            }
            .build()
        val body = request.body?.toRequestBody(request.headers["Content-Type"]?.toMediaTypeOrNull())
        val httpRequest = Request.Builder()
            .url(request.url)
            .apply {
                request.headers.forEach { (key, value) -> header(key, value) }
                method(request.method.uppercase(), if (request.method.equals("GET", true)) null else body)
            }
            .build()
        val startedAt = System.currentTimeMillis()
        client.newCall(httpRequest).execute().use { response ->
            return EngineHttpResponseV2(
                statusCode = response.code,
                body = response.body?.string().orEmpty(),
                headers = response.headers.toMultimap(),
                finalUrl = response.request.url.toString(),
                elapsedMs = System.currentTimeMillis() - startedAt,
            )
        }
    }

    private fun proxyFrom(value: String): Proxy {
        val normalized = value.removePrefix("http://").removePrefix("https://")
        val host = normalized.substringBefore(":")
        val port = normalized.substringAfter(":", "7890").toInt()
        return Proxy(Proxy.Type.HTTP, InetSocketAddress(host, port))
    }
}

