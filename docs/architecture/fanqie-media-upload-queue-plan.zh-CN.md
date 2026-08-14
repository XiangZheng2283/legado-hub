# fanqie 评论媒体上传队列 —— 详细执行计划

- 日期：2026-08（对话定稿）
- 关联需求：fanqie-media-upload-queue-requirement.zh-CN.md
- 执行方式：分阶段实现，每阶段跑对应验证；全部完成后跑 verify.ps1 全量门禁。

## 术语
- **下载器 / dl**：番茄本地下载器（Rust，18423），接口 /api/jobs、/api/library、/api/status。
- **图床 / ImgBed**：CloudFlare ImgBed 上传服务（backend/app/services/imgbed.py 已实现 upload()）。
- **队列项**：一次图床上传的最小单位 = {本地文件, 元数据映射}。

## 依赖现状（执行前已知）
- 图床上传已实现：backend/app/services/imgbed.py（ImgBedConfig、ImgBedUploader.upload(data, mime_type, filename)、get_imgbed_uploader、is_trusted_imgbed_url）。**当前无 429 处理、无持久化、无并发限制、无前端可见性。**
- 下载器媒体落盘：<save_dir>/<book_id>/{cover.jpg, images/<sha1(url)>.ext, segment_comments/<chapter>.json, status.json}，其中 <save_dir> = ~/fqdownload/data/book。
- 客户端只收图床 https URL（SourceScopedWebController.kt / SourceScopedRequestPolicy.kt 已确认）。
- 后端 DB：backend/app/storage/db.py（sqlite，initialize_database）。已有 search_jobs、subscription_search_jobs 等表可参考建表风格。
- 后端后台任务：backend/app/main.py lifespan 启动后台任务（参考 SearchJobService 清理）。

## 阶段 1 —— 后端持久化媒体上传队列服务

### 1.1 新文件：backend/app/services/media_upload_queue.py
实现 MediaUploadQueueService，核心职责：持久化、429/退避、并发限制、去重、断点续传、状态查询。

### 1.2 DB 表（加到 backend/app/storage/db.py 的建表流程）
表 media_upload_queue：
- id INTEGER PRIMARY KEY AUTOINCREMENT
- book_id TEXT NOT NULL           -- 下载器书 ID
- kind TEXT NOT NULL              -- 'avatar' | 'content' | 'cover'
- source_url TEXT                 -- 原始 URL（可空，cover 无）
- local_path TEXT NOT NULL        -- 本地文件绝对路径（save_dir 下）
- ref TEXT                        -- EPUB 相对引用或 sha1 文件名（去重键之一）
- status TEXT NOT NULL            -- 'queued' | 'uploading' | 'done' | 'failed' | 'rate_limited'
- attempts INTEGER DEFAULT 0
- retry_after_seconds INTEGER     -- 429 退避秒数
- next_retry_at TEXT              -- ISO 时间，rate_limited 时下次可重试时间
- uploaded_url TEXT               -- 图床返回的 https URL（成功时）
- error TEXT
- created_at / updated_at TEXT
索引：idx_media_q_book (book_id)、idx_media_q_status (status, next_retry_at)。

