# 无 AI 订阅聚合方案

> 状态：规划收口版（v2，整合用户决策）
> 范围：`legado-hub` 订阅流程、聚合处理器、插件广告样本采集、敏感词词库、日志流、前端
> 前置：Phase A（WAL + 章节并行）已实施并验证，本文档取代 `subscription-throughput-optimization-plan.zh-CN.md` 的后续阶段
> 关联：`ai-aggregate-source-plan.md`（AI 聚合源原规划，本文档为其前置重构）
> 决策基线：直接重构不保留兼容路径、无旧数据迁移（dev 阶段）、AI 完全搁置到最后

---

## 1. 背景与目标

### 1.1 问题

当前订阅流程将 AI 校对深度耦合在章节处理的关键路径上：

```
fetch → purify(纯代码,0.1s) → AI校对(22s) → 写DB+文件
```

实测数据（919 章小说，deepseek-v4-flash，aiMaxConcurrency=4）：

| 指标 | 数值 |
|------|------|
| AI 校对耗时 | 16-30s/章（均值 22s），占单章 95% 时间 |
| 纯抓取耗时 | 2.7s/章 |
| 有效吞吐 | ~10s/章（受 deepseek API 侧限流） |
| 919 章预估 | ~2.5 小时 |
| AI 并发调参收益 | 2→4 仅提升 15-20%（API 侧瓶颈） |

**结论**：AI 是吞吐瓶颈，且 API 侧并发限流无法通过本地调参突破。

### 1.2 目标

将订阅流程重构为**完全无 AI 介入**的聚合管线，用纯代码完成大部分工作：

1. **免费章节**：官方源直接拉取完整正文 → 纯代码净化 → 写入本地
2. **VIP 章节**：官方预览存本地 → 遍历第三方候选源对齐校验 → 成功写入完整正文 / 失败保留预览
3. **广告水印**：从每个第三方插件站点采集样本，内置到插件中，净化时使用插件专属模式
4. **AI 增强**：作为独立后置任务，对已处理章节异步补充（最后阶段）

### 1.3 设计原则

| 原则 | 说明 |
|------|------|
| 官方源为基准 | 免费章直接用官方正文；VIP 章用官方预览做对齐基准 |
| 第三方源为补充 | 仅在 VIP 章节补全完整正文时使用，必须通过对齐校验 |
| 文件系统优先 | 章节正文和章节元数据（is_vip、字数、预览字数）存文件系统 |
| DB 最小化 | DB 只保留调度必需字段（status、next_retry_time、retry_count），不保留正文内容 |
| 官方源缺席则降级 | 没有官方源时不强行套免费/VIP 流程，保留第三方聚合校验路径 |
| 宿主管净化 | 广告净化由宿主 `_purify_content` 执行，但使用插件提供的广告模式 |
| 插件管站点特征 | 每个插件内置自己站点的广告水印样本模式，宿主不硬编码 |
| 处理一章即可读 | 每处理完一章立即写入文件系统并可见，不等批次完成 |
| 从第 1 章开始 | 默认处理顺序从章节索引 0 开始，除非用户显式指定起始位置 |
| 直接重构 | 不保留兼容/回退路径，不做旧数据迁移（dev 阶段） |
| 候选源发现阻塞初始化 | 订阅初始化阶段等待所有候选源搜索完成后再开始章节处理 |
| 字数校验 | 净化后正文长度与官方字数比对，容差下限 90%、上限 120% |
| AI 完全搁置 | AI 增强作为独立后置任务，在无 AI 订阅全流程稳定前不实施 |

---

## 2. 当前状态分析

### 2.1 已有基础设施

| 组件 | 位置 | 状态 | 复用程度 |
|------|------|------|----------|
| WAL + busy_timeout | `db.py:554`, `aggregate_processor.py:115` | 已启用 | 直接复用 |
| 章节并行 | `aggregate_processor.py:677` asyncio.gather+Sem(8) | 已启用 | 直接复用 |
| per-source 信号量 | `aggregate_processor.py:1438` Sem(2) | 已启用 | 直接复用 |
| `_purify_content` | `aggregate_processor.py:2610` | 正则去广告+去重标题 | 扩展：改用插件模式 |
| `align_candidate_chapter` | `aggregate_alignment.py` | 滑窗对齐 | 扩展：接入主路径 |
| `vip_chapter_preview` | qidian_com_app 插件 | VIP 预览 API | 直接复用 |
| `chapter()` 返回元数据 | qidian_com_app/web 插件 | is_vip, wordsCount, actualWords, previewOnly | 直接复用 |
| SharedBookStorage | `shared_book_storage.py` | 文件系统原子写入 | 扩展：chapter_index 加字段 |
| 预览重试机制 | `preview_retry_count` + `PREVIEW_RETRY_DELAYS_MINUTES` | 已实现 | 直接复用 |

### 2.2 缺失部分

| 缺失 | 影响 | 解决方式 |
|------|------|----------|
| `is_vip` 未存入文件系统 | 无法区分免费/VIP 章节 | chapter_index.json 每章条目加 `isVip` 字段 |
| `free_chapter_end_index` 未记录 | 无法快速判断免费边界 | metadata.json 加 `freeChapterEndIndex` |
| 主路径（Path 1）无对齐校验 | 第三方主源串书无法检测 | 所有第三方内容都过 `align_candidate_chapter` |
| `classify_source_content` 用 200 字硬编码 | 误判 VIP 预览为完整正文 | 改用插件元数据 `is_vip` + `previewOnly` 判断 |
| `_AD_PATTERNS` 全局硬编码 | 每个站点广告特征不同 | 改为插件提供 `ad_patterns`，宿主调用 |
| `processed_content` DB 字段存全文 | 写放大 + 存储浪费 | 无 AI 模式不写入，正文以 .md 文件为准 |
| AI 耦合在 `_process_full_content` | 22s/章瓶颈 | Step 2 整体移除，AI 作为独立后置任务 |

### 2.3 插件能力确认

