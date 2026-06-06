# 上游阅读/Legado 规则语义拆解

> 参考仓库：
> - `data/upstreams/luoyacheng-legado`：阅读 APP 原生规则执行语义
> - `data/upstreams/aoaostar-legado`：书源/订阅发布参考

## 1. 执行链路概览

阅读 APP 的书源执行分为以下阶段，LegadoHub 需要逐一对齐：

```
搜索:   searchUrl -> HTTP -> ruleSearch -> bookList -> [name, author, coverUrl, intro, ...]
发现:   exploreUrl -> HTTP -> ruleSearch (复用) -> bookList
详情:   bookUrl -> HTTP -> ruleBookInfo -> [name, author, intro, tocUrl, ...]
目录:   tocUrl -> HTTP -> ruleToc -> chapterList -> [chapterName, chapterUrl, updateTime]
正文:   chapterUrl -> HTTP -> ruleContent -> [title, content]
```

每个阶段都有独立的请求规格（URL、method、headers、body、charset）和规则规格（selector、extractor、transform）。

## 2. AnalyzeUrl 请求语法

`AnalyzeUrl.kt` 负责把书源里的 URL 模板解析为实际 HTTP 请求：

- **简单 URL**: `https://example.com/search?q={{key}}&page={{page}}`
- **JSON 规格**: `url,{"method":"POST","body":"key={{key}}","headers":{"X-Req":"1"},"charset":"gbk"}`
- **变量替换**: `{{key}}`、`{{page}}`、`{{title}}`、`{{author}}` 等来自规则上下文
- **方法支持**: GET、POST
- **编码支持**: UTF-8、GBK、GB2312、Big5（通过 charset 字段声明）
- **Headers**: source 级 `header` 字段 + 请求级 `headers` 合并
- **CookieJar**: `enabledCookieJar` 为 true 时维护源级 cookie

## 3. AnalyzeRule 规则语法

`AnalyzeRule.kt` 是规则解析核心。规则字符串格式：

```
selector1@selector2@...@extractMethod##replaceRegex
```

### 3.1 Selector 链

- **CSS/JSoup 选择器**: `class.item`、`tag.li`、`id.list`
- **索引**: `.item.0` 表示取第一个匹配
- **排除**: `.item!0` 排除第 0 个
- **XPath**: 以 `//` 开头时走 XPath
- **JsonPath**: 以 `$` 开头时走 JsonPath

### 3.2 @ 字段操作符

- `text`: 元素文本
- `textNodes`: 所有文本节点拼接
- `html`: 元素 HTML
- `href` / `src`: 属性值，自动相对路径转绝对
- `title` / 其他: 对应 HTML 属性

### 3.3 || 回退

多条规则用 `||` 分隔，按顺序执行，返回第一个非空结果：
```
class.item.0@text || id.fallback@text
```

### 3.4 ## 替换规则

正则替换后缀：
```
class.content@text##<script[^>]*>.*?</script>##
```

### 3.5 JS 扩展

- `@js:` 前缀：对提取结果执行 JS 变换
- `<js>...</js>` 块：在规则中嵌入 JS 代码
- `java.ajax(...)`：在 JS 中发起额外请求

## 4. 各阶段规则字段

### ruleSearch
- `bookList`: 列表选择器
- `name`, `author`, `coverUrl`, `intro`, `kind`, `lastChapter`, `wordCount`, `bookUrl`

### ruleBookInfo
- `init`: 预处理规则（可能含 `<js>`）
- `name`, `author`, `coverUrl`, `intro`, `kind`, `lastChapter`, `wordCount`, `tocUrl`

### ruleToc
- `chapterList`: 章节列表选择器
- `chapterName`, `chapterUrl`, `updateTime`
- `nextTocUrl`: 分页目录

### ruleContent
- `content`: 正文选择器
- `title`: 标题选择器
- `nextContentUrl`: 分页正文

## 5. JS 扩展能力

`JsExtensions.kt` 提供大量辅助函数：

- `java.ajax(url)` / `java.ajax(url, headers)`
- `java.get(url, headers)` / `java.post(url, body, headers)`
- `java.put(key, value)` / `java.get(key)` —— 规则上下文存储
- `java.log(msg)`
- `java.base64Encode` / `java.base64Decode`
- `java.md5` / `java.sha1`
- `java.timeFormat`
- `java.getElements` / `java.getElement` —— DOM 操作

## 6. Headers / Cookie / Login 行为

- source 级 `header` 可以是 JSON 字符串或键值对字符串
- `enabledCookieJar` 开启时，同一 source 的 HTTP 请求共享 cookie
- `loginUrl` 存在时，表示需要登录才能访问
- WebView 需求：某些源通过 `webView` 字段标记需要 WebView 渲染

## 7. LegadoHub 当前能力矩阵

| 能力 | 当前状态 | 说明 |
|---|---|---|
| CSS Selector 链 | 支持 | `app/legado_engine/rule_executor.py` 主执行路径 |
| XPath | 支持 | 支持作为列表与字段规则主路径执行 |
| JsonPath | 支持 | 支持 `$.key`、嵌套字段、`$.array[*]`、`$.array[0]` 与数组字段展开 |
| Regex | 支持 | 支持 `regex:` 作为列表与字段规则主路径 |
| `||` fallback | 支持 | 列表与字段均按分支返回第一个非空结果 |
| `@` 字段操作符 | 支持 | text/href/src/html/attribute |
| `##` replace | 支持 | 字段提取后执行正则替换 |
| `@js:` | 受限支持 | 支持安全字符串变换；复杂 DOM、网络、运行时 JS 仍标记为缺口 |
| `<js>` | 不支持 | 标记为 unsupported_syntax |
| `{{key}}` / `{{page}}` | 支持 | URL 与 POST body 均支持变量替换 |
| `@get` / `@put` | 支持 | 规则执行上下文可写入与读取临时变量 |
| Headers | 支持 | source 级 header 与请求级 header 合并 |
| CookieJar | 受限支持 | 同一运行器内可保存并复用基础 Cookie；尚未做持久化登录态 |
| GET/POST/body | 支持 | `parse_request_spec` |
| charset | 支持 | UTF-8/GBK/GB2312 |
| exploreUrl | 支持 | 支持 JSON/数组/字符串三类发现配置与分页加载 |
| loginUrl | 检测 | 可检测并标记为需要登录 |
| WebView | 检测 | 可检测并标记为引擎缺口 |

## 8. 差距分类

### 已完成（Implemented in current backend）
- XPath 作为主执行路径
- JsonPath 主执行路径（支持 `[*]`、数组索引与数组字段展开）
- Regex 主执行路径
- exploreUrl 解析与执行
- `@get` / `@put` 上下文存储
- source/request headers 合并
- 目录 `nextTocUrl` 与正文 `nextContentUrl` 分页跟随
- 同一运行器内基础 CookieJar
- 单源调用 trace 与引擎能力矩阵展示

### 暂不支持（Classify as unsupported）
- 复杂 `<js>` 块含 `java.ajax` 嵌套请求
- WebView 渲染依赖源
- 需要真实登录交互的源
- Rhino/ES6 完整 JS 运行时

### 后续扩展（Future runtime extension）
- 受限 JS 引擎（QuickJS / MiniRacer）
- WebView 抓取服务（Headless browser）
- 完整 Cookie 持久化与登录工作流
