# 别家聚合书源段评/章评实现方案研究

> 研究对象：光遇聚合 v26.6.9、书山聚合 v5.30
> 研究日期：2026-06-11
> 目的：了解成熟聚合书源如何在 Legado 阅读 App 中实现段评（段落评论）和章评（章节评论）

---

## 一、概述

两个书源代表了两种不同的段评实现范式：

| 维度 | 光遇聚合 | 书山聚合 |
|------|---------|---------|
| **架构** | 服务端驱动（后端注入 `<comment>` 标签） | 客户端驱动（前端 `getComments()` 主动获取并注入） |
| **数据流** | 请求 `?review=1` → 后端在内容中嵌入评论标记 → 前端替换为 SVG | 获取正文 → 调用代理 API 获取评论统计 → 前端解析并注入 SVG |
| **支持源站** | 番茄、七猫、塔读、QQ阅读 | 番茄、七猫、QQ阅读、企鹅看书、晋江、半夏 |
| **标题评论** | 无（纯段落级） | QQ阅读/企鹅看书支持标题云评论（Bubble 缓存到标题） |
| **设置方式** | 独立设置页 `getSvgSettings()`，HTML 弹窗 | 全局开关 `toggleParacomment()`，通过 `java.get/put("yunpara")` |
| **iOS 支持** | `paraForiOS()` → `<comment>` 原生标签 + `<div rs-native>` | `createCommentHtmlTag()` → 类似 `<comment>` 原生标签 |

---

## 二、光遇聚合段评方案（服务端驱动）

### 2.1 核心流程

```
获取目录 → 构建章节URL → 请求 /content?review=1 → 后端注入 <comment> 标签
                                               ↓
                    前端注入 base_url/book_id/ssionid 到 ident URL
                                               ↓
                    paraForAndroid: <comment> → <img> SVG气泡
                    paraForiOS:     <comment> → <comment> 原生标签
                                               ↓
                    点击气泡 → showCmt() → WebView 打开评论详情页
```

### 2.2 关键代码

**内容获取（ruleContent）：**
```js
let SOURCES_WITH_REVIEW = ['番茄', '七猫', '塔读', 'QQ阅读', 'svip_QQ阅读'];
let dpSettings = getVariable('段评设置');
let para = dpSettings && dpSettings['段评开关'] || 'true';
let hasReview = SOURCES_WITH_REVIEW.includes(sources) && para=="true" && tab == '小说';
let content_url = hasReview ? CONTENT_URL_WITH_REVIEW : CONTENT_URL; // '/content?review=1'
let data = request(content_url, 'POST', params);
```

**服务端返回的内容格式：**
```html
<p>某段落文字<comment ident="/get_review?chapter_id=xxx&book_id=" count="123" /></p>
```

**URL 注入（补齐参数）：**
```js
let fqssionid = getFqToken();
content = content
    .replace(/ident="/g, `ident="${base_url}`)
    .replace(/book_id=/g, `book_id=${book_id}&ssionid=${fqssionid}`);
