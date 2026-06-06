package legadohub.engine.rule

import legadohub.engine.model.UnsupportedReason

data class AnalyzeRuleInput(
    val content: String,
    val rule: String,
    val baseUrl: String = "",
    val variables: Map<String, String> = emptyMap(),
)

data class AnalyzeRuleResult(
    val values: List<String>,
    val unsupported: List<UnsupportedReason> = emptyList(),
) {
    val first: String?
        get() = values.firstOrNull()
}