### 1.3 核心逻辑
- enqueue_book(book_id, save_dir)：扫描 save_dir/images/* + save_dir/cover.jpg，为每个文件计算去重键（sha1 文件名或 source_url），已存在同键 done/uploading 则跳过，否则插入 queued。
- enqueue_ref(book_id, save_dir, kind, source_url)：单个入队（前端按章选头像用）。
- worker 主循环：后台 asyncio 任务，限并发 N（配置，默认 4）；取 status='queued' 或 (status='rate_limited' 且 next_retry_at<=now) 的任务，置 uploading，调 get_imgbed_uploader().upload(...)，成功置 done+uploaded_url，失败区分 429（读 Retry-After → rate_limited + 退避）与其它（failed + error）。
- 进程启动时把遗留 uploading 重置为 queued（断点续传）。
- 配置：并发数、是否启用，从 app_config.json / AppConfig 读取（复用 imgbed 配置）。

### 1.4 单元测试：backend/tests/test_media_upload_queue.py
- enqueue_book 去重（同图两次只一条）；
- worker 429 → rate_limited + next_retry_at 在 Retry-After 之后，不并发超限；
- 上传成功 → done + uploaded_url；
- 启动重置 uploading → queued；
- 图床关闭/数据非法 → failed 且不泄漏本地路径到 uploaded_url。

### 阶段 1 验证
python -m pytest tests/test_media_upload_queue.py -q（backend/ 下）。

## 阶段 2 —— 下载完成自动入队（Q1=方式1）

### 2.1 后台轮询器（backend/app/services/download_watcher.py 或并入 media_upload_queue）
- asyncio 后台任务，周期（默认 10s）拉下载器 /api/jobs?all=true，找 state=='done' 且“新发现”的书（记录已处理集合，持久化到 DB 去重）。
- 对每个新 done 书：读 /api/status 拿 save_dir → MediaUploadQueueService.enqueue_book(book_id, save_dir)。
- 处理记录表（可加列或内存+DB）：book_id + 完成时间戳，避免重复入队。

### 2.2 配置
- 下载器 base URL（复用 fanqie_local 的 TOMATO_BASE / FANQIE_LOCAL_BASE）与是否启用自动入队。

### 2.3 测试
- 用假下载器响应（monkeypatch fetch）验证：done 书 → enqueue 全部 images + cover；重复 done 不重复入队。

### 阶段 2 验证
python -m pytest tests/test_download_watcher.py -q。

## 阶段 3 —— API 端点

### 3.1 队列管理（backend/app/api/console.py 或独立 router）
- GET /api/admin/media-queue —— 状态列表（分页、按 book_id/status 过滤）。
- GET /api/admin/media-queue/stats —— 统计：queued/uploading/done/failed/rate_limited 计数、当前并发。
- POST /api/admin/media-queue/{id}/retry —— 单个重试（failed/rate_limited → queued）。
- POST /api/admin/media-queue/retry-failed —— 批量重试失败项。
- POST /api/admin/media-queue/book/{book_id}/enqueue —— 手动对某书重新入队（扫描本地文件）。
- DELETE /api/admin/media-queue/{id} —— 删除项。

### 3.2 每章头像引用（供前端勾选）
- GET /api/admin/media-queue/book/{book_id}/chapters/{chapter_id}/avatars —— 解析 save_dir/segment_comments/<chapter_id>.json，返回该章评论者头像清单 [{userName, source_url, local_path, ref, already_uploaded_url?}]。
- POST /api/admin/media-queue/avatars —— body 传入选中的 {book_id, source_url[]}，逐个 enqueue_ref(kind='avatar')。

### 3.3 封面
- 封面随 enqueue_book 一起入队（kind='cover'）；书籍列表/详情展示时优先用 media_upload_queue 中该 book 的 cover uploaded_url（若无则维持现状）。

### 阶段 3 验证
用 FastAPI TestClient 测各端点：状态、统计、重试、每章头像清单、入队。

## 阶段 4 —— 前端队列管理页 + 头像选择/批量上传

### 4.1 新页面（frontend/src，Vite+React19+shadcn/ui）
「媒体上传队列」页：
- 统计卡：queued / uploading / done / failed / rate_limited 计数 + 当前并发。
- 列表：每项 book_id、kind、status、进度（attempts）、429 等待倒计时、uploaded_url（可复制）。
- 操作：单条重试、批量重试失败、删除、按状态过滤、按书过滤。
- 自动刷新（轮询 stats + list）。

### 4.2 头像选择/批量上传 UI
- 选择书 → 选章节 → 显示该章评论者头像清单（来自阶段 3.2 API）→ 勾选/全选 → 批量入队上传。
- 显示已在队列/已上传状态。

### 4.3 前端测试与构建
- 组件单测（vitest）、npm run lint、npm run build。

### 阶段 4 验证
npm run build（backend serving frontend/dist）+ 手动/组件验证新页面。

## 阶段 5 —— 收敛：让评论渲染消费队列结果

### 5.1 改造 _enrich_review_media（backend/app/services/chapter_review_catalog.py）
目标：删除“请求时同步上传 ImgBed”。改为：fanqie_local（与其它源）评论媒体的 URL 从 media_upload_queue 的 uploaded_url 取；若该项尚未上传，则入队（enqueue_ref）并**返回空 media**（或不阻塞），由队列异步补齐，后续请求再读到 URL。
- avatarRef/imageRefs（EPUB 相对引用）→ 查队列（ref 或 sha1 键）→ uploaded_url。
- 未上传/不可用时：不输出任何 URL（符合“不允许 URL 回退”）。
- 图床已启用但项 pending：可返回空并记录，客户端该评论暂时无图，队列完成后刷新可见。

### 5.2 更新测试
- backend/tests/test_chapter_review_catalog_regression.py：改为“fanqie 媒体已在队列 done → 返回图床 URL；未上传 → 空”。
- 新增：队列 done 后评论渲染含图床 URL 的测试。

### 5.3 更新文档
- plugins/sources/official/fanqie_local/README.md：媒体改为“经队列上传图床”。
- 本文档状态改为已完成。

### 阶段 5 验证
python -m pytest tests/test_chapter_review_catalog_regression.py tests/test_media_upload_queue.py -q。

## 全量门禁
完成后在 repo 根执行 verify.ps1（按 AGENTS.md），并跑 backend pytest 全量 + 前端 build/lint。

## 风险与注意
- 下载器 images/ 与 EPUB 内引用都可用作映射；优先直接用 save_dir 松散文件（枚举 images/* + cover.jpg），EPUB 相对引用（OEBPS/images/...）用于评论渲染时反查队列。两套命名需在 enqueue 时统一 ref/去重键。
- 队列项须能反查评论：评论来源是 EPUB 解析（avatarRef=OEBPS/images/...），而 save_dir 文件名为 sha1(url)；需在入队 cover/content 时同时记录 source_url 与 ref 两种键，或建 ref↔sha1 映射，阶段 5 才能命中。
- 不泄漏本地路径：所有返回给前端/客户端的 URL 只能是图床 https；local_path 只在管理后端内部使用，API 返回时转成相对标识或脱敏。
- 下载器轮询与图床上传并发都要有上限，防止打爆 18423 或图床。
## 落地后预期结果（最终交付态）

1. **自动入队**：下载器某书 state==done → 后台轮询自动发现 → 把该书 <save_dir>/<book_id>/images/* 全部文件 + cover.jpg 入队上传图床 → 各项转为 done 并持图床 https uploaded_url。
2. **前端可见可控**：队列页实时显示每项状态、正在上传、并发数、429 等待倒计时；支持单条/批量重试失败、删除、按状态/书过滤。
3. **评论媒体交付**：评论正文图与头像渲染时从队列取图床 URL；对应项尚未上传完成时该评论暂时无图（不泄漏本地路径/源站 URL），队列完成后刷新可见。
4. **封面上传**：封面图床 URL 用于书籍列表/详情展示。
5. **每章头像选择/批量上传**：前端按书选章节 → 显示该章评论者头像清单（segment_comments/<chapter>.json 映射）→ 勾选/全选批量入队上传。
6. **客户端可显示**：Legado-X 评论面板通过跨源 https 加载图床正文图与头像（无需鉴权头）。
7. **持久化 + 断点续传**：队列存项目 DB；进程重启后从 queued 继续，遗留 uploading 重置为 queued。

## 约束项（必须满足，不满足即视为缺陷）

1. **绝不 URL 回退**：图床不可用/未上传 → 不返回本地路径或源站 URL；宁可该评论无图。
2. **429 退避**：图床返回 429 读 Retry-After → rate_limited 退避后重试；**不并发打爆图床**（并发有上限）。
3. **不泄漏本地路径**：所有对外（前端/客户端）URL 只能是图床 https；local_path 仅在管理后端内部使用，API 返回脱敏。
4. **ref↔sha1 双键映射**：EPUB 相对引用（OEBPS/images/...）↔ images/<sha1(url)>.ext 必须能互相命中，否则阶段 5 评论渲染命中不了队列。
5. **内容去重**：同图跨章/跨书只传一次（sha1 命名天然去重）。
6. **并发/轮询上限**：下载器轮询与图床上传并发都要有上限，防打爆 18423 或图床。
7. **图床配置与降级**：复用现有 imgbed 配置（enabled/baseUrl/uploadChannel/uploadFolder/authCode/apiToken）；未启用时优雅降级——评论仍有文字，不上传/不展示本地图。
8. **作用域边界**：不改客户端 Legado-X；不改下载器 Rust 落盘；评论解析结果不落库到项目存储（另开）。
10. **绝不二次下载**：上传源只能是下载器已落盘的本地文件（<save_dir>/<book_id>/images/*、cover.jpg、segment_comments/*.json）；本地缺失即跳过该 URL，禁止向网络或下载器二次下载评论/头像/正文图。
9. **阶段 5 收敛**：删除请求时同步上传 ImgBed 逻辑，`_enrich_review_media` 改为从队列取 URL；相关测试重写。