| 能力 | qidian_com_app | qidian_com_web | 第三方插件 |
|------|----------------|----------------|------------|
| toc() 返回 is_vip | 是（sS 字段） | 是（sS 字段） | 视插件而定 |
| chapter() 返回完整正文 | 是（免费章） | 是（免费章） | 是（免费+VIP） |
| chapter() 返回预览 | 是（VIP 未购买） | 是（VIP 未购买） | 不适用 |
| vip_chapter_preview() | 是（专属 API） | 是（从 chapter 提取） | 不适用 |
| 返回 actualWords | 是 | 是 | 不适用 |
| 返回 previewOnly | 是 | 是 | 不适用 |
| chapter_reviews() | 是（App+Web fallback） | 是（仅公开评论） | 视插件而定 |

---

## 3. 数据存储设计

### 3.1 存储原则

**文件系统是正文和章节元数据的唯一权威来源**，DB 只存调度状态，不存正文全文。

```
DB（调度状态）          文件系统（正文+元数据）
─────────────          ──────────────────────
aggregate_chapter_tasks  library/<book>/
  status                   chapters/0001-title.md（正文+trace block）
  next_retry_time          chapter_index.json（每章元数据）
  retry_count              metadata.json（书级元数据+bookState）
  last_error_code
aggregate_book_tasks
  next_check_time
  interval_minutes
  status
```

### 3.2 chapter_index.json 扩展

当前结构（`schemaVersion: 1`）：

```json
{
  "schemaVersion": 1,
  "bookId": "aggregate_book_id",
  "chapters": [
    {"index": 0, "title": "第一章", "file": "chapters/0001-xxx.md", "status": "processed"}
  ]
}
```

扩展为 `schemaVersion: 2`：

```json
{
  "schemaVersion": 2,
  "bookId": "aggregate_book_id",
  "freeChapterEndIndex": 50,
  "chapters": [
    {
      "index": 0,
      "title": "第一章 免费标题",
      "file": "chapters/0001-xxx.md",
      "status": "processed",
      "isVip": false,
      "officialWordCount": 3200,
      "officialPreviewWords": null
    },
    {
      "index": 50,
      "title": "第五十一章 VIP标题",
      "file": "chapters/0051-xxx.md",
      "status": "processed",
      "isVip": true,
      "officialWordCount": 4081,
      "officialPreviewWords": 108,
      "sourceId": "69shuba_com",
      "sourceChapterId": "xxx",
      "alignedWith": "official_preview",
      "alignmentScore": 0.92
    }
  ]
}
```

新增字段说明：

| 字段 | 类型 | 说明 |
|------|------|------|
| `freeChapterEndIndex` | int | 最后一个免费章的 index（全书级，存于 chapters 同级） |
| `isVip` | bool | 该章是否为 VIP 章节（来自官方源 TOC） |
| `officialWordCount` | int | 官方源返回的完整章字数 |
| `officialPreviewWords` | int / null | 官方源返回的预览实际字数（仅 VIP 章） |
| `sourceId` | string | 实际提供正文的源 ID（官方或第三方） |
| `sourceChapterId` | string | 实际提供正文的源章节 ID |
| `alignedWith` | string | 对齐基准类型（`official_full` / `official_preview`） |
| `alignmentScore` | float | 对齐相似度分数 |

### 3.3 trace block 扩展

当前 trace block（嵌入 .md 文件末尾）：

```json
{
  "chapterIndex": 0,
  "chapterStatus": "processed",
  "previewOnly": false
}
```

扩展：

```json
{
  "chapterIndex": 0,
  "chapterStatus": "processed",
  "previewOnly": false,
  "isVip": false,
  "sourceId": "qidian_com_app",
  "sourceChapterId": "837504266",
  "officialWordCount": 3200,
  "officialPreviewWords": null,
  "alignedWith": "official_full",
  "alignmentScore": null,
  "purifiedBy": "plugin_ad_patterns",
  "adPatternsSource": "qidian_com_app"
}
```

### 3.4 DB 字段处理

| 表 | 字段 | 处理方式 |
|------|------|----------|
| `aggregate_chapter_tasks` | `processed_content` | 不再写入正文（留空），所有阅读/详情/重建入口改读 .md 文件 |
| `aggregate_chapter_tasks` | `source_word_count` | 语义明确为"实际正文源返回的字数" |
| `aggregate_chapter_tasks` | `preview_only` | 保留，但改由插件元数据驱动 |
| `aggregate_chapter_tasks` | AI 相关字段（ai_model 等） | 保留结构，无 AI 模式下不写入 |
| `aggregate_chapter_tasks` | 不新增 DB 列 | is_vip、official_word_count 等存文件系统 |

正文不再进入 DB 后，以下入口必须同步改读文件系统：

1. Legado 章节正文返回
2. 控制台章节详情正文预览
3. 共享书籍 `chapter_index.json` / `metadata.json` 重建
4. 前文上下文加载
5. 预览 fallback / AI 后置重试读取正文

### 3.5 状态体系与中文映射

状态分两层：DB 保留机器调度状态，文件/接口返回阅读状态和中文标签。中文映射在后端完成，前端只展示后端返回值。

| DB 调度状态 | 文件/阅读状态 | 中文标签 | 说明 |
|-------------|---------------|----------|------|
| `pending` / `placeholder` | `processing` | 处理中 | 已入队但未生成可读正文 |
| `processed` | `readable` | 可阅读 | 无 AI 正文已生成 |
| `fallback` + `previewOnly=true` | `fetched` | 预览 | 仅保留官方预览 |
| `fallback` + 第三方正文 | `supplemented` | 已补全 | 第三方正文已通过校验 |
| `fallback` + 校验存疑 | `suspect` | 存疑 | 有正文但可信度不足 |
| `error` | `failed` | 失败 | 当前重试周期处理失败 |
| AI 后置完成 | `proofread_complete` | 已校对 | 后置 AI 增强完成 |

后端接口统一返回 `status`、`statusLabel`、`statusDescription`，避免前端重复维护状态文案。

### 3.6 TOC 元数据传递

免费/VIP 分流依赖官方 TOC 元数据，不能只写到最终文件里。处理章节前必须能拿到：