// 结果：ident="https://v1.gyks.cf/get_review?chapter_id=xxx&book_id=123&ssionid=abc"
```

### 2.3 Android 渲染：`paraForAndroid()`

```js
function paraForAndroid(content, sources) {
    return content.replace(/<p>(.*?)(?:<comment ident="([^"]*)" count="([^"]*)" \/>)?<\/p>/g,
        (match, text, url, count) => {
            if (url && count) {
                cache.putMemory(url, 0); // 防重复点击初始化
                return `<p>${text}<img src="${createSvg(count, url, sources)}"></p>`;
            } else {
                return `<p>${text}</p>`;
            }
        }
    );
}
```

**SVG 气泡生成（`createSvg`）：**
- 支持 6 种预设样式 + 自定义 SVG
- 可配置边框颜色、填充颜色、字体颜色
- 支持"气泡增大"开关（`TEXT` vs `text`）
- 数字 >99 显示为 `99+`
- 生成的 data URI 嵌入 `js`/`click` 动作：`showCmt(url, sources)`

### 2.4 iOS 渲染：`paraForiOS()`

```js
function paraForiOS(html, sources) {
    return html.replace(
        /<p>(.*?)(?:<comment ident="([^"]*)" count="([^"]*)" \/>)?<\/p>/g,
        (match, text, url, count) => {
            if (url && count) {
                return `<div rs-native>${text}<comment count="${count>99?'99':count}" onPress="java.showReadingBrowser('${url}','${sources}段评')"></div>`;
            }
            return `<div rs-native>${text}</div>`;
        }
    );
}
```

### 2.5 点击交互：`showCmt()`

根据 App 变体（安卓/轻阅读/改版）不同：
- **安卓**：第一次点击忽略（防误触），第二次才响应
- **轻阅读**：`java.startBrowserDp(url, sources + '段评')` — 底部弹窗浏览器
- **改版**：`java.showBrowser()` — 底部 Sheet Dialog，支持拖拽、背景暗淡、缓存优化
- **默认**：`java.startBrowser(url, sources + '段评')` — 全屏浏览器

### 2.6 设置系统：`getSvgSettings()`

通过 `java.startBrowserAwait()` 打开一个内嵌 HTML 设置页：
- 段评开关：`true` / `false`
- 气泡增大：`true` / `false`
- 段评样式：0-5 预设 + 自定义
- 段评边框颜色 / 字体颜色 / 填充颜色
- 自定义段评样式：JSON 配置

设置结果通过解析 HTML body 中的 `<span>` 和 `<textarea>` 值提取。

---

## 三、书山聚合段评方案（客户端驱动）

### 3.1 核心流程

```
获取目录 → buildChapterUrl() 构建 data: URL（注入 bookid/chapterid）
                                               ↓
                    请求章节内容 → 获取正文 HTML
                                               ↓
                    检查 yunpara == "on" 且 source 支持
                                               ↓
                    getComments(正文, bookid, chapterid, sourceType, ...)
                                               ↓
                    调用代理 API 获取评论统计
                    /proxy_qqidea, /proxy_idea, /proxy_qmidea, /proxy_jjidea
                                               ↓
                    解析数据 → 定位段落 → createSvg() → 注入正文
                                               ↓
                    QQ阅读 title 评论 → cache.put(bookid_chapterid) → 附加到标题
```

### 3.2 关键代码

**全局开关：**
```js
function toggleParacomment() {
    const key = "yunpara";
    let status = java.get(key) ?? "off";
    if (status == "on") {
        java.put(key, "off");
        java.toast("\n番茄，七猫，QQ阅读，企鹅看书\n段评已关闭");
    } else {
        java.put(key, "on");
        java.toast("\n番茄，七猫，QQ阅读，企鹅看书\n段评已开启");
    }
}
```

**启用判断（ruleContent.content 解包后）：**
```js
let yunparaStatus = java.get("yunpara") || "off";
let isParagraphEnabled = false;
if (yunparaStatus == "on") {
    if (/七猫/.test(contenturl) && book_id && item_id && content_md5) {
        isParagraphEnabled = true;
    } else if (/番茄小说/.test(contenturl) && book_id && item_id && !contenturl.includes('tone_id=')) {
        isParagraphEnabled = true;
    } else if (isBanxia && novelId && chapterId) {
        isParagraphEnabled = true;
    } else if ((/企鹅看书|QQ阅读/.test(contenturl)) && qqBookid && qqChapterid) {
        isParagraphEnabled = true;
    }
}
// 然后调用 getComments(result, bookid, chapterid, sourceType, ...)
```

**标题评论附加（ruleContent.title）：**
```js
let yunparaStatus = java.get("yunpara") || "off";
let isModifiedVersion = checkEnv();
let isQingRead = isQRead();
let isQQSource = /QQ阅读|企鹅看书/.test(decoded);

