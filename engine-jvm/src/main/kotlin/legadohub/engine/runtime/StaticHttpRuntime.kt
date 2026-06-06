package legadohub.engine.runtime

import java.util.Collections

class StaticHttpRuntime(
    private val responses: Map<String, String>,
) : EngineHttpRuntime {
    val requests: MutableList<EngineHttpRequestV2> = Collections.synchronizedList(mutableListOf())

    override suspend fun execute(request: EngineHttpRequestV2): EngineHttpResponseV2 {
        requests += request
        val body = responses[request.url]
            ?: responses[request.url.substringBefore("?")]
            ?: error("No static response for ${request.url}")
        return EngineHttpResponseV2(
            statusCode = 200,
            body = body,
            finalUrl = request.url,
        )
    }
}