| 字段 | 来源 | 用途 |
|------|------|------|
| `isVip` | 官方源 `toc()` | 判断免费章 / VIP 章 |
| `officialWordCount` | 官方源 TOC 或章节详情 | 判断预览是否短于完整字数 |
| `officialPreviewWords` | 官方 VIP 预览接口 | 记录预览长度 |
| `freeChapterEndIndex` | TOC 扫描计算 | 快速展示免费边界 |

这些字段可以存 `chapter_index.json`，也可以在处理前从 TOC 缓存读取；但不能只存在前端展示层。

---

## 4. 无 AI 订阅流程

### 4.1 总体流程

```
订阅初始化（阻塞，必须全部完成才能进入章节处理）
  │
  ├─ 官方源 toc() → 每章带 is_vip + wordCount
  ├─ 写入 chapter_index.json（含 isVip 字段）
  ├─ 记录 freeChapterEndIndex 到 metadata.json
  └─ 候选源搜索（所有源完成搜索后才继续）

章节处理（从第 1 章开始，并行 Semaphore(8)）
  │
  ├─ 免费章（isVip=false）
  │   ├─ 官方源 chapter() 拉完整正文
  │   ├─ _purify_content（使用官方源广告模式，通常无需去广告）
  │   ├─ 字数校验（净化后长度 vs officialWordCount，容差 90%-120%）
  │   ├─ 写 .md + 更新 chapter_index.json（立即可见）
  │   └─ status=processed
  │
  └─ VIP 章（isVip=true）
      ├─ 官方源 vip_chapter_preview() / chapter() 拉预览
      ├─ 预览文本立即写入 .md（带 preview 标记）
      ├─ 遍历第三方候选源（按优先级排序）：
      │   ├─ 第三方源 chapter() 拉正文
      │   ├─ _purify_content（使用该插件广告模式）
      │   ├─ align_candidate_chapter(官方预览, 第三方标题, 第三方正文, 官方标题)
      │   ├─ 字数校验（净化后长度 vs officialWordCount，容差 90%-120%）
      │   ├─ 对齐通过 + 字数通过 → 替换 .md 正文 → status=processed → 跳出循环
      │   └─ 对齐失败或字数不达标 → 换下一个源
      ├─ 全部源失败 → 保留预览 .md → status=fallback
      └─ 安排重试（PREVIEW_RETRY_DELAYS_MINUTES）
```

### 4.1.1 处理顺序

默认从章节索引 0（第一章）开始顺序处理。用户可在订阅时显式指定起始章节索引。

顺序处理的原因：
1. 用户想尽快看到第一章可读，而不是等 919 章全处理完
2. 前几章处理完即可开始阅读，后台继续追赶后续章节
3. 章节并行（Semaphore(8)）在一批内仍并行，但批与批之间按顺序推进

### 4.2 免费章节处理

```python
async def _process_free_chapter(self, catalog, chapter, official_source_id):
    """免费章节：官方源直接拉取完整正文。"""
    result = await catalog.chapter(chapter.source_chapter_id)

    content = result.get("content", "")
    if not content:
        return ChapterResult(status="error", error_code="empty_content")

    # 使用官方源广告模式净化（官方源通常无广告）
    ad_patterns = self._get_plugin_ad_patterns(official_source_id)
    purified = self._purify_content(content, ad_patterns=ad_patterns)

    # 字数校验（容差 90%-120%）
    if not self._validate_word_count(purified, chapter.official_word_count):
        return ChapterResult(status="error", error_code="word_count_mismatch")

    return ChapterResult(
        status="processed",
        content=purified,
        source_id=official_source_id,
        source_chapter_id=chapter.source_chapter_id,
        aligned_with="official_full",
    )
```

### 4.2.1 字数校验

```python
def _validate_word_count(self, content: str, official_word_count: int) -> bool:
    """净化后正文长度与官方字数比对，容差 90%-120%。"""
    if not official_word_count or official_word_count <= 0:
        return True  # 无官方字数则跳过校验
    actual = len(content.replace("\n", "").replace(" ", ""))
    lower = official_word_count * 0.9
    upper = official_word_count * 1.2
    return lower <= actual <= upper
```

字数校验失败的处理：
- 免费章：标记 `error`（`word_count_mismatch`），等下次重试
- VIP 章第三方源：跳过该源，尝试下一个候选源
- 容差可配置（`WORD_COUNT_TOLERANCE_LOWER=0.9`，`WORD_COUNT_TOLERANCE_UPPER=1.2`）

### 4.2.2 初始阶段策略：先日志后拒绝

初始实施阶段**只记录日志不拒绝**，收集实际偏差分布后再决定是否启用硬拒绝：

```python
def _validate_word_count(self, content: str, official_word_count: int, *, enforce: bool = False) -> bool:
    """字数校验。enforce=False 时只记录偏差不拒绝。"""
    if not official_word_count or official_word_count <= 0:
        return True
    actual = len(content.replace("\n", "").replace(" ", ""))
    lower = official_word_count * self._word_count_lower
    upper = official_word_count * self._word_count_upper
    passed = lower <= actual <= upper
    if not passed:
        deviation = actual / official_word_count if official_word_count else 0
        self._log_word_count_deviation(actual, official_word_count, deviation, passed)
        if not enforce:
            return True  # 初始阶段只记录不拒绝
    return passed
```

实施节奏：
1. **第一阶段**：`enforce=False`，记录 `word_count_deviation` 到 trace block + 日志流
2. **测试期**：分析日志中实际偏差分布，统计各源的偏差区间
3. **确定容差**：根据实测数据调整 `WORD_COUNT_TOLERANCE_LOWER/UPPER` 到合适值
4. **第二阶段**：`enforce=True`，启用硬拒绝

日志记录内容：
| 字段 | 说明 |
|------|------|
| `actual_length` | 净化后正文字符数 |
| `official_word_count` | 官方字数 |
| `deviation_ratio` | 实际/官方 比值 |
| `source_id` | 提供正文的源 ID |
| `chapter_index` | 章节索引 |
| `is_vip` | 是否 VIP 章 |

### 4.3 VIP 章节处理

