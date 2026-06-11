# 书源插件模板

作为 LegadoHub 原生 Python 书源插件的起点。

## 目录结构

```text
plugins/sources/example_plugin/
  metadata.yaml
  source.py
  README.md
  tests/
    smoke.yaml
```

## metadata.yaml

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
  mode: auto        # never / auto / always
  required: false
browser:
  mode: none        # none / optional / required
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

字段规则：

- `id`：稳定的 ASCII 标识符，在所有插件中唯一。
- `name`：控制台中显示的显示名。
- `version`：插件版本，行为变更时递增。
- `contractVersion`：第一阶段必须为 `"1.0"`。
- `domains`：插件预期访问的域名。
- `baseUrls`：站点规范入口 URL。
- `capabilities`：支持的生命周期方法。
- `auth.mode`：`none`、`optional`、`required` 或 `manual`。
- `content.access`：`free`、`paid`、`mixed` 或 `unknown`。
- `tags`：运营提示，如 `html`、`json-api`、`proxy`、`cloudflare`、`login`、`special`。
- `explore` 保留给官方/授权书源，如起点、七猫、番茄、QQ 阅读。普通镜像或爬虫书源不得声明排行榜/分类发现能力。

## source.py

```python
from urllib.parse import urljoin
from bs4 import BeautifulSoup


class Source:
    id = "example_plugin"
    name = "示例书源"
    contract_version = "1.0"
    last_modified = "2026-06-10"
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
            "extra": {
                "status": ctx.text(html, ".status"),
                "updateTime": ctx.text(html, ".update-time"),
            },
        }

    async def toc(self, ctx, book_url: str):
        chapters = []
        seen = set()
        page_url = book_url
        for _ in range(200):
            html = await ctx.fetch_text(page_url)
            links = ctx.select(html, "#list dd a")
            new_count = 0
            for node in links:
                href = ctx.attr(node, "href", "")
                title = ctx.text(node).strip()
                if not href or not title or href in seen:
                    continue
                seen.add(href)
                chapters.append({
                    "sourceId": self.id,
                    "index": len(chapters) + 1,
                    "title": title,
                    "chapterUrl": ctx.urljoin(page_url, href),
                    "isVip": False,
                    "isLocked": False,
                })
                new_count += 1
            next_href = ctx.attr(html, "a:contains('下一页')", "href")
            if not next_href or new_count == 0:
                break
            next_url = ctx.urljoin(page_url, next_href)
            if next_url == page_url:
                break
            page_url = next_url
        return chapters

    async def chapter(self, ctx, chapter_url: str):
        parts = []
        current_url = chapter_url
        title = ""
        original_stem = self._chapter_stem(chapter_url)
        while current_url and len(parts) < 10:
            html = await ctx.fetch_text(current_url)
            if not title:
                title = ctx.text(html, "h1")
            content_html = ctx.html(html, "#content")
            content = self._clean_chapter_content(content_html)
            if content:
                parts.append(content)
            # 合并同一章节分页；跳到下一章前停止
            next_href = ctx.attr(html, "#next_url", "href")
            if not next_href or self._chapter_stem(next_href) != original_stem:
                break
            current_url = ctx.urljoin(chapter_url, next_href)
        return {
            "sourceId": self.id,
            "title": title,
            "content": "\n\n".join(parts),
            "chapterUrl": chapter_url,
            "format": "text",
            "authRequired": False,
            "isPaid": False,
        }

    def _chapter_stem(self, url: str) -> str:
        path = url.split("?")[0].split("#")[0]
        if "_" in path:
            return path.rsplit("_", 1)[0]
        return path.rsplit(".", 1)[0] if "." in path else path

    def _clean_chapter_content(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "header", "footer", "iframe", "ins", "center"]):
            tag.decompose()
        for div in soup.find_all("div"):
            text = div.get_text(strip=True)
            if len(text) < 80 and any(kw in text for kw in ["广告", "声明", "本章结束", "返回目录", "加入书签", "推荐", "最新网址", "章节内容缺失", "章节不存在"]):
                div.decompose()
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

## tests/smoke.yaml

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

## 书籍信息字段标准

`detail()` 应返回 Reading/Legado 通过 `ruleBookInfo` 消费的相同元数据表面。填充书源页面暴露的每个字段：

- 必填基线：`sourceId`、`name`、`author`、`bookUrl`、`tocUrl`。
- 强烈推荐：`coverUrl`、`intro`、`kind`、`lastChapter`、`wordCount`。
- 将站点特定但有用的元数据（如 `status`、`updateTime`、`lastUpdateTime`、`rating` 或原始标签）放在 `extra` 下。
- 返回 `intro` 前清理 SEO 尾巴、重复标签和站点导航杂项。
- 搜索结果在可能的情况下应使用相同的字段名，以便 Reading 在用户进入详情页之前渲染有用的列表。
- 如果搜索页不暴露 `lastChapter`、`author`、`coverUrl`、`intro`、`kind`、`wordCount` 或 `updateTime` 等标准字段，书源插件必须在其自身的 `search()` 方法内调用自身的 `detail()` 解析器为前几个稳定候选补全这些字段。不要依赖调度器来填充这些字段。
- 书源本地详情丰富应有界且无破坏：仅针对有稳定 `bookUrl` 的候选，短超时，失败被跟踪但不致命，仅填充空字段。在有用时标记 `extra.detailEnriched = true`。

推荐辅助：

```python
from app.source_plugins.search_enrichment import enrich_search_items_from_detail

