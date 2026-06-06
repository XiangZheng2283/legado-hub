package legadohub.engine.port

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.collections.shouldContain
import io.kotest.matchers.collections.shouldHaveSize
import io.kotest.matchers.shouldBe
import io.legado.app.data.entities.BookSource
import io.legado.app.data.entities.rule.BookInfoRule
import io.legado.app.data.entities.rule.ContentRule
import io.legado.app.data.entities.rule.ExploreRule
import io.legado.app.data.entities.rule.SearchRule
import io.legado.app.data.entities.rule.TocRule
import io.legado.app.model.webBook.WebBook
import kotlinx.coroutines.runBlocking
import legadohub.engine.runtime.EngineCookieStore
import legadohub.engine.runtime.EngineHttpRequestV2
import legadohub.engine.runtime.EngineHttpResponseV2
import legadohub.engine.runtime.EngineHttpRuntime
import legadohub.engine.runtime.EngineTraceEvent
import legadohub.engine.runtime.StaticHttpRuntime
import java.util.Collections

class WebBookPortTest : StringSpec({
    "ported WebBook chain supports search detail toc and content through runtime boundary" {
        val source = simpleSource()
        val runtime = StaticHttpRuntime(
            mapOf(
                "https://example.com/search?q=%E5%87%A1%E4%BA%BA" to """
                    <main>
                      <div class="book">
                        <a class="name" href="/book/1">凡人修仙传</a>
                        <span class="author">忘语</span>
                        <span class="last">第一章 山边小村</span>
                      </div>
                    </main>
                """.trimIndent(),
                "https://example.com/book/1" to """
                    <main>
                      <h1>凡人修仙传</h1>
                      <span class="author">忘语</span>
                      <a class="toc" href="/book/1/catalog">目录</a>
                    </main>
                """.trimIndent(),
                "https://example.com/book/1/catalog" to """
                    <main>
                      <div class="chapter"><a href="/book/1/1.html">第一章 山边小村</a></div>
                      <div class="chapter"><a href="/book/1/2.html">第二章 青衣老者</a></div>
                    </main>
                """.trimIndent(),
                "https://example.com/book/1/1.html" to """
                    <article>
                      <h1>第一章 山边小村</h1>
                      <div id="content">山边小村里，少年推开柴门。</div>
                    </article>
                """.trimIndent(),
            ),
        )
        val webBook = WebBook(runtime)

        val results = runBlocking { webBook.searchBookAwait(source, "凡人") }
        results shouldHaveSize 1
        results.first().name shouldBe "凡人修仙传"
        results.first().bookUrl shouldBe "https://example.com/book/1"

        val book = results.first().toBook()
        runBlocking { webBook.getBookInfoAwait(source, book) }
        book.author shouldBe "忘语"
        book.tocUrl shouldBe "https://example.com/book/1/catalog"

        val chapters = runBlocking { webBook.getChapterListAwait(source, book) }
        chapters shouldHaveSize 2
        chapters.first().title shouldBe "第一章 山边小村"

        val content = runBlocking { webBook.getContentAwait(source, book, chapters.first()) }
        content shouldBe "山边小村里，少年推开柴门。"
    }

    "ported WebBook routes java.ajax in source rules through runtime" {
        val source = simpleSource().copy(
            ruleSearch = simpleSource().getSearchRule().copy(
                author = "@js:java.ajax('https://example.com/author')",
            ),
        )
        val runtime = StaticHttpRuntime(
            mapOf(
                "https://example.com/search?q=%E5%87%A1%E4%BA%BA" to """
                    <main>
                      <div class="book">
                        <a class="name" href="/book/1">凡人修仙传</a>
                      </div>
                    </main>
                """.trimIndent(),
                "https://example.com/author" to "忘语",
            ),
        )

        val results = runBlocking { WebBook(runtime).searchBookAwait(source, "凡人") }

        results shouldHaveSize 1
        results.first().author shouldBe "忘语"
    }

    "ported WebBook executes @js searchUrl through AnalyzeUrl runtime" {
        val source = simpleSource().copy(
            searchUrl = "@js:baseUrl + '/js-search?q=' + java.encodeURI(key)",
        )
        val runtime = StaticHttpRuntime(
            mapOf(
                "https://example.com/js-search?q=%E5%87%A1%E4%BA%BA" to """
                    <main>
                      <div class="book">
                        <a class="name" href="/book/1">凡人修仙传</a>
                        <span class="author">忘语</span>
                      </div>
                    </main>
                """.trimIndent(),
            ),
        )

        val results = runBlocking { WebBook(runtime).searchBookAwait(source, "凡人") }

        results shouldHaveSize 1
        results.first().bookUrl shouldBe "https://example.com/book/1"
        results.first().author shouldBe "忘语"
    }

    "ported WebBook evaluates embedded searchUrl expressions as Reading AnalyzeUrl does" {
        val source = simpleSource().copy(
            searchUrl = "/embedded?q={{java.encodeURI(key)}}&p={{page}}",
        )
        val runtime = StaticHttpRuntime(
            mapOf(
                "https://example.com/embedded?q=%E5%87%A1%E4%BA%BA&p=2" to """
                    <main>
                      <div class="book">
                        <a class="name" href="/book/2">凡人修仙传 第二页</a>
                      </div>
                    </main>
                """.trimIndent(),
            ),
        )

        val results = runBlocking { WebBook(runtime).searchBookAwait(source, "凡人", page = 2) }

        results shouldHaveSize 1
        results.first().name shouldBe "凡人修仙传 第二页"
        results.first().bookUrl shouldBe "https://example.com/book/2"
    }

    "ported WebBook parses text explore kinds and executes explore book list rules" {
        val source = simpleSource().copy(
            exploreUrl = "热门::/rank?page={{page}}\n新书::/new",
            ruleExplore = ExploreRule(
                bookList = ".book",
                name = ".name@text",
                author = ".author@text",
                bookUrl = ".name@href",
                coverUrl = ".cover@src",
            ),
        )
        val runtime = StaticHttpRuntime(
            mapOf(
                "https://example.com/rank?page=2" to """
                    <main>
                      <div class="book">
                        <a class="name" href="/book/9">排行榜小说</a>
                        <span class="author">作者甲</span>
                        <img class="cover" src="/covers/9.jpg" />
                      </div>
                    </main>
                """.trimIndent(),
            ),
        )
        val webBook = WebBook(runtime)

        val kinds = webBook.exploreKinds(source)
        kinds shouldHaveSize 2
        kinds.first().title shouldBe "热门"
        kinds.first().url shouldBe "/rank?page={{page}}"

        val results = runBlocking { webBook.exploreBookAwait(source, kinds.first().url!!, page = 2) }

        results shouldHaveSize 1
        results.first().name shouldBe "排行榜小说"
        results.first().author shouldBe "作者甲"
        results.first().bookUrl shouldBe "https://example.com/book/9"
        results.first().coverUrl shouldBe "https://example.com/covers/9.jpg"
    }

    "ported WebBook parses JSON explore kinds" {
        val source = simpleSource().copy(
            exploreUrl = """[{"title":"完本","url":"/complete","type":"url"},{"title":"筛选","type":"select","chars":["男频","女频"],"default":"男频"}]""",
        )
        val kinds = WebBook(StaticHttpRuntime(emptyMap())).exploreKinds(source)

        kinds shouldHaveSize 2
        kinds[0].title shouldBe "完本"
        kinds[0].url shouldBe "/complete"
        kinds[1].type shouldBe "select"
        kinds[1].chars shouldBe listOf("男频", "女频")
        kinds[1].default shouldBe "男频"
    }

    "ported WebBook accepts trailing commas in JSON explore kinds" {
        val source = simpleSource().copy(
            exploreUrl = """[{"title":"完本","url":"/complete",},]""",
        )

        val kinds = WebBook(StaticHttpRuntime(emptyMap())).exploreKinds(source)

        kinds shouldHaveSize 1
        kinds.first().title shouldBe "完本"
        kinds.first().url shouldBe "/complete"
    }

    "ported WebBook emits request and parse trace events" {
        val source = simpleSource()
        val runtime = StaticHttpRuntime(
            mapOf(
                "https://example.com/search?q=%E5%87%A1%E4%BA%BA" to """
                    <main>
                      <div class="book">
                        <a class="name" href="/book/1">凡人修仙传</a>
                        <span class="author">忘语</span>
                      </div>
                    </main>
                """.trimIndent(),
            ),
        )
        val traces = mutableListOf<EngineTraceEvent>()

        val results = runBlocking {
            WebBook(
                runtime = runtime,
                onTrace = { trace -> traces += trace },
            ).searchBookAwait(source, "凡人")
        }

        results shouldHaveSize 1
        traces.map { it.type } shouldContain "request_started"
        traces.map { it.type } shouldContain "request_finished"
        traces.map { it.type } shouldContain "parse_started"
        traces.map { it.type } shouldContain "parse_finished"
        traces.last().stage shouldBe "search.parse"
        traces.last().message shouldBe "results=1"
    }

    "ported WebBook attaches stored cookies and records response cookies for main requests" {
        val source = simpleSource()
        val requests = Collections.synchronizedList(mutableListOf<EngineHttpRequestV2>())
        val runtime = object : EngineHttpRuntime {
            override suspend fun execute(request: EngineHttpRequestV2): EngineHttpResponseV2 {
                requests += request
                return EngineHttpResponseV2(
                    statusCode = 200,
                    body = """
                        <main>
                          <div class="book">
                            <a class="name" href="/book/1">凡人修仙传</a>
                            <span class="author">忘语</span>
                          </div>
                        </main>
                    """.trimIndent(),
                    headers = mapOf("Set-Cookie" to listOf("sid=next; Path=/")),
                    finalUrl = request.url,
                )
            }
        }
        val cookieStore = TestCookieStore().apply {
            seed("https://example.com", "https://example.com/search?q=%E5%87%A1%E4%BA%BA", "sid=old")
        }

        val results = runBlocking {
            WebBook(runtime, cookieStore).searchBookAwait(source, "凡人")
        }

        results shouldHaveSize 1
        requests.single().headers["Cookie"] shouldBe "sid=old"
        cookieStore.saved("https://example.com", "https://example.com/search?q=%E5%87%A1%E4%BA%BA") shouldBe
            "sid=next; Path=/"
    }

    "ported WebBook follows nextTocUrl pages and reindexes chapters" {
        val source = simpleSource().copy(
            ruleToc = simpleSource().getTocRule().copy(
                nextTocUrl = ".next@href",
                formatJs = "index + '. ' + title",
            ),
        )
        val book = io.legado.app.data.entities.Book(
            name = "凡人修仙传",
            bookUrl = "https://example.com/book/1",
            tocUrl = "https://example.com/book/1/catalog",
        )
        val runtime = StaticHttpRuntime(
            mapOf(
                "https://example.com/book/1/catalog" to """
                    <main>
                      <div class="chapter"><a href="/book/1/1.html">第一章 山边小村</a></div>
                      <a class="next" href="/book/1/catalog?page=2">下一页</a>
                    </main>
                """.trimIndent(),
                "https://example.com/book/1/catalog?page=2" to """
                    <main>
                      <div class="chapter"><a href="/book/1/2.html">第二章 青衣老者</a></div>
                    </main>
                """.trimIndent(),
            ),
        )

        val chapters = runBlocking { WebBook(runtime).getChapterListAwait(source, book) }

        chapters shouldHaveSize 2
        chapters[0].index shouldBe 0
        chapters[1].index shouldBe 1
        chapters[0].title shouldBe "1. 第一章 山边小村"
        chapters[1].title shouldBe "2. 第二章 青衣老者"
        chapters[1].url shouldBe "https://example.com/book/1/2.html"
    }

    "ported WebBook follows nextContentUrl pages and applies replaceRegex after merge" {
        val source = simpleSource().copy(
            ruleContent = simpleSource().getContentRule().copy(
                nextContentUrl = ".next@href",
                replaceRegex = "## 广告",
            ),
        )
        val book = io.legado.app.data.entities.Book(
            name = "凡人修仙传",
            bookUrl = "https://example.com/book/1",
        )
        val chapter = io.legado.app.data.entities.BookChapter(
            title = "第一章 山边小村",
            url = "https://example.com/book/1/1.html",
        )
        val runtime = StaticHttpRuntime(
            mapOf(
                "https://example.com/book/1/1.html" to """
                    <article>
                      <h1>第一章 山边小村</h1>
                      <div id="content">第一段 广告</div>
                      <a class="next" href="/book/1/1_2.html">下一页</a>
                    </article>
                """.trimIndent(),
                "https://example.com/book/1/1_2.html" to """
                    <article>
                      <div id="content">第二段 广告</div>
                    </article>
                """.trimIndent(),
            ),
        )

        val content = runBlocking { WebBook(runtime).getContentAwait(source, book, chapter) }

        content shouldBe "第一段\n第二段"
    }
})