```python
async def _process_vip_chapter(self, catalog, chapter, official_source_id, candidate_sources):
    """VIP 章节：官方预览 + 第三方对齐。"""

    # Step 1: 拉取官方预览，立即存本地
    preview = await self._fetch_official_preview(catalog, chapter, official_source_id)
    if not preview:
        return ChapterResult(status="error", error_code="no_preview")

    # 预览已写入 .md（即使后续全失败，预览不丢）

    # Step 2: 遍历第三方候选源
    for candidate in candidate_sources:
        try:
            result = await self._fetch_candidate_chapter(catalog, candidate, chapter)
            if not result or not result.get("content"):
                continue

            # 使用候选源插件的广告模式净化
            ad_patterns = self._get_plugin_ad_patterns(candidate.source_id)
            purified = self._purify_content(result["content"], ad_patterns=ad_patterns)

            # 对齐校验
            alignment = align_candidate_chapter(
                official_preview=preview["text"],
                candidate_title=result.get("title", ""),
                candidate_content=purified,
                expected_title=chapter.title,
            )

            if alignment["passed"]:
                # 字数校验
                if not self._validate_word_count(purified, chapter.official_word_count):
                    continue  # 字数不达标，换下一个源
                return ChapterResult(
                    status="processed",
                    content=purified,
                    source_id=candidate.source_id,
                    source_chapter_id=candidate.source_chapter_id,
                    aligned_with="official_preview",
                    alignment_score=alignment["score"],
                )
        except Exception:
            continue

    # Step 3: 全部源失败，保留预览
    return ChapterResult(
        status="fallback",
        content=preview["text"],
        source_id=official_source_id,
        source_chapter_id=chapter.source_chapter_id,
        preview_only=True,
    )
```

### 4.4 对齐校验接入主路径

当前 `align_candidate_chapter` 只在候选源补全路径（Path 2/3）使用。新流程中**所有第三方内容**（无论主源还是候选源）都要经过对齐校验：

| 内容来源 | 对齐基准 | 对齐方式 |
|----------|----------|----------|
| 官方免费正文 | 无需对齐 | 直接使用 |
| 官方 VIP 预览 | 自身即基准 | — |
| 第三方正文（用于 VIP 补全） | 官方 VIP 预览 | `align_candidate_chapter(official_preview, ...)` |

### 4.5 `classify_source_content` 重构

当前用 `length >= 200` 硬编码判断 full/preview。新版改为：

```python
def classify_source_content(content, *, is_vip, preview_only, source_word_count):
    """基于插件元数据判断内容类型，不靠字数猜。"""
    if not content:
        return "empty"
    if is_vip and preview_only:
        return "preview"
    if is_vip and not preview_only:
        return "full"  # 第三方源补全的 VIP 完整正文
    return "full"  # 免费章完整正文
```

### 4.6 无官方源降级

没有官方源时，不执行免费/VIP 分流，也不生成 `freeChapterEndIndex`。流程降级为第三方聚合：

1. 按主源优先级拉取章节正文
2. 使用标题、序号、字数和候选源交叉结果做基础校验
3. 校验通过写入 `readable`
4. 校验不足但有正文写入 `suspect`
5. 全部失败写入 `failed` 并按普通重试处理

这一路径不标记 `official_full` / `official_preview`，避免把第三方内容伪装成官方基准。

### 4.7 预览存储与重试

VIP 章预览**必须先写入 .md 文件**，再做第三方对齐。确保：

1. 进程重启后预览不丢失
2. 全源失败时预览仍可阅读
3. 重试时可重新拉取候选源（可能有新源加入）

重试策略复用现有机制：
- `preview_retry_count` + `PREVIEW_RETRY_DELAYS_MINUTES = [30, 60, 120, 240, 480]`
- 每次重试重新拉取候选源列表和官方预览
- 重试上限后标记为长期 fallback

### 4.8 候选源发现阻塞初始化

订阅初始化阶段必须等待**所有候选源搜索完成**后才能进入章节处理：

```
订阅初始化
  ├─ 官方源 toc() → 写 chapter_index.json
  ├─ 候选源搜索（所有第三方源并行搜索）
  │   ├─ source A → 找到 book_id_X
  │   ├─ source B → 找到 book_id_Y
  │   └─ source C → 未找到（跳过）
  └─ 搜索全部完成 → 写入 source-map → 进入章节处理
```

原因：
1. VIP 章处理依赖 source-map 知道哪些第三方源有此书
2. 如果边搜索边处理，可能错过刚发现的候选源
3. 初始化阶段是一次性阻塞，不影响后续追更

### 4.9 增量写入

每处理完一章立即写入文件系统，不等批次完成：

```python
async def _process_chapter_and_write(self, catalog, chapter):
    result = await self._process_chapter(catalog, chapter)
    # 立即写入单章 .md + 更新 chapter_index.json
    await self._write_single_chapter(chapter, result)
    return result
```

当前 `write_book_bundle` 是批量写入（所有章节一起写）。新版改为：
- `_write_single_chapter`：写入单章 .md 文件 + 原子更新 chapter_index.json 对应条目
- `rebuild_book_state_from_files`：每次单章写入后触发轻量更新（只更新该章条目 + 书级计数）

### 4.10 追更（新章节）流程

追更场景：已订阅的书有新章节更新。

```
追更检查（interval_minutes，默认 30 分钟）
  │
  ├─ 官方源 toc() → 对比已有 chapter_index.json
  ├─ 新增章节追加到 chapter_index.json
  ├─ 新章 isVip=true → 走 VIP 路径
  └─ 新章 isVip=false → 走免费路径
```

追更不重新搜索候选源（复用已有 source-map），除非用户手动触发 source-map 刷新。

---

## 5. 插件广告水印样本采集

插件广告模式是净化质量优化，不阻塞无 AI 订阅主链路。第一阶段可以继续使用现有全局回退模式；等免费/VIP 分流和文件状态稳定后，再逐插件采集和收敛。

### 5.1 问题

当前 `_AD_PATTERNS`（`aggregate_processor.py:2586`）是全局硬编码正则：