if ((isModifiedVersion || isQingRead) && yunparaStatus == "on" && isQQSource && bookid && chapterid) {
    let Bubble = cache.get(bookid + "_" + chapterid) || "";
    title = title + Bubble;
}
```

### 3.3 各源站评论数据结构

#### QQ阅读 / 企鹅看书（`proxy_qqidea`）

```json
{
  "noteCount": [{
    "data": [
      {"paragraphOffset": 0, "count": 123},
      {"paragraphOffset": 5, "count": 45}
    ]
  }]
}
```
- `paragraphOffset == 0`：标题评论（生成 Bubble 缓存到标题）
- `paragraphOffset > 0`：段落评论（段落索引，需 `-1` 映射到行索引）

#### 番茄小说（`proxy_idea`）

```json
{
  "data": {
    "data": {
      "0": {"count": 10},
      "5": {"count": 3}
    }
  }
}
```
- Key 为段落行号（从 0 开始）

#### 七猫（`proxy_qmidea`）

```json
{
  "data": {
    "chapters": [{
      "bubbles": [
        {"p": "段落MD5", "c": "12"},
        {"p": "段落MD5", "c": "5"}
      ]
    }]
  }
}
```
- `p`：段落内容 MD5 哈希
- `c`：评论数量
- 需要原文章节 `content_md5` 作为请求参数

#### 晋江 / 半夏（`proxy_jjidea`）

```json
{
  "data": [
    {"paragraph_id": "1", "comment_total": 8},
    {"paragraph_id": "3", "comment_total": 2}
  ]
}
```
- `paragraph_id`：段落编号（从 1 开始）
- `comment_total`：评论数

### 3.4 `getComments()` 核心逻辑

```js
function getComments(content, bid, cid, sourceType, content_md5, extra) {
    let apiUrl;
    switch(sourceType) {
        case 'qq':
            apiUrl = `${host}/proxy_qqidea?bid=${bid}&cid=${cid}`;
            break;
        case 'fq':
            apiUrl = `${host}/proxy_idea?item_id=${cid}`;
            break;
        case 'qm':
            apiUrl = `${host}/proxy_qmidea?action=paragraph_bubbles&book_id=${bid}&item_id=${cid}&content_md5=${content_md5}`;
            break;
        case 'jj':
            apiUrl = `${host}/proxy_jjidea?bid=${bid}&cid=${cid}`;
            if (extra) {
                apiUrl += `&bookid=${extra.bookid}&chapterid=${extra.chapterid}`;
            }
            break;
    }
    
    let response = java.ajax(apiUrl);
    let data = JSON.parse(response);
    
    // 解析不同格式的评论数据...
    // 将 content 拆分为段落数组
    // 在对应段落后插入 SVG 气泡
    // QQ阅读的 paragraphOffset=0 生成 titleBubble 缓存到 cache
    
    return injectedContent;
}
```

### 3.5 章节 URL 构建：`buildChapterUrl()`

对于 QQ阅读/企鹅看书：
```js
if (catalog.source == '企鹅看书' || catalog.source == 'QQ阅读') {
    const qqBidMatch = x.url.match(/bookid=(\d+)/);
    const qqCidMatch = x.url.match(/chapterid=(\d+)/);
    if (qqBidMatch && qqCidMatch) {
        contentUrlParams += `&bookid=${qqBidMatch[1]}&chapterid=${qqCidMatch[1]}`;
    }
}
return `data:contentUrl;base64,${java.base64Encode(contentUrlParams)},{"type":"qingci"}`;
```

对于番茄/七猫/晋江：额外注入 `js` 字段指向评论详情页 URL：
```js
commentPart = `{"type":"qingci","js":"book ? result : '${commentUrl}'"}`;
```

---

## 四、两方案对比

| 对比维度 | 光遇聚合（服务端驱动） | 书山聚合（客户端驱动） |
|---------|---------------------|---------------------|
| **实现复杂度** | 后端复杂，前端简单（只需替换标签） | 后端简单，前端复杂（需解析多源格式） |
| **前端代码量** | 较小（替换 `<comment>` → SVG） | 较大（`getComments()` 需处理 4+ 源格式） |
| **可维护性** | 后端统一格式，前端一次适配 | 每新增一个源需修改前端解析逻辑 |
| **灵活性** | 受限于后端返回的 `<comment>` 位置 | 可自定义段落匹配算法（MD5/索引/内容匹配） |
| **网络请求** | 1 次（内容+评论标记一起返回） | 2 次（内容 + 评论 API） |
| **缓存策略** | 无（每次重新获取） | 有（title Bubble 缓存到 Legado cache） |
| **iOS 支持** | `<comment>` 原生标签 + `<div rs-native>` | `<comment>` 原生标签 |
| **防误触** | 安卓第一次点击忽略 | 1 秒限流 `checkClickRateLimit()` |
| **设置粒度** | 每源统一开关 + 样式配置 | 全局开关 `yunpara` + 颜色配置 |
| **标题评论** | ❌ 不支持 | ✅ QQ阅读/企鹅看书支持 |
| **章末评论** | 通过 `/get_review` 整章评论页 | 通过 `commentPart.js` 整章评论页 |

---

## 五、与起点本章说 API 的对比

### 5.1 起点本章说（我们已逆向的 API）

| 维度 | 起点本章说 | 光遇/书山段评 |
|-----|-----------|--------------|
| **数据源** | 起点官方 API（`reviewsummary4m` + `reviewlist4m`） | 第三方聚合服务器代理 |
| **数据粒度** | 段落级（`paragraphId=N`）+ 章末（`paragraphId=-1`） | 段落级（各种格式） |
| **评论内容** | 可直接获取评论文本、用户、时间、点赞数 | 仅获取评论数量统计 |
| **点击后** | 需打开新页面展示评论详情 | 需打开新页面展示评论详情 |
| **是否需要登录** | 需要起点 Cookie | 需要各源站 Cookie / Token |
| **段评标记** | API 返回段落编号 | 需在正文中标记段落位置 |

### 5.2 关键差异

1. **数据深度不同**：起点本章说 API 返回完整的评论内容（文本、用户、时间、点赞等），而光遇/书山的代理 API 只返回评论数量统计（用于生成气泡）。用户点击气泡后才去获取具体评论内容。

2. **段落定位方式不同**：
   - 起点：API 返回 `paragraphId`，需要我们自己把正文拆成段落并编号
   - 光遇：后端直接在正文中插入 `<comment>` 标签，段落位置由后端决定
   - 书山：前端根据源站格式（索引/MD5/段落号）匹配段落

3. **集成方式不同**：
   - 起点：直接调用官方 API，无需第三方服务器
   - 光遇/书山：依赖第三方聚合服务器做代理和数据转换

---

## 六、对 AI 聚合书源的启示

### 6.1 技术方案选择

基于我们的架构（FastAPI 后端 + React 前端 + 起点官方 API），推荐采用 **书山聚合的客户端驱动模式**，但做以下调整：

| 我们的优势 | 如何利用 |
|-----------|---------|
| 自己控制后端 | 后端统一获取本章说数据，前端只需渲染 |
| 有 Playwright | 可用浏览器自动化获取最难的源站数据 |
| 起点官方 API 已逆向 | 直接调用，无需代理服务器 |
| React 前端 | 可用更现代的 UI 组件展示评论 |

### 6.2 推荐实现方案

```
前端阅读页加载章节 → 同时请求内容 + 本章说数据
                                ↓
                    后端 chapter_reviews() 获取 reviewsummary4m + reviewlist4m
                                ↓
                    返回结构化评论数据（段落级 + 章末级）
                                ↓
                    前端解析正文，按段落编号插入气泡/标记
                                ↓
                    用户点击 → 弹出评论列表 Drawer / Modal