async def search(self, ctx, keyword: str, page: int):
    ...
    return await enrich_search_items_from_detail(self, ctx, items)
```

## 目录完整性标准

`toc()` 必须按正常阅读顺序返回完整目录。许多镜像小说站点只渲染一个静态预览（包含开头几章和最新几章），而完整目录通过 AJAX/API、分页或"加载更多"脚本加载。这种情况下：

- 优先使用完整 AJAX/API/分页目录端点。
- 如果完整目录端点可以从书籍 URL 推导，在获取静态目录页之前先尝试它。某些站点会对 `/book/...` 页面挑战，但 `/ajax_novels/chapterlist/...` 仍可用。
- 仅当完整端点失败时，才将静态目录作为 fallback。
- 按章节 URL 去重。
- 丢弃 `#`、排序按钮、相关书籍链接和最近更新块。
- 站点可在正常/倒序之间切换时，按显式章号排序。
- 如果站点仅暴露部分目录，跟踪已知限制。

在编写 `toc()` 或 `chapter()` 的选择器之前，主动检查页面是否有 JSON/AJAX/get 端点。常见信号包括脚本变量、包含 `api`、`ajax`、`chapterlist`、`chapters`、`content`、`reader` 的网络路径，或移动/AMP 端点。优先使用稳定的 API/AJAX 响应而不是 HTML 解析获取完整目录和正文内容；HTML 选择器仅作为文档化的 fallback。如果端点探测返回 404/500/挑战页面，将探测结果保留在验证笔记或 `ctx.trace()` 中，以便下一次适配迭代不会重复盲目猜测。

重复镜像框架常出现相同陷阱：

- "最新章节"预览出现在真实目录之前。按区块边界解析，而不是仅使用宽泛选择器如 `#list a`。
- 某些 HTML 结构为 `<a><dd>title</dd></a>` 而不是 `<dd><a>title</a></dd>`。在假设框架形状之前，针对实时 DOM 验证。
- 分页目录可能使用兄弟 URL 如 `/book/123-2.html`，而不是子 URL 如 `/book/123/123-2.html`。跟随实际的 `下一页` 链接。
- 不要仅按章号去重。`番外`、`完结感言` 等无编号章节必须保留。
- 章节页面可能包含短的广告 `<p>` 加真实文本节点。不要让"第一个 `<p>` 获胜"的逻辑丢弃正文。
- 如果来源页面本身返回缺失、串章、混章正文，插件应跟踪或为该章节返回空，而不是将明显被污染的内容缓存为有效文本。解析器不得伪造缺失正文。

## 章节内容标准

`chapter()` 必须返回干净、可读的纯文本：

- 通过 `<br>`、`<p>` 或块文本提取保留段落边界。
- 合并同一章节分页，并在到达下一章前停止。
- 移除标题页码标记，如 `(1/2)`、`(2/3)`、`（第2页）`。
- 剥离 script/style/nav/header/footer、广告容器、下载提示、推荐块、缺章提示和站点口号。
- 将短的仅广告内容视为无效；不要将其作为成功章节缓存或返回。
- 正文优先使用 API/AJAX/get 端点；HTML 选择器作为 fallback。

## Fallback 策略标准

当站点搜索被阻止或不稳定时，保持降级书源本地化和可预测：

1. 通过声明的访问层进行正常书源搜索。
2. 如果检测到挑战或 JavaScript 渲染的结果页，对同一站点搜索 URL 进行浏览器渲染搜索。
3. 书源拥有的排行榜/分类/最近更新 fallback。
4. 仅作为最终声明 bypass 使用外部搜索引擎代理。

HTTP 200 仍然可能是挑战页面。在将解析失败视为空结果之前，检查返回的 HTML 中是否有挑战标记。

搜索页也需要误报防护：如果响应只包含通用推荐、热门书籍或 fallback 导航，且不包含查询关键词的显式标题命中，返回空或继续到声明的 fallback。不要将推荐页视为成功搜索。

## 特殊站点覆盖

对于特殊站点，将自定义逻辑保留在生命周期方法内，但通过网络访问保持在 `ctx` 内。

```python
async def chapter(self, ctx, chapter_url: str):
    html = await ctx.fetch_text(chapter_url)
    token = self._extract_token(html)
    payload = self._decrypt_payload(html, token)
    return {
        "title": ctx.text(html, "h1"),
        "content": ctx.clean_text(payload),
        "chapterUrl": chapter_url,
    }
```

不要在插件中启动不受管理的线程、创建全局 HTTP 客户端或实现书源级并发。

## 登录/认证钩子

对于官方或基于登录的书源，在 `metadata.yaml` 中声明认证并实现可选钩子。

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

```python
async def auth_status(self, ctx):
    cookie = ctx.cookies.get("qidian.com")
    return {
        "sourceId": self.id,
        "authenticated": bool(cookie),
        "accountName": "",
        "expiresAt": "",
        "message": "已检测到 Cookie" if cookie else "未登录",
        "requiredActions": [] if cookie else ["manual_login"],
    }

async def prepare_login(self, ctx):
    return {
        "sourceId": self.id,
        "mode": "manual_browser",
        "loginUrl": "https://www.qidian.com",
        "instructions": "在打开的浏览器中完成登录，然后回到后台点击检测登录状态。",
        "cookieDomains": ["qidian.com"],
    }
```

锁定章节应返回结构化认证/付费字段，而不是假装解析失败。
