# 书源插件模板（中文）

这份文档就是给你直接开工用的。

如果你只想先把一个插件跑起来，不想先看一堆背景资料，那就先看这份。

一句话版本：

**一个最小可用的 LegadoHub 插件，核心只需要 `metadata.yaml` 和 `source.py`。**

---

## 1. 最小目录

最小版本：

```text
plugins/sources/example_plugin/
  metadata.yaml
  source.py
```

更适合长期维护的版本：

```text
plugins/sources/example_plugin/
  metadata.yaml
  source.py
  README.md
  tests/
    smoke.yaml
```

怎么理解：

- `metadata.yaml`：告诉运行时“我是谁、我支持什么”
- `source.py`：真正的适配代码
- `README.md`：写给人看
- `tests/`：写给验证流程看

注意：
`README.md`、`tests/`、`smoke.yaml` 都不是运行时硬依赖。

---

## 2. `metadata.yaml` 怎么起步

先用最保守的一版：

```yaml
contractVersion: "1.0"
id: example_plugin
name: 示例书源
version: 0.1.0
type: source
domains:
  - example.com
baseUrls:
  - https://example.com
capabilities:
  - search
  - detail
  - toc
  - chapter
enabled: true
proxy:
  mode: auto
  required: false
browser:
  mode: none
  reason: ""
auth:
  mode: none
  cookieDomains: []
content:
  access: free
tags:
  - html
  - no-login
```

### 关键字段

`id`
: 插件唯一标识，尽量稳定。

`name`
: 控制台里给人看的名字。

`domains`
: 这个插件会访问哪些域名。

`baseUrls`
: 站点主入口。

`capabilities`
: 这个插件实现了哪些能力。普通小说站最常见的是：
- `search`
- `detail`
- `toc`
- `chapter`

`auth.mode`
: 如果站点不需要登录，就先写 `none`。

`content.access`
: 内容是免费、付费还是混合。

### 一个重要约束

普通镜像站、抓取站不要随便声明 `explore`。  
排行榜 / 分类能力尽量留给官方或授权书源。

---

## 3. `source.py` 最少实现什么

四个最基础的方法：

1. `search`
2. `detail`
3. `toc`
4. `chapter`

下面是一份最常用骨架：

```python
from bs4 import BeautifulSoup


class Source:
    id = "example_plugin"
    name = "示例书源"
    contract_version = "1.0"
    base_url = "https://example.com"

    async def search(self, ctx, keyword: str, page: int):
        html = await ctx.fetch_text(
            f"{self.base_url}/search",
            params={"q": keyword, "page": page},
        )
        items = []
        for node in ctx.select(html, ".result-item"):
            items.append({
                "sourceId": self.id,
                "name": ctx.text(node, ".title"),
                "author": ctx.text(node, ".author"),
                "bookUrl": ctx.urljoin(self.base_url, ctx.attr(node, "a", "href")),
                "coverUrl": ctx.urljoin(self.base_url, ctx.attr(node, "img", "src")),
                "intro": ctx.text(node, ".intro"),
                "kind": ctx.text(node, ".kind"),
                "lastChapter": ctx.text(node, ".latest"),
            })
        return items

    async def detail(self, ctx, book_url: str):
        html = await ctx.fetch_text(book_url)
        return {
            "sourceId": self.id,
            "name": ctx.text(html, "h1"),
            "author": ctx.text(html, ".author").replace("作者：", "").strip(),
            "coverUrl": ctx.urljoin(book_url, ctx.attr(html, ".cover img", "src")),
            "intro": ctx.text(html, ".intro"),
            "kind": ctx.text(html, ".kind"),
            "lastChapter": ctx.text(html, ".latest"),
            "wordCount": ctx.text(html, ".word-count"),
            "tocUrl": book_url,
            "authRequired": False,
        }

    async def toc(self, ctx, book_url: str):
        chapters = []
        html = await ctx.fetch_text(book_url)
        for index, node in enumerate(ctx.select(html, "#list dd a"), start=1):
            chapters.append({
                "sourceId": self.id,
                "index": index,
                "title": ctx.text(node),
                "chapterUrl": ctx.urljoin(book_url, ctx.attr(node, "href")),
                "isVip": False,
                "isLocked": False,
            })
        return chapters

    async def chapter(self, ctx, chapter_url: str):
        html = await ctx.fetch_text(chapter_url)
        content_html = ctx.html(html, "#content")
        return {
            "sourceId": self.id,
            "title": ctx.text(html, "h1"),
            "content": self._clean_chapter_content(content_html),
            "chapterUrl": chapter_url,
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _clean_chapter_content(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "iframe", "ins", "center"]):
            tag.decompose()
        for br in soup.find_all("br"):
            br.replace_with("\n")
        paragraphs = []
        for p in soup.find_all("p"):
            text = p.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)
        if paragraphs:
            return "\n\n".join(paragraphs)
        text = soup.get_text("\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n\n".join(lines)
```

