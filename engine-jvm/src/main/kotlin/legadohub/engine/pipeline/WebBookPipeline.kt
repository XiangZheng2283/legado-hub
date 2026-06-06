package legadohub.engine.pipeline

import legadohub.engine.model.BookSource
import legadohub.engine.model.EngineResult
import legadohub.engine.model.EngineStage
import legadohub.engine.model.SearchBook
import legadohub.engine.model.SearchRule
import legadohub.engine.model.TraceEvent
import legadohub.engine.model.UnsupportedCode
import legadohub.engine.model.UnsupportedReason
import legadohub.engine.rule.AnalyzeRuleInput
import legadohub.engine.rule.AnalyzeRuleParser
import legadohub.engine.runtime.EngineHttpRequest
import legadohub.engine.runtime.HttpRuntime
import legadohub.engine.url.AnalyzeHttpMethod
import legadohub.engine.url.AnalyzeUrlInput
import legadohub.engine.url.AnalyzeUrlParser
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.decodeFromJsonElement

class WebBookPipeline(
    private val httpRuntime: HttpRuntime,
    private val analyzeUrlParser: AnalyzeUrlParser = AnalyzeUrlParser(),
    private val analyzeRuleParser: AnalyzeRuleParser = AnalyzeRuleParser(),
    private val json: Json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        isLenient = true
    },
) {
    suspend fun search(source: BookSource, keyword: String, page: Int = 1): EngineResult<SearchBook> {
        val startedAt = System.currentTimeMillis()
        val trace = mutableListOf<TraceEvent>()
        val unsupported = mutableListOf<UnsupportedReason>()

        val searchUrl = source.searchUrl
        if (searchUrl.isNullOrBlank()) {
            return EngineResult(
                ok = false,
                trace = trace,
                unsupported = listOf(
                    UnsupportedReason(
                        code = UnsupportedCode.UnsupportedRuleSyntax,
                        message = "搜索 url 不能为空",
                        field = "searchUrl",
                    ),
                ),
                error = "searchUrl is blank",
                latencyMs = System.currentTimeMillis() - startedAt,
            )
        }

        val rule = decodeSearchRule(source)
        if (rule.bookList.isNullOrBlank()) {
            return EngineResult(
                ok = false,
                unsupported = listOf(
                    UnsupportedReason(
                        code = UnsupportedCode.UnsupportedRuleSyntax,
                        message = "搜索规则缺少 bookList",
                        field = "ruleSearch.bookList",
                    ),
                ),
                error = "ruleSearch.bookList is blank",
                latencyMs = System.currentTimeMillis() - startedAt,
            )
        }

        val analyzedUrl = analyzeUrlParser.parse(
            AnalyzeUrlInput(
                ruleUrl = searchUrl,
                key = keyword,
                page = page,
                baseUrl = source.bookSourceUrl,
                source = source,
            ),
        )
        unsupported += analyzedUrl.unsupported
        trace += TraceEvent(
            stage = EngineStage.Search,
            type = "url_analyzed",
            message = "搜索 URL 已解析",
            sourceId = source.sourceId,
            url = analyzedUrl.url,
            elapsedMs = System.currentTimeMillis() - startedAt,
        )

        if (unsupported.any { it.code == UnsupportedCode.WebViewRequired }) {
            return EngineResult(
                ok = false,
                trace = trace,
                unsupported = unsupported,
                error = "webview required",
                latencyMs = System.currentTimeMillis() - startedAt,
            )
        }

        val response = httpRuntime.execute(
            EngineHttpRequest(
                url = analyzedUrl.url,
                method = analyzedUrl.method.name,
                headers = analyzedUrl.headers,
                body = analyzedUrl.body,
                proxy = analyzedUrl.proxy,
                charset = analyzedUrl.charset,
            ),
        )
        trace += TraceEvent(
            stage = EngineStage.Search,
            type = "request_done",
            message = "搜索请求完成，HTTP ${response.statusCode}",
            sourceId = source.sourceId,
            url = response.finalUrl ?: analyzedUrl.url,
            elapsedMs = response.elapsedMs,
        )

        val body = response.body
        val containers = analyzeRuleParser.analyze(
            AnalyzeRuleInput(content = body, rule = rule.bookList),
        )
        unsupported += containers.unsupported
        val items = containers.values.mapNotNull { itemHtml ->
            parseSearchBook(itemHtml, rule, source, unsupported)
        }

        return EngineResult(
            ok = unsupported.none { it.code == UnsupportedCode.UnsupportedRuleSyntax } || items.isNotEmpty(),
            items = items,
            trace = trace,
            unsupported = unsupported,
            error = if (items.isEmpty()) "no search result" else null,
            latencyMs = System.currentTimeMillis() - startedAt,
        )
    }

    private fun decodeSearchRule(source: BookSource): SearchRule {
        val element = source.ruleSearch ?: return SearchRule()
        return json.decodeFromJsonElement<SearchRule>(element)
    }

    private fun parseSearchBook(
        itemHtml: String,
        rule: SearchRule,
        source: BookSource,
        unsupported: MutableList<UnsupportedReason>,
    ): SearchBook? {
        fun value(ruleText: String?): String {
            if (ruleText.isNullOrBlank()) return ""
            val result = analyzeRuleParser.analyze(AnalyzeRuleInput(content = itemHtml, rule = ruleText))
            unsupported += result.unsupported
            return result.first.orEmpty()
        }

        val name = value(rule.name)
        if (name.isBlank()) return null

        return SearchBook(
            name = name,
            author = value(rule.author),
            bookUrl = value(rule.bookUrl),
            intro = value(rule.intro),
            kind = value(rule.kind),
            lastChapter = value(rule.lastChapter),
            updateTime = value(rule.updateTime),
            coverUrl = value(rule.coverUrl),
            wordCount = value(rule.wordCount),
            sourceId = source.sourceId,
            sourceName = source.bookSourceName,
        )
    }
}