```python
_AD_PATTERNS = re.compile(
    r"(?im)^.*("
    r"最新网址|最新地址|最新域名|"
    r"本章未完|请收藏|"
    r"百度搜索|笔趣阁|"
    r"www\.|\.com|\.net|\.org"
    r").*$"
)
```

问题：
1. 不同站点广告特征不同，全局模式漏检率高
2. 误删正文中的合法 URL（`.com` 模式过于宽泛）
3. 新站点广告格式无法覆盖
4. 站点改版后广告格式变化无法跟踪

### 5.2 方案：插件内置广告模式

每个第三方插件内置自己站点的广告水印模式，宿主调用时获取。

#### 5.2.1 插件接口扩展

在 `metadata.yaml` 中声明：

```yaml
# metadata.yaml
ad_patterns:
  enabled: true
  # 模式来源：采集脚本自动生成 + 人工校验
  source: sampled  # sampled | manual | hybrid
  sampled_at: 2026-06-30
```

在 `source.py` 中导出：

```python
class Source:
    # 广告水印模式（从站点采集生成）
    AD_PATTERNS = [
        r"(?im)^.*最新网址.*$",
        r"(?im)^.*本章未完.*点击下一页.*$",
        # ... 站点专属模式
    ]

    # 水印特征（用于检测而非删除）
    WATERMARK_MARKERS = [
        "69shuba.com",
        "69书吧",
    ]

    def get_ad_patterns(self) -> list[str]:
        """返回该插件站点的广告水印正则模式列表。"""
        return self.AD_PATTERNS
```

#### 5.2.2 宿主调用

```python
def _get_plugin_ad_patterns(self, source_id: str) -> list[str]:
    """从插件获取广告模式，回退到全局模式。"""
    plugin = self._plugin_registry.get(source_id)
    if plugin and hasattr(plugin, "get_ad_patterns"):
        patterns = plugin.get_ad_patterns()
        if patterns:
            return patterns
    # 回退到全局模式（兼容未采集的插件）
    return _FALLBACK_AD_PATTERNS

def _purify_content(self, content: str, *, ad_patterns: list[str] = None) -> str:
    """使用指定广告模式净化内容。"""
    if ad_patterns is None:
        ad_patterns = _FALLBACK_AD_PATTERNS

    # 插件返回完整行级正则；宿主逐条编译和应用，避免二次拼接破坏正则语义。
    for pattern in ad_patterns:
        text = re.sub(pattern, "", text)
    # ... 其余净化步骤
```

### 5.3 采集流程

对每个第三方插件执行一次集体更新：

```
采集脚本（dev-assets/tools/ad_pattern_collector.py）
  │
  ├─ 读取 plugins/sources/thirdparty/ 下所有插件
  ├─ 对每个插件：
  │   ├─ 调用插件 search() 获取随机书籍列表
  │   ├─ 随机选 3-5 本书
  │   ├─ 调用 toc() 获取章节列表
  │   ├─ 随机选 5-10 章
  │   ├─ 调用 chapter() 获取正文
  │   ├─ 人工/自动识别广告水印行
  │   ├   ├─ 启发式：与正文无关的短行、重复出现的行、包含 URL 的行
  │   ├   ├─ 对比：同一章在不同源的正文差异
  │   ├   └─ 生成正则模式
  │   ├─ 写入插件的 ad_patterns.py 或 source.py
  │   └─ 更新 metadata.yaml（sampled_at, source=sampled）
  └─ 输出采集报告
```

#### 5.3.1 采集脚本设计

```python
# dev-assets/tools/ad_pattern_collector.py

async def collect_ad_patterns(plugin_id: str, sample_count: int = 5):
    """从插件站点采集广告水印样本。"""
    plugin = load_plugin(plugin_id)
    results = await plugin.search("随机关键词")

    samples = []
    for book in random.sample(results, min(3, len(results))):
        toc = await plugin.toc(book.book_id)
        chapters = random.sample(toc.chapters, min(10, len(toc.chapters)))

        for chapter in chapters:
            content = await plugin.chapter(chapter.chapter_id)
            ad_lines = extract_ad_lines(content)
            samples.extend(ad_lines)

    patterns = generate_regex_patterns(samples)
    write_ad_patterns_to_plugin(plugin_id, patterns)
    return CollectionReport(plugin_id, samples, patterns)
```

#### 5.3.2 广告行识别启发式

```python
def extract_ad_lines(content: str) -> list[str]:
    """启发式识别广告水印行。"""
    ad_lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # 特征1：包含 URL 或域名
        if re.search(r"https?://|www\.|\.\w{2,4}(?=\s|$|/)", stripped):
            ad_lines.append(stripped)
        # 特征2：短行 + 包含推广关键词
        elif len(stripped) < 50 and re.search(r"收藏|记住|网址|地址|域名|关注|扫码|下载", stripped):
            ad_lines.append(stripped)
        # 特征3：重复出现（跨章节比对时识别）
        # 特征4：与前后段落无语义连贯性
    return ad_lines
```

### 5.4 采集计划

| 阶段 | 内容 | 预计工作量 |
|------|------|------------|
| 采集脚本开发 | `ad_pattern_collector.py` + 启发式识别 | 1 天 |
| 首轮采集 | 20 个第三方插件 × 每个采样 5-10 章 | 自动化，~2 小时 |
| 人工校验 | 逐插件确认模式无误删 | 0.5 天 |
| 模式写入 | 生成 `ad_patterns.py` 或写入 `source.py` | 自动化 |
| 回归测试 | 用采集样本验证净化效果 | 0.5 天 |

### 5.5 第三方插件清单

当前 `plugins/sources/thirdparty/` 下 20 个插件：

```
0xs_net, 22biqu_com, 69hsw_com, 69shuba_com, 69shuba_tw,
96dushu_com, biquge365_net, dongtanxs_com, kks101_com, quanben5_com,
ranwen8_cc, shuhaige_net, sudugu_org, tianxibook_com, ttkan_co,
twkan_com, xbiqugu_la, xbiquzw_net, xhytd_com, xiaoshuohu_com
```

每个插件需要：
1. 采集脚本自动采样
2. 生成 `ad_patterns` 列表
3. 在 `source.py` 中导出 `get_ad_patterns()` 方法
4. 更新 `metadata.yaml` 中 `ad_patterns.enabled = true`