---

## 4. 最推荐的开发顺序

不要一开始就把所有复杂度一起塞进去。

推荐顺序：

1. 先把 `search()` 跑通
2. 再补 `detail()`
3. 再补 `toc()`
4. 最后补 `chapter()`

也就是说，先把阅读主链路通了，再考虑：

- 登录
- 评论
- 解密
- 反爬
- 浏览器绕过

---

## 5. 各方法最好返回什么

### `search()`
尽量补齐：

- `name`
- `author`
- `bookUrl`
- `coverUrl`
- `intro`
- `kind`
- `lastChapter`

### `detail()`
至少保证：

- `sourceId`
- `name`
- `author`
- `bookUrl`
- `tocUrl`

最好还能给：

- `coverUrl`
- `intro`
- `kind`
- `lastChapter`
- `wordCount`

### `toc()`
关键要求：

**返回完整目录，不要把目录预览页误当成完整目录。**

很多站点会有这个坑：

- 页面只显示最前面几章和最新几章
- 真正完整目录在 AJAX / API / 分页里

### `chapter()`
目标很简单：

**返回干净、可读、段落正常的纯文本正文。**

至少要处理：

- `<br>` / `<p>` 段落
- 广告
- 推荐块
- 上下页残留
- 同章分页

---

## 6. 常见坑

### 目录页是假目录
看起来像目录，实际上只是“最新章节预览”。

### 搜索页字段不全
可能只有书名，没有作者、简介、封面。

### 正文第一页是假正文
第一页可能是广告、下载提示、推荐块。

### 下一页其实还是同一章
要合并，不要误判成下一章。

### 不要太早做登录
站点不需要登录时，先别做登录。

登录、Cookie、验证码、浏览器绕过都会明显提高复杂度。

---

## 7. 什么时候再加登录能力

如果站点确实要登录，再扩：

```yaml
auth:
  mode: optional
  loginUrl: https://www.qidian.com
  accountRequiredFor:
    - paid_chapter
  cookieDomains:
    - qidian.com
content:
  access: mixed
  paid: supported_after_login
tags:
  - official
  - login
  - paid
```

以及：

```python
async def auth_status(self, ctx):
    ...

async def prepare_login(self, ctx):
    ...
```

这一步应该是**后加项**，不是默认项。

---

## 8. 什么时候需要 README 和 tests

### `README.md`
不是运行必需，但如果插件要长期维护，建议加。

适合写：

- 这个站适配了什么
- 当前支持哪些能力
- 有哪些已知限制
- 是否需要登录 / 代理 / 浏览器

### `tests/smoke.yaml`
也不是运行必需，但如果要长期维护，建议加。

最小例子：

```yaml
keyword: 凡人修仙传
expect:
  search_min_items: 1
  detail_has:
    - name
    - author
    - tocUrl
  toc_min_chapters: 1
  chapter_min_chars: 200
```

它的价值很直接：

- 以后你改了解析逻辑
- 能快速看出插件有没有被改坏

---

## 9. 这份模板最适合怎么用

最推荐的不是整份照抄，而是：

1. 先复制最小骨架
2. 把站点自己的：
   - 搜索结构
   - 详情结构
   - 目录结构
   - 正文结构
   换进去
3. 一步一步跑通

如果你下一步想看“适配真实站点时该怎么推进”，再继续看：

- `plugin-source-workflow.md`

这份更偏模板，那份更偏流程。
