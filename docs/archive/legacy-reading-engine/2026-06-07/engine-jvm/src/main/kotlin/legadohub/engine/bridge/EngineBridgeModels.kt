package legadohub.engine.bridge

import kotlinx.serialization.Serializable

@Serializable
data class SourceParseSummary(
    val count: Int,
    val sources: List<SourceParseEntry>,
)

@Serializable
data class SourceParseEntry(
    val sourceId: String,
    val name: String,
    val group: String? = null,
    val enabled: Boolean,
    val enabledExplore: Boolean,
    val valid: Boolean,
    val invalidReason: String? = null,
)

@Serializable
data class BatchSearchCliRequest(
    val sourcesPath: String,
    val keyword: String,
    val page: Int = 1,
    val staticResponsesPath: String? = null,
    val batchSize: Int = 20,
    val globalConcurrency: Int = 20,
    val perHostConcurrency: Int = 2,
    val sourceTimeoutMs: Long = 8_000,
    val requestTimeoutMs: Long = 8_000,
    val overallTimeoutMs: Long = 30_000,
)

@Serializable
data class SourceSmokeSummary(
    val sourceId: String,
    val sourceName: String,
    val keyword: String,
    val search: SourceSmokeStage,
    val detail: SourceSmokeStage? = null,
    val toc: SourceSmokeStage? = null,
    val content: SourceSmokeStage? = null,
    val exploreKinds: SourceSmokeStage? = null,
    val explore: SourceSmokeStage? = null,
)

@Serializable
data class SourceSmokeStage(
    val ok: Boolean,
    val count: Int? = null,
    val title: String? = null,
    val url: String? = null,
    val sample: String? = null,
    val errorCode: String? = null,
    val message: String? = null,
    val elapsedMs: Long,
)
