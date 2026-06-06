# Phase 1 真实书源审核验收记录（2026-06-06）

## 当前结论

本轮审核以 `engine-jvm` 作为阅读书源解析内核，调用 `data/sources/raw/by-site/legado/sub-xiu2_yuedu.json` 中的真实 XIU2/Yuedu 书源进行验证。JVM 自动化回归测试通过，真实书源已经验证到完整闭环能力，但真实源矩阵仍暴露出若干站点限制和引擎语义缺口。

当前状态适合保存为 Phase 1 中间基线，不应声明 Phase 1 完整结束。

## 已完成修复

- `AnalyzeRule` 支持链式 `<js>...</js>` 与后续选择器组合，例如 `<js>result</js>.book@text`。
- `AnalyzeRule` 支持字段选择器后接 `@js:`，例如 `a@data-bid@js:'https://m.qidian.com/book/' + result + '/'`。
- `AnalyzeRule.getElements()` 支持纯 JS 返回元素列表，例如 `<js>java.getElement('.book')</js>`。
- `java.getElement()` 在空选择器结果时返回空 `JsElementList`，避免真实书源里 `c.length` 访问空值时报错。
- `WebBook.exploreKinds()` 支持 JSON 尾逗号，并且不再把 JSON 解析失败伪装成 `ERROR:` 分类。
- `source-smoke` 选择第一个有 URL 的发现分类，跳过分组标题。
- `source-smoke` 与 batch 搜索的失败分类更细：`SOURCE_TIMEOUT`、`REDIRECT_LOOP`、`HTTP_4XX`、`NETWORK_ERROR` 等。

## 自动化验证

命令：

```powershell
$env:JAVA_HOME='C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot'
$env:Path="$env:JAVA_HOME\bin;$env:Path"
$env:GRADLE_OPTS=''
data\upstreams\luoyacheng-legado\gradlew.bat -p . :engine-jvm:test --no-daemon
```

结果：

```text
BUILD SUCCESSFUL in 1m 11s
65 tests completed
```

## CLI 基础验收

版本命令：

```powershell
& 'C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot\bin\java.exe' -jar engine-jvm\build\libs\engine-jvm-0.0.1.jar version
```

输出：

```text
0.0.1
```

书源解析：

```powershell
& 'C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot\bin\java.exe' -jar engine-jvm\build\libs\engine-jvm-0.0.1.jar parse-source data\sources\raw\by-site\legado\sub-xiu2_yuedu.json
```

结果：解析 26 个书源对象；其中 14 个为启用状态。

## 真实书源 smoke 结果

### 阅友小说

命令：

```powershell
& 'C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot\bin\java.exe' -jar engine-jvm\build\libs\engine-jvm-0.0.1.jar source-smoke data\sources\raw\by-site\legado\sub-xiu2_yuedu.json "阅友" "凡人修仙传" 12000
```

结果：

- search：成功，5 条结果。
- detail：成功，获取书籍详情与目录地址。
- toc：成功，3876 章。
- content：成功，正文 2190 字符。
- exploreKinds：成功，29 个分类。
- explore：成功，6 条发现结果。

说明：该源证明当前 JVM 内核已经具备真实书源 search/detail/toc/content/explore 的完整闭环能力。

### 起点中文

结果：

- search：`PARSE_EMPTY`，站点返回 202 后解析结果为空。
- exploreKinds：成功，326 个分类；已正确跳过空 URL 分组标题，选中“月票榜”。
- explore：`PARSE_EMPTY`。

说明：此前 `bookList` 规则被误送入 JSoup 的问题已修复；当前失败不再是该 JSoup 误解析问题。

### 番茄小说2

结果：

- search：`JS_ERROR`，`missing ; before statement (AnalyzeRule#3)`。
- exploreKinds：成功，46 个分类；JSON 尾逗号解析已通过。
- explore：仍失败，当前错误为 `Could not parse query '$.data.result||$.data.data'`。

待办：`ruleExplore.bookList` 混合了 `.book_list[*]&&data.data&&...&&$.data.result||$.data.data`。需要继续补齐 JSON 内容上的 shorthand 规则：`.field`、`field.subfield`、`$.path||$.fallback` 在 `getElements()` 和字段抽取里都应走 JsonPath 语义，而不是 JSoup/CSS。

### 得奇小说网

结果：

- search：`SOURCE_TIMEOUT`，`Read timed out`。
- exploreKinds：成功，2 个分类。
- explore：`SOURCE_TIMEOUT`。

### 武林中文网

结果：

- search：`HTTP_4XX`，HTTP 403。
- exploreKinds：`PARSE_EMPTY`。

### 酷我小说

结果：

- search：`PARSE_EMPTY`。
- exploreKinds：`PARSE_EMPTY`。

## 批量搜索验收

命令：

```powershell
& 'C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot\bin\java.exe' -jar engine-jvm\build\libs\engine-jvm-0.0.1.jar batch-search data\sources\raw\by-site\legado\sub-xiu2_yuedu.json "凡人修仙传"
```

结果：

- totalSources：14
- completedSources：14
- results：6
- 有结果源：阅友小说 5 条、天天看小说 1 条。
- 典型失败分类：
  - `PARSE_EMPTY`：起点中文、酷我小说
  - `HTTP_4XX`：艾途小说、铅笔小说、武林中文网
  - `REDIRECT_LOOP`：大熊猫文学网
  - `SOURCE_TIMEOUT`：得奇小说网、快书网、手机小说、就爱文学
  - `NETWORK_ERROR`：熊猫看书证书链失败

## 当前未完成点

1. 番茄小说2 的 search JS 仍有 Rhino/规则兼容问题。
2. 番茄小说2 的 explore 列表规则需要补齐 JSON shorthand 与混合 fallback 语义。
3. 笔阅读器 `bookSourceUrl` 带 `##`，请求生成 `/api/...` 时未正确归一化为绝对 URL。
4. 起点搜索和发现当前为空，需要结合站点 Cookie/WebView 验证逻辑继续区分站点限制和内核能力。
5. 真实源可用率较低，后续后台应保留 per-source failure reason、自动禁用、手动复测与代理重试机制。

## 下一步建议

1. 继续补 `AnalyzeRule.getElements()` 对 JSON shorthand 的支持：
   - `.field`
   - `field.subfield`
   - `$.path||$.fallback`
   - `&&` 与 `%%` 合并语义
2. 为番茄 `ruleExplore.bookList` 添加离线 mock 测试，先让规则语义可重复验证，再跑真实源。
3. 修复 `bookSourceUrl` 中 `##` 导致的 baseUrl 归一化问题。
4. 完成后再次运行 JVM 回归、番茄 smoke、批量搜索真实矩阵。
