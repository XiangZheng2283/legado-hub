package legadohub.engine.port

import io.kotest.core.spec.style.StringSpec
import io.kotest.matchers.collections.shouldContainExactly
import io.kotest.matchers.shouldBe
import io.legado.app.data.entities.Book
import io.legado.app.data.entities.BookSource
import io.legado.app.help.ConcurrentRateLimiter
import io.legado.app.model.analyzeRule.AnalyzeRule
import legadohub.engine.runtime.EngineCookieStore
import legadohub.engine.runtime.EngineHttpRequestV2
import legadohub.engine.runtime.EngineHttpResponseV2
import legadohub.engine.runtime.EngineHttpRuntime
import legadohub.engine.runtime.StaticHttpRuntime
import org.jsoup.nodes.Element
import java.util.Collections
import kotlin.math.abs

class AnalyzeRulePortTest : StringSpec({
    "ported AnalyzeRule extracts CSS text html and attributes" {
        val rule = AnalyzeRule().setContent(
            """
            <main>
              <a class="name" href="/book/1">凡人修仙传</a>
              <div class="intro"><b>山村少年</b></div>
            </main>
            """.trimIndent(),
            "https://example.com/search",
        )

        rule.getString(".name@text") shouldBe "凡人修仙传"
        rule.getString(".intro@html") shouldBe "<b>山村少年</b>"
        rule.getString(".name@href", isUrl = true) shouldBe "https://example.com/book/1"
    }

    "ported AnalyzeRule extracts XPath text and attributes" {
        val rule = AnalyzeRule().setContent(
            """
            <main>
              <h1>凡人修仙传</h1>
              <a href="/book/1">详情</a>
            </main>
            """.trimIndent(),
        )

        rule.getString("xpath://h1/text()") shouldBe "凡人修仙传"
        rule.getString("xpath://a/@href") shouldBe "/book/1"
    }

    "ported AnalyzeRule extracts JsonPath values" {
        val rule = AnalyzeRule().setContent(
            """
            {
              "books": [
                {"name": "凡人修仙传"},
                {"name": "魔天记"}
              ]
            }
            """.trimIndent(),
        )

        rule.getStringList("$.books[*].name") shouldContainExactly listOf("凡人修仙传", "魔天记")
    }

    "ported AnalyzeRule applies fallback to JsonPath element rules" {
        val rule = AnalyzeRule().setContent(
            """
            {
              "data": [
                {"name": "凡人修仙传"},
                {"name": "魔天记"}
              ]
            }
            """.trimIndent(),
        )

        val elements = rule.getElements("$.missing||$.data")

        elements.size shouldBe 2
    }

    "ported AnalyzeRule extracts regex capture groups" {
        val rule = AnalyzeRule().setContent("作者：忘语")

        rule.getString("regex:作者：(.*)") shouldBe "忘语"
    }

    "ported AnalyzeRule supports fallback and replace" {
        val rule = AnalyzeRule().setContent(
            """
            <main>
              <span class="title">凡人修仙传 最新章节</span>
            </main>
            """.trimIndent(),
        )

        rule.getString(".missing@text || .title@text## 最新章节##") shouldBe "凡人修仙传"
    }

    "ported AnalyzeRule evaluates JS through Rhino with java helpers" {
        val rule = AnalyzeRule().setContent("<main></main>")

        rule.getString("@js:java.base64Decode(java.base64Encode('凡人'))") shouldBe "凡人"
        rule.getString("@js:java.md5('abc')") shouldBe "900150983cd24fb0d6963f7d28e17f72"
    }

    "ported AnalyzeRule supports chained js before selector rules" {
        val rule = AnalyzeRule().setContent("<main><div class=\"book\"><a>凡人修仙传</a></div></main>")

        rule.getString("<js>result</js>.book@text") shouldBe "凡人修仙传"
        rule.getElements("<js>result</js>.book").size shouldBe 1
    }

    "ported AnalyzeRule supports pure js element list rules" {
        val rule = AnalyzeRule().setContent("<main><div class=\"book\">凡人修仙传</div></main>")

        val elements = rule.getElements("<js>java.getElement('.book')</js>")

        elements.size shouldBe 1
        (elements.first() as Element).className() shouldBe "book"
        (elements.first() as Element).text() shouldBe "凡人修仙传"
    }

    "ported AnalyzeRule supports selector result passed into js rules" {
        val rule = AnalyzeRule().setContent(
            """
            <main>
              <a data-bid="123">凡人修仙传</a>
            </main>
            """.trimIndent(),
        )

        rule.getString("a@data-bid@js:'https://m.qidian.com/book/' + result + '/'") shouldBe
            "https://m.qidian.com/book/123/"
        rule.getString("a@text@js:result[0] + ':' + result.length") shouldBe "凡:5"
    }

    "ported AnalyzeRule evaluates common Reading JS helpers" {
        val rule = AnalyzeRule().setContent("<main>正文</main>", "https://example.com/book/1")

        rule.getString("@js:java.hexDecodeToString(java.hexEncodeToString('凡人'))") shouldBe "凡人"
        rule.getString("@js:java.encodeURI('凡人 修仙')") shouldBe "%E5%87%A1%E4%BA%BA%20%E4%BF%AE%E4%BB%99"
        rule.getString("@js:java.timeFormatUTC(0,'yyyy-MM-dd',8)") shouldBe "1970-01-01"
        rule.getString("@js:java.put('k','v');java.get('k')") shouldBe "v"
        rule.getString("@js:baseUrl") shouldBe "https://example.com/book/1"
        rule.getString("@js:String(src).indexOf('正文') >= 0 ? 'yes' : 'no'") shouldBe "yes"
        rule.getString("@js:java.t2s('繁體小說')") shouldBe "繁体小说"
        rule.getString("@js:java.s2t('繁体小说')") shouldBe "繁體小說"
    }

    "ported AnalyzeRule evaluates Reading symmetric crypto helpers" {
        val rule = AnalyzeRule().setContent("<main></main>")

        rule.getString(
            "@js:" +
                "enc=java.desEncodeToBase64String('凡人','6CB1E21E','DES/CBC/PKCS5Padding','1F0FB845');" +
                "java.aesBase64DecodeToString(enc,'6CB1E21E','DES/CBC/PKCS5Padding','1F0FB845')",
        ) shouldBe "凡人"

        rule.getString(
            "@js:" +
                "enc=java.aesEncodeToBase64String('凡人修仙','1234567890123456','AES/CBC/PKCS5Padding','6543210987654321');" +
                "java.aesBase64DecodeToString(enc,'1234567890123456','AES/CBC/PKCS5Padding','6543210987654321')",
        ) shouldBe "凡人修仙"
    }

    "ported AnalyzeRule exposes book variables and special keys to JS" {
        val book = Book(name = "凡人修仙传").apply {
            putVariable("custom", "source-1")
        }
        val rule = AnalyzeRule(book).setContent("<main></main>")

        rule.getString("@js:java.get('bookName')") shouldBe "凡人修仙传"
        rule.getString("@js:java.get('custom')") shouldBe "source-1"
        rule.getString("@js:java.put('custom','source-2');java.get('custom')") shouldBe "source-2"
    }

    "ported AnalyzeRule exposes source variable helpers to JS" {
        val source = io.legado.app.data.entities.BookSource(
            bookSourceName = "测试源",
            bookSourceUrl = "https://example.com/source-variable",
        )
        val rule = AnalyzeRule(source = source).setContent("<main></main>")

        rule.getString("@js:source.setVariable(2);source.getVariable()") shouldBe "2"
        rule.getString("@js:source.put('token','abc');source.get('token')") shouldBe "abc"
        rule.getString("@js:source.putVariable(null);String(source.getVariable()) === '' ? 'empty' : 'not-empty'") shouldBe "empty"
    }

    "ported AnalyzeRule exposes selector helpers inside JS" {
        val rule = AnalyzeRule().setContent(
            """
            <main>
              <a class="chapter" href="/1">第一章</a>
              <a class="chapter" href="/2">第二章</a>
            </main>
            """.trimIndent(),
            "https://example.com/book/",
        )

        rule.getString("@js:java.getString('.chapter@text')") shouldBe "第一章\n第二章"
        rule.getString("@js:java.getElement('.chapter').length") shouldBe "2"
        rule.getString("@js:java.getElement('.chapter').toArray()[1].text()") shouldBe "第二章"
        rule.getString("@js:java.getElement('.chapter').toArray()[0].attr('href')") shouldBe "/1"
        rule.getString(
            "@js:" +
                "java.setContent('<main><span class=\"next\">新正文</span></main>');" +
                "java.getString('.next@text')",
        ) shouldBe "新正文"
    }

    "ported AnalyzeRule returns empty element list to JS for missing selectors" {
        val rule = AnalyzeRule().setContent("<main></main>")

        rule.getString("@js:java.getElement('.missing').length") shouldBe "0"
    }

    "ported AnalyzeRule exposes java.ajax as structured unsupported text" {
        val rule = AnalyzeRule().setContent("<main></main>")

        rule.getString("@js:java.ajax('https://example.com')") shouldBe "UNSUPPORTED:java.ajax:https://example.com"
    }

    "ported AnalyzeRule routes java.ajax through injected HTTP runtime" {
        val runtime = StaticHttpRuntime(
            mapOf("https://example.com/api" to """{"name":"凡人修仙传"}"""),
        )
        val rule = AnalyzeRule(httpRuntime = runtime).setContent("<main></main>")

        rule.getString("@js:java.ajax('https://example.com/api')") shouldBe """{"name":"凡人修仙传"}"""
    }

    "ported AnalyzeRule maps java.ajax object headers body and method into HTTP request" {
        val runtime = StaticHttpRuntime(
            mapOf("https://example.com/api" to "ok"),
        )
        val rule = AnalyzeRule(httpRuntime = runtime).setContent("<main></main>")

        rule.getString(
            "@js:java.ajax({" +
                "url:'https://example.com/api'," +
                "method:'POST'," +
                "headers:{'X-Test':'yes','Content-Type':'text/plain'}," +
                "body:'q=凡人'," +
                "timeoutMs:1500" +
                "})",
        ) shouldBe "ok"

        runtime.requests.last() shouldBe EngineHttpRequestV2(
            sourceId = "AnalyzeRule",
            url = "https://example.com/api",
            method = "POST",
            headers = mapOf("X-Test" to "yes", "Content-Type" to "text/plain"),
            body = "q=凡人",
            timeoutMs = 1500,
        )
    }

    "ported AnalyzeRule exposes java.ajax timeout overload" {
        val runtime = StaticHttpRuntime(
            mapOf("https://example.com/slow" to "slow-ok"),
        )
        val rule = AnalyzeRule(httpRuntime = runtime).setContent("<main></main>")

        rule.getString("@js:java.ajax('https://example.com/slow', 2500)") shouldBe "slow-ok"

        runtime.requests.last().timeoutMs shouldBe 2500
    }

    "ported AnalyzeRule exposes java.ajaxAll response wrappers" {
        val runtime = StaticHttpRuntime(
            mapOf(
                "https://example.com/a" to "A",
                "https://example.com/b" to "B",
            ),
        )
        val rule = AnalyzeRule(httpRuntime = runtime).setContent("<main></main>")

        rule.getString(
            "@js:" +
                "var res = java.ajaxAll(['https://example.com/a','https://example.com/b']);" +
                "res[0].body() + '|' + res[1].body() + '|' + res[0].statusCode()",
        ) shouldBe "A|B|200"

        runtime.requests.map { it.url } shouldContainExactly listOf(
            "https://example.com/a",
            "https://example.com/b",
        )
    }

    "ported AnalyzeRule maps java.ajaxAll object requests" {
        val requests = Collections.synchronizedList(mutableListOf<EngineHttpRequestV2>())
        val runtime = object : EngineHttpRuntime {
            override suspend fun execute(request: EngineHttpRequestV2): EngineHttpResponseV2 {
                requests += request
                return EngineHttpResponseV2(
                    statusCode = 200,
                    body = "ok:${request.method}:${request.body.orEmpty()}",
                    headers = mapOf("X-Result" to listOf(request.headers["X-Test"].orEmpty())),
                    finalUrl = request.url,
                )
            }
        }
        val rule = AnalyzeRule(httpRuntime = runtime).setContent("<main></main>")

        rule.getString(
            "@js:" +
                "var res = java.ajaxAll([" +
                "{url:'https://example.com/a', method:'POST', headers:{'X-Test':'one'}, body:'p=1'}," +
                "{url:'https://example.com/b', method:'HEAD', headers:{'X-Test':'two'}}" +
                "]);" +
                "res[0].body() + '|' + res[1].header('X-Result')",
        ) shouldBe "ok:POST:p=1|two"

        requests[0].method shouldBe "POST"
        requests[0].body shouldBe "p=1"
        requests[0].headers["X-Test"] shouldBe "one"
        requests[1].method shouldBe "HEAD"
        requests[1].headers["X-Test"] shouldBe "two"
    }

    "ported AnalyzeRule exposes ajaxTestAll with timeout" {
        val runtime = StaticHttpRuntime(
            mapOf(
                "https://example.com/a" to "A",
                "https://example.com/b" to "B",
            ),
        )
        val rule = AnalyzeRule(httpRuntime = runtime).setContent("<main></main>")

        rule.getString(
            "@js:" +
                "var res = java.ajaxTestAll(['https://example.com/a','https://example.com/b'], 3200);" +
                "res[0].body() + res[1].body()",
        ) shouldBe "AB"

        runtime.requests.map { it.timeoutMs } shouldContainExactly listOf(3200, 3200)
    }

    "ported AnalyzeRule applies and skips source concurrentRate for ajaxAll" {
        val source = BookSource(
            bookSourceName = "限速源",
            bookSourceUrl = "https://rate.example",
            concurrentRate = "1/120",
        )
        val startedAt = Collections.synchronizedList(mutableListOf<Long>())
        val runtime = object : EngineHttpRuntime {
            override suspend fun execute(request: EngineHttpRequestV2): EngineHttpResponseV2 {
                startedAt += System.currentTimeMillis()
                return EngineHttpResponseV2(statusCode = 200, body = request.url.substringAfterLast("/"), finalUrl = request.url)
            }
        }
        val rule = AnalyzeRule(source = source, httpRuntime = runtime).setContent("<main></main>")

        ConcurrentRateLimiter.clear(source.bookSourceUrl)
        rule.getString(
            "@js:" +
                "var res = java.ajaxAll(['https://rate.example/a','https://rate.example/b']);" +
                "res[0].body() + res[1].body()",
        ) shouldBe "ab"
        val limitedGap = abs(startedAt[1] - startedAt[0])
        (limitedGap >= 80) shouldBe true

        startedAt.clear()
        ConcurrentRateLimiter.clear(source.bookSourceUrl)
        rule.getString(
            "@js:" +
                "var res = java.ajaxAll(['https://rate.example/a','https://rate.example/b'], true);" +
                "res[0].body() + res[1].body()",
        ) shouldBe "ab"
        val skippedGap = abs(startedAt[1] - startedAt[0])
        (skippedGap < 80) shouldBe true
    }

    "ported AnalyzeRule exposes connect and StrResponse-like wrapper helpers" {
        val requests = Collections.synchronizedList(mutableListOf<EngineHttpRequestV2>())
        val runtime = object : EngineHttpRuntime {
            override suspend fun execute(request: EngineHttpRequestV2): EngineHttpResponseV2 {
                requests += request
                return EngineHttpResponseV2(
                    statusCode = 202,
                    body = "connected",
                    headers = mapOf(
                        "Location" to listOf("/next"),
                        "Set-Cookie" to listOf("sid=abc; Path=/"),
                    ),
                    finalUrl = request.url,
                    elapsedMs = 17,
                )
            }
        }
        val rule = AnalyzeRule(httpRuntime = runtime).setContent("<main></main>")

        rule.getString(
            "@js:" +
                "var res = java.connect('https://example.com/connect', '{\"X-Test\":\"yes\"}', 4100);" +
                "res.body() + '|' + res.code() + '|' + res.statusCode() + '|' +" +
                "res.header('Location') + '|' + res.headers().get('Location').get(0) + '|' +" +
                "res.cookie('sid') + '|' + res.isSuccessful() + '|' + res.callTime() + '|' + res.url()",
        ) shouldBe "connected|202|202|/next|/next|abc|true|17|https://example.com/connect"

        requests.single().headers["X-Test"] shouldBe "yes"
        requests.single().timeoutMs shouldBe 4100
    }

    "ported AnalyzeRule attaches stored cookies and records Set-Cookie from java.ajax" {
        val requests = Collections.synchronizedList(mutableListOf<EngineHttpRequestV2>())
        val runtime = object : EngineHttpRuntime {
            override suspend fun execute(request: EngineHttpRequestV2): EngineHttpResponseV2 {
                requests += request
                return EngineHttpResponseV2(
                    statusCode = 200,
                    body = "cookie-ok",
                    headers = mapOf("Set-Cookie" to listOf("sid=next; Path=/")),
                    finalUrl = request.url,
                )
            }
        }
        val cookieStore = InMemoryCookieStore().apply {
            seed("AnalyzeRule", "https://example.com/api", "sid=old")
        }
        val rule = AnalyzeRule(
            httpRuntime = runtime,
            cookieStore = cookieStore,
        ).setContent("<main></main>")

        rule.getString("@js:java.ajax('https://example.com/api')") shouldBe "cookie-ok"

        requests.last().headers["Cookie"] shouldBe "sid=old"
        cookieStore.saved("AnalyzeRule", "https://example.com/api") shouldBe "sid=next; Path=/"
    }

    "ported AnalyzeRule exposes java get post head response wrappers through runtime" {
        val requests = Collections.synchronizedList(mutableListOf<EngineHttpRequestV2>())
        val runtime = object : EngineHttpRuntime {
            override suspend fun execute(request: EngineHttpRequestV2): EngineHttpResponseV2 {
                requests += request
                return EngineHttpResponseV2(
                    statusCode = 200,
                    body = "wrapped:${request.method}:${request.body.orEmpty()}",
                    headers = mapOf(
                        "Location" to listOf("/next"),
                        "Set-Cookie" to listOf("PHPSESSID=abc; Path=/"),
                    ),
                    finalUrl = request.url,
                )
            }
        }
        val rule = AnalyzeRule(httpRuntime = runtime).setContent("<main></main>")

        rule.getString("@js:java.get('https://example.com/a', {'X-Test':'yes'}).body()") shouldBe "wrapped:GET:"
        rule.getString("@js:java.head('https://example.com/a', {}).header('Location')") shouldBe "/next"
        rule.getString("@js:java.get('https://example.com/a', {}).cookie('PHPSESSID')") shouldBe "abc"
        rule.getString("@js:java.post('https://example.com/a', 'q=凡人', {'Content-Type':'text/plain'}).body()") shouldBe
            "wrapped:POST:q=凡人"

        requests.first().headers["X-Test"] shouldBe "yes"
        requests.last().body shouldBe "q=凡人"
        requests.last().headers["Content-Type"] shouldBe "text/plain"
    }

    "ported AnalyzeRule exposes cookie bridge and interactive unsupported helpers" {
        val cookieStore = InMemoryCookieStore().apply {
            seed("https://example.com", "https://example.com/a", "PHPSESSID=old; token=1")
        }
        val rule = AnalyzeRule(
            source = io.legado.app.data.entities.BookSource(
                bookSourceName = "测试源",
                bookSourceUrl = "https://example.com",
            ),
            cookieStore = cookieStore,
        ).setContent("<main></main>", "https://example.com")

        rule.getString("@js:java.getCookie('https://example.com/a','PHPSESSID')") shouldBe "old"
        rule.getString("@js:cookie.setCookie('https://example.com/b','sid=next');cookie.getCookie('https://example.com/b')") shouldBe
            "sid=next"
        rule.getString(
                "@js:" +
                    "cookie.removeCookie('https://example.com/b');" +
                    "String(cookie.getCookie('https://example.com/b')) == '' ? 'empty' : 'not-empty'",
        ) shouldBe "empty"
        rule.getString("@js:java.getVerificationCode('https://example.com/code.png')") shouldBe
            "UNSUPPORTED:getVerificationCode:https://example.com/code.png"
        rule.getString("@js:java.startBrowserAwait('https://example.com/check','验证').body()") shouldBe
            "UNSUPPORTED:startBrowserAwait:https://example.com/check"
    }
})

private class InMemoryCookieStore : EngineCookieStore {
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
