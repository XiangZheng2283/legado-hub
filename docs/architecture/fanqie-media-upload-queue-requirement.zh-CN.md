# fanqie（番茄）评论媒体上传队列 —— 需求文档

- 状态：已确认需求，待执行
- 日期：2026-08（对话定稿）
- 关联：plugins/sources/official/fanqie_local、docs/fq/Tomato-Novel-Downloader、docs/apk/legado-X

## 背景与目标

Legado-X 客户端读取番茄（fanqie）书源时，评论通过 sourceWebView 加载 /reviews/view HTML 面板。客户端面板的图片加载策略（SourceScopedWebController.kt + SourceScopedRequestPolicy.kt）只放行**同源**或 **https 公网（跨源会剥离鉴权头）** 的图片。番茄本地下载器（Rust，端口 18423）把评论头像/正文图/封面保存在**本地磁盘**，不能作为 URL 直接给客户端。

目标：把本地评论媒体**上传到托管的 CloudFlare ImgBed**，客户端只接收图床 https URL；上传通过一个**前端可见、可管理、持久化、带 429 退避和并发的队列**完成。

## 已确认的关键决策

| 决策点 | 结论 |
|--------|------|
| Q1 下载完成后上传的触发方式 | **方式 1**：后端后台轮询下载器 /api/jobs，发现新 state==done 的书 → 自动把该书全部评论图 + 封面入队上传。 |
| Q2 队列存放 | 放**项目自己的数据库/私有存储**（backend/data 下），持久化、断点续传、状态字段。 |
| Q3 头像“映射关系”来源 | **从本地解析找图像映射**（见下文“映射机制”）。 |
| Q4 封面上传时机 | 与评论图一样，**下载完成后一并上传**。 |
| 图像交付方式 | **不做本地解析给客户端**——只上传图床、返回图床 URL。 |
| URL 回退策略 | **不允许任何 URL 回退**：图床上传不了就不给图（宁可 429 排队），绝不退回本地路径或源站 URL。 |
| 429 处理 | 图床返回 429 时不放弃，读 Retry-After 进队列退避重试，不并发打爆图床。 |
| 头像上传交互 | (a) 走前端图像上传队列；(b) 前端 Web 页可**按章选择该章涉及的评论者头像**点击加入上传映射并上传，也支持**批量**。 |
| 是否二次下载 | **绝不**：所有评论正文图/头像/封面只从下载器已落盘的本地文件读取并上传图床；本地缺失即跳过，**禁止向网络或下载器二次下载**评论/媒体。 |

## 下载器落盘结构（映射的权威来源）

下载器书目录：<save_dir>/<book_id>/，其中 <save_dir> = ~/fqdownload/data/book（用户实测示例：~/fqdownload/data/book/7158058782700866560/）

| 路径 | 内容 |
|------|------|
| cover.jpg | 书籍封面（书目录根） |
| images/<sha1(url)>.<ext> | **全部评论头像 + 正文图**的扁平文件，按源 URL 的 sha1 命名（image_utils.rs 的 sha1_hex + ensure_cached_image） |
| segment_comments/<chapter_id>.json | 每章评论缓存，含 user.avatar 和 item.images[].url 原始 URL |
| status.json | 下载状态 |
| downloaded_chapters.jsonl | 已下载章节日志 |

### 映射机制

- **URL → 本地文件**：sha1(url) → images/<sha1(url)>.<ext>。
- **章节 → 头像**：解析 segment_comments/<chapter_id>.json，收集每条评论的 user.avatar URL，用 sha1(url) 定位本地文件。
- **内容去重**：images/ 按 URL 的 sha1 命名 → 同一图跨章/跨书只存一份、上传一次（天然去重）。
- **章节中引用的 URL**（segment_comments/*.json）可能不在 images/（未开启 download_comment_images/avatars 时）；这类 URL 直接跳过或按“不允许 URL 回退”原则不上传、不展示。

### 下载器媒体配置开关（Rust，src/book_parser/segment_comments.rs）
- cfg.download_comment_images —— 是否下载评论正文图
- cfg.download_comment_avatars —— 是否下载评论头像
- 两者都关时 prefetch_comment_media 直接返回（line 54）。

## 客户端（Legado-X）图片支持边界（现状已验证）

- 评论面板 CSP：img-src 'self' https: data:（SourceScopedWebController.kt）。
- canLoadSubresource：同源任意协议允许；跨源仅 https 公网允许，且跨源剥离 Authorization/Cookie（SourceScopedRequestPolicy.kt）。
- 头像 `<img>` 走 _review_avatar，正文图走 `<img class="comment-media">`（后端 reading_reviews.py）。
- 因此图床 **https 公网 URL** 客户端可直接加载（跨源 https，无鉴权需求）。

## 现状（执行前要保留/改造的点）

- backend/app/services/chapter_review_catalog.py 的 _enrich_review_media：已删除 fanqie_local 的 media strip 特例，改走通用**请求时同步上传 ImgBed**逻辑。**阶段 5 收敛**时改为“从队列取已上传 URL”，删掉请求时同步上传，更新测试与文档。
- backend/tests/test_chapter_review_catalog_regression.py：已新增两条测试（上传映射 + 图床关闭降级），阶段 5 按新架构重写。
- plugins/sources/official/fanqie_local/README.md：已更新媒体说明，阶段 5 复核。
- 前端已有「评论图片托管 / 启用评论图片上传」ImgBed 配置 UI（含 baseUrl/uploadChannel/uploadFolder/authCode/apiToken），指向 imgbed 配置；队列管理与头像选择页为**新增**。

## 验收标准

1. 下载器某书 state==done 后，后端自动把该书 images/* 全部文件 + cover.jpg 入队上传到图床。
2. 队列持久化在项目 DB；进程重启后从未完成任务继续。
3. 图床 429 时项目进入 rate_limited 状态，按 Retry-After 退避后自动重试，不丢弃、不并发打爆。
4. 前端队列页能实时看到：每个项目状态、正在上传的、并发数、429 等待。
5. 前端可**按章选择评论者头像**（来自 segment_comments/<chapter>.json 的映射），加入队列上传，支持批量。
6. 封面图床 URL 用于书籍列表/详情展示。
7. 客户端评论面板能显示图床 https 正文图与头像（跨源 https 加载）。
8. 无任何 URL 回退：图床不可用时不泄漏本地路径或源站 URL。
9. 绝不二次下载：已下载小说的评论/头像/正文图不再向网络或下载器重复下载；上传源只能是本地已落盘文件，缺失即跳过。

## 不做（本轮范围外）
- 不把评论正文/头像解析结果持久化到项目存储（章节解析落库另开）。
- 不改客户端 Legado-X 代码（只消费图床 https URL，已支持）。
- 不修改下载器 Rust 落盘逻辑。