private fun simpleSource(): BookSource =
    BookSource(
        bookSourceName = "测试源",
        bookSourceUrl = "https://example.com",
        searchUrl = "/search?q={{key}}",
        ruleSearch = SearchRule(
            bookList = ".book",
            name = ".name@text",
            author = ".author@text",
            bookUrl = ".name@href",
            lastChapter = ".last@text",
        ),
        ruleBookInfo = BookInfoRule(
            name = "h1@text",
            author = ".author@text",
            tocUrl = ".toc@href",
        ),
        ruleToc = TocRule(
            chapterList = ".chapter",
            chapterName = "a@text",
            chapterUrl = "a@href",
        ),
        ruleContent = ContentRule(
            title = "h1@text",
            content = "#content@text",
        ),
    )

private class TestCookieStore : EngineCookieStore {
    private val values = mutableMapOf<Pair<String, String>, String>()

    fun seed(sourceId: String, url: String, cookie: String) {
        values[sourceId to url] = cookie
    }

    fun saved(sourceId: String, url: String): String? =
        values[sourceId to url]

    override suspend fun get(sourceId: String, url: String): String? =
        values[sourceId to url]

    override suspend fun put(sourceId: String, url: String, cookie: String) {
        values[sourceId to url] = cookie
    }

    override suspend fun remove(sourceId: String, url: String) {
        values.remove(sourceId to url)
    }
}