---

## 6. 敏感词词库

### 6.1 目的

第三方源正文可能包含被屏蔽的敏感词（如 `**` 掩码），需要在净化阶段恢复。无 AI 方案使用本地词库做 DFA/Trie 匹配检测，不做 AI 推测。

### 6.2 词库来源

内置 [konsheng/Sensitive-lexicon](https://github.com/konsheng/Sensitive-lexicon)（MIT 许可）：

| 文件 | 大小 | 说明 |
|------|------|------|
| `零时-Tencent.txt` | 716KB | 腾讯过滤词库（最大） |
| `网易前端过滤敏感词库.txt` | 114KB | 网易词库 |
| `非法网址.txt` | 219KB | 非法网址 |
| `GFW补充词库.txt` | 90KB | GFW 补充 |
| `涉枪涉爆.txt` | 8.8KB | 涉枪涉爆 |
| `色情词库.txt` | 7.6KB | 色情 |
| `反动词库.txt` | 5.9KB | 反动 |
| ... | | 共 17 个 .txt 文件 |

存储位置：`backend/data/lexicons/Sensitive-lexicon/`（目录已存在，当前为空）

### 6.3 集成方式

```python
# backend/app/services/sensitive_lexicon.py

class SensitiveLexicon:
    """敏感词词库管理 + DFA/Trie 匹配。"""

    def __init__(self, lexicon_dir: Path):
        self._trie = self._build_trie(lexicon_dir)

    def _build_trie(self, lexicon_dir: Path) -> dict:
        """从所有 .txt 文件构建 Trie 树。"""
        root = {}
        for txt_file in lexicon_dir.glob("*.txt"):
            for line in txt_file.read_text(encoding="utf-8").splitlines():
                word = line.strip()
                if word:
                    self._insert(root, word)
        return root

    def scan(self, text: str) -> list[tuple[int, str]]:
        """扫描文本，返回 [(位置, 匹配词)] 列表。"""
        ...

    def restore_masked(self, text: str) -> str:
        """恢复被 ** 掩码的敏感词（如果能精确匹配上下文）。"""
        ...
```

### 6.4 更新机制

| 方式 | 触发 | 说明 |
|------|------|------|
| 自动更新 | 定时任务（每日） | 从 GitHub raw 拉取最新 .txt 文件 |
| 手动更新 | 控制台设置页 | 用户点击"更新词库"按钮 |
| 增量更新 | 自动 | 对比文件 hash，只更新变化的文件 |

### 6.5 使用场景

1. **净化阶段**：`_purify_content` 调用 `sensitive_lexicon.scan(content)` 检测敏感词
2. **掩码恢复**：`sensitive_lexicon.restore_masked(content)` 尝试恢复 `**` 掩码（需上下文精确匹配）
3. **质量标记**：检测到掩码但无法恢复时，trace block 标记 `hasMaskedWords=true`
4. **AI 增强阶段**（后续）：AI 校对时传入敏感词检测结果作为提示

### 6.6 注意事项

- DFA/Trie 匹配是纯本地操作，无网络依赖，不影响订阅吞吐
- 词库加载到内存，首次加载 ~1-2 秒，后续缓存
- `restore_masked` 只在上下文足够精确时恢复，避免误恢复
- 词库更新不影响正在处理的章节，下一批处理时生效

---

## 7. AI 抽离

### 7.1 从 `_process_full_content` 移除 AI

当前 `_process_full_content`（`aggregate_processor.py:1669-1913`）三步：

```
Step 1: _purify_content (纯代码)
Step 2: AI processing (22s/章)     ← 移除
Step 3: write result (纯代码)
```

移除后：

```python
async def _process_full_content(self, catalog, chapter, ...):
    # Step 1: 抓取
    result = await self._fetch_chapter_content(catalog, chapter)

    # Step 2: 净化（纯代码，使用插件广告模式）
    ad_patterns = self._get_plugin_ad_patterns(result.source_id)
    purified = self._purify_content(result.content, ad_patterns=ad_patterns)

    # Step 3: 写入（纯代码）
    self._write_chapter_result(chapter, purified, status="processed")
```

### 7.2 AI 增强作为独立后置任务

AI 不再在订阅流程中执行，而是作为独立任务类型：

```
订阅流程（无 AI）
  → status=processed（纯代码净化完成）

AI 增强任务（独立调度）
  → 读取 status=processed 的 .md 文件
  → AI 校对（纠错、敏感词恢复、质量评分）
  → 更新 .md 文件 + trace block
  → status=proofread_complete
```

AI 增强任务特点：
- 独立调度，不阻塞订阅流程
- 可按优先级排序（追更书优先、积压书后续）
- 可暂停/恢复（不影响已 processed 的章节阅读）
- 失败不影响订阅状态
- token 用量独立统计

DB 新增任务类型（复用现有任务表或新增 `aggregate_ai_tasks` 表）：

```sql
-- 复用 aggregate_chapter_tasks，新增 ai_status 字段
-- 或新增独立表：
CREATE TABLE IF NOT EXISTS aggregate_ai_tasks (
    task_id TEXT PRIMARY KEY,
    aggregate_book_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    status TEXT DEFAULT 'pending',  -- pending/processing/done/skipped
    ai_model TEXT,
    ai_latency_ms INTEGER,
    ai_tokens INTEGER,
    created_at TEXT,
    processed_at TEXT
);
```

---

## 8. 实施步骤

> 决策基线：直接重构、无兼容路径、无旧数据迁移（dev 阶段）。AI 增强完全搁置到最后。

### Step 0：正文读取切到文件系统 + AI 抽离（合并）

| 改动 | 文件 | 说明 |
|------|------|------|
| 移除 `_process_full_content` Step 2 | `aggregate_processor.py:1687-1837` | AI 处理块整体移除，直接重构不保留 |
| `_get_ai_service` 返回 None | `aggregate_processor.py:1261` | 无 AI 模式下禁用 |
| `processed_content` 不写入 DB | `aggregate_processor.py:2309` | DB 正文留空，以 .md 文件为准 |
| Legago 章节返回读 .md | `aggregate_processor.py` | 不再依赖 `processed_content` |
| 控制台章节详情读 .md | `console.py` | 正文预览从文件读取 |
| 共享文件重建读 .md | `aggregate_processor.py` / `shared_book_storage.py` | DB 只提供状态和路径 |
| 前文上下文读 .md | `aggregate_processor.py` | 后续 AI 后置需要上下文时也不读 DB 正文 |

**验证**：服务启动、订阅一本书、确认章节无 AI 处理直接写入，阅读功能正常。

### Step 1：chapter_index.json 扩展 + 增量写入

| 改动 | 文件 | 说明 |
|------|------|------|
| schemaVersion 1→2 | `shared_book_storage.py` | 直接升版，不做 v1 兼容迁移 |
| 每章条目加 isVip/officialWordCount/officialPreviewWords | `aggregate_processor.py` | TOC 同步时写入 |
| metadata.json 加 freeChapterEndIndex | `aggregate_processor.py` | 书级元数据 |
| 新增 `_write_single_chapter` | `shared_book_storage.py` | 单章增量写入 .md + 更新 chapter_index.json |
| `write_book_bundle` 保留 | `shared_book_storage.py` | 用于批量初始化场景 |

**验证**：订阅后检查 chapter_index.json 包含新字段，单章处理完立即可在文件系统看到。

### Step 2：TOC 同步记录 is_vip + 候选源发现阻塞

| 改动 | 文件 | 说明 |
|------|------|------|
| TOC 同步读取 ChapterItem.is_vip | `aggregate_processor.py` | 从 toc 结果提取 |
| 计算并记录 freeChapterEndIndex | `aggregate_processor.py` | 最后一个 is_vip=false 的 index |
| 候选源搜索阻塞初始化 | `aggregate_processor.py` | 所有源搜索完成后才进入章节处理 |

**验证**：TOC 同步后检查 freeChapterEndIndex 正确，候选源全部完成后才开始处理章节。

### Step 3：免费章路径

| 改动 | 文件 | 说明 |
|------|------|------|
| 新增 `_process_free_chapter` | `aggregate_processor.py` | 官方源直接拉取+净化+字数校验+写入 |
| `run_book_task` 按 is_vip 分流 | `aggregate_processor.py` | 免费章走新路径 |
| 新增 `_validate_word_count` | `aggregate_processor.py` | 容差 90%-120% |

**验证**：免费章全部 processed，无 AI 调用，耗时 <3s/章，字数校验通过。

### Step 4：VIP 章路径

| 改动 | 文件 | 说明 |
|------|------|------|
| 新增 `_process_vip_chapter` | `aggregate_processor.py` | 预览存本地+遍历第三方对齐+字数校验 |
| 新增 `_fetch_official_preview` | `aggregate_processor.py` | 调用 vip_chapter_preview 或 chapter() |
| 预览先写 .md | `aggregate_processor.py` | 确保预览不丢 |
| 候选源遍历 + 对齐 | `aggregate_processor.py` | 复用 `align_candidate_chapter` |
| 全源失败 → fallback + 重试 | `aggregate_processor.py` | 复用现有重试机制 |

**验证**：VIP 章有第三方源时 processed，无源时 fallback 保留预览。

### Step 5：无官方源降级路径

| 改动 | 文件 | 说明 |
|------|------|------|
| 判断 aggregate 是否有官方源 | `aggregate_processor.py` | 有官方源才执行免费/VIP 分流 |
| 第三方-only 走旧聚合校验 | `aggregate_processor.py` | 不生成官方对齐标记 |
| 存疑正文标记 `suspect` | `aggregate_processor.py` | 有正文但缺少官方基准 |

**验证**：没有官方源的书仍能处理，不出现 fake official 字段。

### Step 6：`classify_source_content` 重构

| 改动 | 文件 | 说明 |
|------|------|------|
| 改用 is_vip + previewOnly 判断 | `aggregate_alignment.py` | 去掉 200 字硬编码 |

**验证**：VIP 预览不再被误判为完整正文。

### Step 7：插件广告模式采集

| 改动 | 文件 | 说明 |
|------|------|------|
| 开发采集脚本 | `dev-assets/tools/ad_pattern_collector.py` | 自动采样+生成模式 |
| 采集 20 个第三方插件 | `plugins/sources/thirdparty/*/source.py` | 每个插件导出 `get_ad_patterns()` |
| `_purify_content` 使用插件模式 | `aggregate_processor.py` | 按 source_id 获取模式 |
| 全局 `_AD_PATTERNS` 改为回退 | `aggregate_processor.py` | 仅在插件无模式时使用 |

**验证**：净化效果对比采集前后，无正文误删。

### Step 8：敏感词词库集成

| 改动 | 文件 | 说明 |
|------|------|------|
| 新增 `sensitive_lexicon.py` | `backend/app/services/sensitive_lexicon.py` | DFA/Trie 匹配 |
| 下载词库到 `backend/data/lexicons/` | 启动时自动下载 | 17 个 .txt 文件 |
| `_purify_content` 集成词库扫描 | `aggregate_processor.py` | 检测掩码 + 尝试恢复 |
| 控制台词库管理 | `console.py` + 前端设置页 | 手动更新按钮 |

**验证**：词库加载成功，掩码检测准确，恢复不误判。

### Step 9：日志流重设计

| 改动 | 文件 | 说明 |
|------|------|------|
| 新增实时日志流接口 | `console.py` + `ws` 或 `SSE` | tail -f 风格 |
| 每插件调用反馈 | `aggregate_processor.py` | 显示 source_id + 耗时 + 结果 |
| 处理进度清晰化 | `aggregate_processor.py` | 当前章/总章 + 阶段（TOC/免费/VIP/对齐） |

**验证**：控制台日志流实时显示每章处理状态和插件调用详情。

### Step 10：前端重设计

| 改动 | 文件 | 说明 |
|------|------|------|
| 订阅页面重设计 | `frontend/src/` | 新流程适配 |
| 订阅搜索页面重设计 | `frontend/src/` | 候选源发现可视化 |
| 书架/图书馆 UI 重设计 | `frontend/src/` | 章节状态展示（可阅读/预览/存疑/失败） |
| 书籍详情页重设计 | `frontend/src/` | 免费/VIP 边界展示 + 章节状态 |
| 日志组件 | `frontend/src/` | 后端风格实时日志流组件 |

**验证**：前端全流程可用，状态展示与后端一致。

### Step 11：AI 增强独立任务（最后）

| 改动 | 文件 | 说明 |
|------|------|------|
| 新增 AI 增强任务类型 | 新文件 `aggregate_ai_enhancer.py` | 独立调度器 |
| 读取 processed 章节 → AI 校对 → 更新 | `aggregate_ai_enhancer.py` | 后置异步 |
| 控制台 AI 增强管理 | `console.py` + 前端 | 进度/配置/统计 |

**验证**：AI 增强不阻塞订阅流程，可独立暂停/恢复。

---

## 9. 预期效果

### 9.1 吞吐提升

| 场景 | 当前（含 AI） | 无 AI 方案 | 提升 |
|------|---------------|------------|------|
| 免费章（919 章） | ~2.5 小时（22s/章） | ~40 分钟（2.7s/章） | ~4x |
| VIP 章（有第三方源） | ~2.5 小时 | ~5 分钟（2.7s/章 + 对齐 0.1s） | ~30x |
| VIP 章（无第三方源） | ~2.5 小时 | ~3 分钟（仅拉预览 0.1s/章） | ~50x |
| 10 本积压 × 5000 章 | ~25 小时 | ~4 小时 | ~6x |

### 9.2 架构改善

| 指标 | 当前 | 无 AI 方案 |
|------|------|------------|
| AI 依赖 | 强耦合在关键路径 | 完全解耦，独立后置 |
| 外部 API 故障影响 | 订阅流程阻塞 | 不影响订阅，仅 AI 增强延迟 |
| DB 写入量 | 每章 3 次（含 processed_content 全文） | 每章 1-2 次（无全文） |
| 进程重启恢复 | AI 中断的章节需重做 | 预览已存本地，不丢 |
| 可调试性 | AI 输出黑盒 | 纯代码净化可追踪 |
| 首章可读时间 | 等整批处理完 | 处理完第一章即可读 |

---

## 10. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 第三方源串书 | VIP 章写入错误内容 | `align_candidate_chapter` 对齐校验 + 字数校验，不通过换源 |
| 广告模式误删正文 | 净化后内容缺失 | 完整性检查（缩减 >50% 回退）+ 人工校验采集模式 |
| 官方预览字数过短 | 对齐置信度低 | 降低 `PREVIEW_MIN_LENGTH`，多源交叉验证 |
| 第三方源全部失败 | VIP 章无完整正文 | 保留预览 + 延迟重试，不影响其他章节 |
| 字数校验误判 | 合理内容被拒绝 | 容差可配置（默认 90%-120%），可按源调整 |
| 候选源搜索超时 | 初始化阻塞过久 | 每源搜索超时限制，超时源跳过不阻塞 |
| 敏感词词库误恢复 | 上下文不精确导致错误恢复 | `restore_masked` 只在精确匹配时恢复，否则标记不恢复 |
| 无旧数据迁移 | 现有订阅数据不可用 | dev 阶段决策，重新订阅即可 |

---

## 11. 日志流重设计

### 11.1 目标

当前处理日志过于笼统，用户无法看到每章处理的实时状态和插件调用详情。改为 tail -f 风格的实时日志流。

### 11.2 日志内容

每条日志包含：

| 字段 | 说明 |
|------|------|
| `timestamp` | 精确到毫秒 |
| `bookId` | 书籍 ID |
| `chapterIndex` | 章节索引 |
| `chapterTitle` | 章节标题 |
| `stage` | 阶段（`toc_sync` / `candidate_search` / `free_chapter` / `vip_preview` / `vip_align` / `write`） |
| `sourceId` | 插件 ID |
| `action` | 动作（`fetch` / `purify` / `align` / `validate` / `write`） |
| `result` | 结果（`success` / `fail` / `skip` / `fallback`） |
| `durationMs` | 耗时 |
| `detail` | 详情（错误信息、对齐分数、字数等） |

### 11.3 接口

```
GET /api/subscribe/books/{id}/logs/stream   # SSE 实时流
GET /api/subscribe/books/{id}/logs?limit=100  # 历史日志
```

### 11.4 前端展示

后端风格日志流组件：
- 自动滚动到底部
- 按 stage 着色
- 可过滤 sourceId / result
- 显示进度条（当前章/总章）

---

## 12. 前端重设计

### 12.1 范围

| 页面 | 改动 |
|------|------|
| 订阅页面 | 新流程适配：初始化阶段展示（TOC 同步 + 候选源搜索进度） |
| 订阅搜索页面 | 候选源发现可视化：每个源搜索状态 + 结果 |
| 书架/图书馆 | 章节状态展示：可阅读/预览/存疑/失败 计数 |
| 书籍详情页 | 免费/VIP 边界展示 + 每章状态标签 + 字数信息 |
| 日志组件 | 后端风格实时日志流（§11） |
| 设置页 | 敏感词词库管理（更新按钮 + 版本信息） |

### 12.2 状态展示

前端只展示后端返回的 `statusLabel` + `statusDescription`，不自行维护状态文案（§3.5）。

---

## 13. 术语表

| 术语 | 说明 |
|------|------|
| 免费章 | 官方源 `is_vip=false` 的章节，可直接拉取完整正文 |
| VIP 章 | 官方源 `is_vip=true` 的章节，未购买仅有预览 |
| 官方预览 | VIP 章在官方源未购买时返回的开头部分文本 |
| 对齐校验 | 用官方预览作为基准，验证第三方源正文是否为同一章节内容 |
| 串书 | 第三方源返回了错误章节的内容（书库错配） |
| 广告模式 | 从插件站点采集的广告水印正则表达式列表 |
| AI 增强 | 独立于订阅流程的后置 AI 校对任务（纠错、敏感词恢复等） |
| trace block | 嵌入 .md 文件末尾的 JSON 元数据块 |
