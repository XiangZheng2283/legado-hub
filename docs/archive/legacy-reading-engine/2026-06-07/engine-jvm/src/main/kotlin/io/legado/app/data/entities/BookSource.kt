package io.legado.app.data.entities

import io.legado.app.data.entities.rule.BookInfoRule
import io.legado.app.data.entities.rule.ContentRule
import io.legado.app.data.entities.rule.ExploreRule
import io.legado.app.data.entities.rule.ReviewRule
import io.legado.app.data.entities.rule.SearchRule
import io.legado.app.data.entities.rule.TocRule
import kotlinx.serialization.Serializable

/**
 * JVM port of Reading's BookSource model.
 *
 * Room, Parcelable, and Android annotations are removed. Field names and core
 * identity behavior are preserved.
 */
@Serializable
data class BookSource(
    var bookSourceUrl: String = "",
    var bookSourceName: String = "",
    var bookSourceGroup: String? = null,
    var bookSourceType: Int = 0,
    var bookUrlPattern: String? = null,
    var customOrder: Int = 0,
    var enabled: Boolean = true,
    var enabledExplore: Boolean = true,
    override var jsLib: String? = null,
    override var enabledCookieJar: Boolean? = true,
    override var concurrentRate: String? = null,
    override var header: String? = null,
    override var loginUrl: String? = null,
    override var loginUi: String? = null,
    var loginCheckJs: String? = null,
    var coverDecodeJs: String? = null,
    var bookSourceComment: String? = null,
    var variableComment: String? = null,
    var lastUpdateTime: Long = 0,
    var respondTime: Long = 180000L,
    var weight: Int = 0,
    var exploreUrl: String? = null,
    var exploreScreen: String? = null,
    var ruleExplore: ExploreRule? = null,
    var searchUrl: String? = null,
    var ruleSearch: SearchRule? = null,
    var ruleBookInfo: BookInfoRule? = null,
    var ruleToc: TocRule? = null,
    var ruleContent: ContentRule? = null,
    var ruleReview: ReviewRule? = null,
    var eventListener: Boolean = false,
    var customButton: Boolean = false,
) : BaseSource {
    override fun getTag(): String = bookSourceName

    override fun getKey(): String = bookSourceUrl

    override fun hashCode(): Int = bookSourceUrl.hashCode()

    override fun equals(other: Any?): Boolean =
        other is BookSource && other.bookSourceUrl == bookSourceUrl

    fun getSearchRule(): SearchRule =
        ruleSearch ?: SearchRule().also { ruleSearch = it }

    fun getExploreRule(): ExploreRule =
        ruleExplore ?: ExploreRule().also { ruleExplore = it }

    fun getBookInfoRule(): BookInfoRule =
        ruleBookInfo ?: BookInfoRule().also { ruleBookInfo = it }

    fun getTocRule(): TocRule =
        ruleToc ?: TocRule().also { ruleToc = it }

    fun getContentRule(): ContentRule =
        ruleContent ?: ContentRule().also { ruleContent = it }

    fun getDisPlayNameGroup(): String =
        if (bookSourceGroup.isNullOrBlank()) {
            bookSourceName
        } else {
            "$bookSourceName ($bookSourceGroup)"
        }

    fun addGroup(groups: String): BookSource {
        val nextGroups = groupSet()
        nextGroups.addAll(splitGroups(groups))
        bookSourceGroup = nextGroups.joinToString(",")
        return this
    }

    fun removeGroup(groups: String): BookSource {
        val remove = splitGroups(groups).toSet()
        bookSourceGroup = groupSet().filterNot { it in remove }.joinToString(",")
        return this
    }

    fun hasGroup(group: String): Boolean =
        group in groupSet()

    fun removeInvalidGroups() {
        removeGroup(getInvalidGroupNames())
    }

    fun removeErrorComment() {
        bookSourceComment = bookSourceComment
            ?.split("\n\n")
            ?.filterNot { it.startsWith("// Error: ") }
            ?.joinToString("\n")
    }

    fun addErrorComment(e: Throwable) {
        bookSourceComment = "// Error: ${e.localizedMessage}" +
            if (bookSourceComment.isNullOrBlank()) "" else "\n\n$bookSourceComment"
    }

    fun getCheckKeyword(default: String): String {
        ruleSearch?.checkKeyWord?.let {
            if (it.isNotBlank() && !it.contains("http") && !it.contains("::") &&
                !it.contains("++") && !it.contains("--")
            ) {
                return it
            }
        }
        return default
    }

    fun getInvalidGroupNames(): String =
        groupSet().filter { "失效" in it || it == "校验超时" }.joinToString()

    fun getDisplayVariableComment(otherComment: String): String =
        if (variableComment.isNullOrBlank()) otherComment else "$variableComment\n$otherComment"

    fun equal(source: BookSource): Boolean =
        equal(bookSourceName, source.bookSourceName) &&
            equal(bookSourceUrl, source.bookSourceUrl) &&
            equal(bookSourceGroup, source.bookSourceGroup) &&
            bookSourceType == source.bookSourceType &&
            equal(bookUrlPattern, source.bookUrlPattern) &&
            equal(bookSourceComment, source.bookSourceComment) &&
            customOrder == source.customOrder &&
            enabled == source.enabled &&
            enabledExplore == source.enabledExplore &&
            enabledCookieJar == source.enabledCookieJar &&
            equal(variableComment, source.variableComment) &&
            equal(concurrentRate, source.concurrentRate) &&
            equal(jsLib, source.jsLib) &&
            equal(header, source.header) &&
            equal(loginUrl, source.loginUrl) &&
            equal(loginUi, source.loginUi) &&
            equal(loginCheckJs, source.loginCheckJs) &&
            equal(coverDecodeJs, source.coverDecodeJs) &&
            equal(exploreUrl, source.exploreUrl) &&
            equal(searchUrl, source.searchUrl) &&
            getSearchRule() == source.getSearchRule() &&
            getExploreRule() == source.getExploreRule() &&
            getBookInfoRule() == source.getBookInfoRule() &&
            getTocRule() == source.getTocRule() &&
            getContentRule() == source.getContentRule()

    private fun groupSet(): LinkedHashSet<String> =
        splitGroups(bookSourceGroup).toCollection(LinkedHashSet())

    private fun splitGroups(groups: String?): List<String> =
        groups
            ?.split(",", ";", "，", "；")
            ?.map { it.trim() }
            ?.filter { it.isNotEmpty() }
            .orEmpty()

    private fun equal(a: String?, b: String?): Boolean =
        a == b || (a.isNullOrEmpty() && b.isNullOrEmpty())
}