```

### 6.3 需要解决的关键问题

1. **段落对齐**：起点 API 返回 `paragraphId`，需要将正文拆分成段落并一一对应
   - 方案：按 `<p>` 标签或换行符拆分，编号后匹配
   
2. **段落级评论渲染**：在 Web 端如何展示段评气泡
   - 方案：在段落末尾添加小圆点/数字标记，hover/点击展开
   - 或：在段落右侧添加悬浮气泡（类似起点 App）

3. **章末评论展示**：`paragraphId=-1` 的章末评论如何展示
   - 方案：章节末尾添加"章末评论"折叠面板

4. **Legado 端兼容性**：如果要导出到 Legado 书源
   - 参考书山聚合的 `data:contentUrl;base64,...` 格式
   - 参考光遇聚合的 `<comment>` 标签方案
   - 或者提供独立的 `ruleContent` 注入逻辑

### 6.4 与起点源的关系

既然 AI 聚合书源以起点数据为第一验证来源，段评也应如此：
- **第一优先级**：起点官方 `reviewlist4m` API
- **第二优先级**：其他源站（如番茄、七猫等，待后续实现）
- **聚合策略**：以起点的段落编号为基准，其他源站的段评做补充

---

## 七、附录：关键数据结构速查

### 起点 reviewlist4m 返回结构
```json
{
  "result": 0,
  "data": {
    "list": [
      {
        "id": "评论ID",
        "paragraphId": 5,
        "content": "评论内容",
        "userName": "用户名",
        "likeNum": 10,
        "type": 2
      }
    ]
  }
}
```

### 光遇 `<comment>` 标签格式
```html
<p>段落文字<comment ident="/get_review?chapter_id=xxx&book_id=yyy" count="123" /></p>
```

### 书山 QQ阅读评论统计格式
```json
{"noteCount": [{"data": [{"paragraphOffset": 5, "count": 45}]}]}
```

### 书山番茄评论统计格式
```json
{"data": {"data": {"5": {"count": 3}}}}
```

---

*文档结束*
