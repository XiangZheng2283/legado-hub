# AI 聚合源后端 — 全量开发报告

> 日期：2026-06-14
> 状态：后端功能完整，前端 4 页面已构建
> 测试：125 个全部通过

---

## 一、总体架构

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (React 19 + shadcn/ui + react-query)              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │
│  │ Settings │ │Bookshelf │ │Book Det. │ │Chapter Det.   │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬────────┘  │
└───────┼────────────┼────────────┼───────────────┼───────────┘
        │            │            │               │
┌───────┼────────────┼────────────┼───────────────┼───────────┐
│  Console API (FastAPI)                                      │
│  /aggregate-settings  /aggregate-books  /aggregate-chapters │
└───────┬────────────┬────────────┬───────────────┬───────────┘
        │            │            │               │
┌───────┼────────────┼────────────┼───────────────┼───────────┐
│  Service Layer                                              │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────┐│
│  │ SettingsRepo │ │  Processor   │ │ AggregateAIService   ││
│  │ (encrypted)  │ │ (state mach.)│ │ (official/preview/tp)││
│  └──────────────┘ └──────┬───────┘ └──────────────────────┘│
│  ┌──────────────┐ ┌──────┴───────┐ ┌──────────────────────┐│
│  │  Alignment   │ │  Reviews     │ │  Lexicon Scanner     ││
│  │  (classify+  │ │  (normalize+ │ │  (trie-based masked  ││
│  │   match)     │ │   fetch)     │ │   word detection)    ││
│  └──────────────┘ └──────────────┘ └──────────────────────┘│
└─────────────────────────────────────────────────────────────┘
        │
┌───────┼─────────────────────────────────────────────────────┐
│  AI Layer (backend/app/ai/)                                 │
│  client.py (httpx)  compat.py  request_builder.py           │
│  models_catalog.py (30+ models)  encryption.py (Fernet)     │
│  lexicon.py (Trie scanner)                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、文件清单

### 新增文件（22 个）

| 文件 | 行数 | 说明 |
|------|------|------|
| `backend/app/ai/client.py` | 174 | httpx 异步 OpenAI 兼容客户端 |
| `backend/app/ai/encryption.py` | 58 | Fernet 对称加密 |
| `backend/app/ai/lexicon.py` | 198 | Trie 敏感词扫描器 |
| `backend/app/services/aggregate_alignment.py` | 242 | 章节分类 + 跨源对齐 + 偏差值 |
| `backend/app/services/aggregate_ai_service.py` | 195 | AI 聚合服务骨架 |
| `backend/app/services/aggregate_settings.py` | 190 | 设置仓库（加密 + 脱敏） |
| `backend/app/services/aggregate_reviews.py` | 117 | 热评 normalize + bubble label |
| `backend/tests/test_ai_client.py` | 251 | 17 个 AI 客户端测试 |
| `backend/tests/test_lexicon.py` | 162 | 16 个敏感词扫描测试 |
| `backend/tests/test_retry_logic.py` | 230 | 19 个重试/退避测试 |
| `backend/tests/test_aggregate_alignment.py` | 176 | 21 个对齐 + 偏差值测试 |
| `backend/tests/test_aggregate_ai_service.py` | 189 | 10 个 AI 服务测试 |
| `backend/tests/test_aggregate_settings.py` | 105 | 5 个设置 + 加密测试 |
| `backend/tests/test_aggregate_reviews.py` | 96 | 5 个热评测试 |
| `backend/tests/test_aggregate_processor_state_machine.py` | 510 | 17 个状态机测试 |
| `frontend/src/routes/AggregateSettingsPage.tsx` | ~350 | 聚合设置页 |
| `frontend/src/routes/AggregateBookshelfPage.tsx` | ~250 | 聚合书架页 |
| `frontend/src/routes/AggregateBookDetailPage.tsx` | ~300 | 书详情页 |
| `frontend/src/routes/AggregateChapterDetailPage.tsx` | ~350 | 章节详情页 |
| `docs/devlog-ai-aggregate.md` | ~210 | 开发日志 |

### 修改文件（8 个）

| 文件 | 改动 |
|------|------|
| `backend/app/api/console.py` | test-provider / fetch-models 接入真实客户端；章节详情 JOIN 修复；热评真实抓取 |
| `backend/app/services/aggregate_processor.py` | 四路径状态机 / ai_service 注入 / TOC 缓存 / 前文校准 / 偏差值 / 主源优先级 / TOC diff |
| `backend/app/services/aggregate_virtual_source.py` | `primary_book_id_from_payload` 支持 `source_priority` 参数 |
| `backend/app/ai/models_catalog.py` | 3 → 30+ 模型 |
| `backend/app/storage/db.py` | schema + ensure_current_schema 增量补列 |
| `backend/tests/test_aggregate_processor.py` | +主源优先级测试 / monkeypatch 修复 |
| `frontend/src/App.tsx` | +4 条路由 |
| `frontend/src/components/layout/Layout.tsx` | +2 个导航项 |
| `frontend/src/lib/api.ts` | +14 个 API 方法 |

---

## 三、后端功能完成度

| 功能 | 状态 | 说明 |
|------|------|------|
| 设置持久化 | ✅ | contentWorkflow + aiProviderConfig，脱敏 key 不覆盖真实 key |
| API Key 加密 | ✅ | Fernet，密钥自动生成或从环境变量读取，兼容旧明文 |
| AI 客户端 | ✅ | httpx 异步 POST / GET，auth/timeout/错误分类 |
| 请求构建器 | ✅ | thinkingLevel / compat / DeepSeek/OpenRouter/Qwen 格式 |
| 模型目录 | ✅ | 30+ 模型，覆盖主流 provider |
| 连通性测试 | ✅ | 真实 HTTP 请求 /models |
| 模型列表拉取 | ✅ | 只需 baseUrl + apiKey，不要求 model |
| 章节分类 | ✅ | full / preview / empty |
| 跨源对齐 | ✅ | 标题相似 + 滑动窗口 preview（autojunk=False 修复中文） |
| 偏差值校验 | ✅ | LCS 相似度，低于阈值自动 fallback |
| 敏感词扫描 | ✅ | Trie 掩码检测，接入 AI prompt |
| 前文校准 | ✅ | 前 3 章已处理内容传入 AI prompt |
| 处理状态机 | ✅ | 官方完整 / preview+候选+AI / 第三方主源 / fallback |
| 重试退避 | ✅ | 5 级递增延迟，AI_BAD_REQUEST 不重试 |
| 终态章节排除 | ✅ | retry_count≥5 / AI_BAD_REQUEST 不再入队 |
| Fallback 阅读 | ✅ | status='fallback' 也返回正文 |
| 主源优先级 | ✅ | 可配置有序列表，先匹配后降级 |
| TOC 同步 | ✅ | diff 检测新增/变更/移除章节 |
| 热评抓取 | ✅ | 通过 plugin chapter_reviews 真实获取 |
| 占位文案 | ✅ | 固定 "聚合处理中……请先查看其他源或稍后刷新。" |
| 章节目录 | ✅ | 每轮最多 5 章，processed/fallback 不重复处理 |
| 评论结构 | ✅ | chapterEndHot / chapterEnd / authorReviews / hotParagraphReviews / paragraphs |
| 热评气泡 | ✅ | "热评 N"（非 "起点热评 N"） |

---

## 四、前端页面完成度

| 页面 | 路由 | 功能 |
|------|------|------|
| 聚合设置 | `/console/aggregate-settings` | AI Provider 配置 + 测试连通 + 拉模型 + 工作流开关 + 主源优先级列表 |
| 聚合书架 | `/console/aggregate-books` | 书籍列表 + 分页 + 状态筛选 + 进度条 + 操作按钮 |
| 书详情 | `/console/aggregate-books/:bookId` | 章节列表 + 状态标签 + 偏差值 + 重试 + 搜索 |
| 章节详情 | `/console/aggregate-books/:bookId/chapters/:chapterId` | 正文预览 + alignment + AI 信息 + fallback + 热评 |

---

## 五、测试覆盖

| 测试文件 | 数量 | 覆盖 |
|------|------|------|
| test_aggregate_processor.py | 11 | enqueue / toc / placeholder / 5 窗口 / 跳过 / 主源优先级 |
| test_aggregate_processor_state_machine.py | 17 | preview 不 processed / fallback 返回 / 第三方不 official / AI 调用 / AI 失败 fallback / 偏差值 / TOC 缓存 / 前文校准 / _is_official |
| test_aggregate_alignment.py | 21 | classify / title_sim / sliding_window / align / build_json / deviation_score |
| test_aggregate_ai_service.py | 10 | official_full / with_candidates / third_party / 未配置 / prompt 禁止凭空 / lexicon / 前文上下文 |
| test_aggregate_settings.py | 5 | 迁移 / 脱敏 / 加密 / 旧明文兼容 |
| test_aggregate_reviews.py | 5 | normalize / contract / bubble label |
| test_ai_client.py | 17 | config / chat / list_models / connectivity / errors |
| test_ai_request_builder.py | 2 | deepseek / openrouter |
| test_lexicon.py | 16 | trie / 掩码 / 空格误报 / 目录加载 |
| test_retry_logic.py | 19 | classify_error / compute_retry / max_retries / 终态排除 |
| test_db.py | 3 | schema / idempotent |
| **总计** | **125** | |

---

## 六、下一阶段 TODO

| 优先级 | 项目 | 说明 |
|--------|------|------|
| P1 | 前端验证与联调 | 启动前后端，验证页面与 API 对接 |
| P1 | qidian_com_web 插件确认 | 确认插件 ID 和 chapter_reviews 能力 |
| P2 | AI 自评分 prompt | 偏差值权重 0.3，需在 prompt 追加自评请求 |
| P2 | 候选 TOC 分页 | 当前只取第一页，大量章节时可能漏匹配 |
| P3 | 目录断更恢复 | 长期连载书断更后恢复更新的处理 |
| P3 | 前端主源拖拽排序 | 当前只有增删，拖拽排序需引入 dnd 库 |

---

## 七、关键设计决策记录

1. **官方源优先 → 可配置优先级**：初始设计是"官方源永远优先"，后改为用户可配置有序列表 `primarySourcePriority`，匹配不到时再降级到官方优先+评分。

2. **SequenceMatcher autojunk=False**：发现 Python `difflib.SequenceMatcher` 对长中文重复文本（如小说正文）会将高频汉字标记为 junk，导致相似度计算为 0.0。所有调用点统一改为 `autojunk=False`。

3. **四路径状态机**：`_process_chapter` 从"全走 processed"改为：
   - 官方完整 → processed (official)
   - 预览 → 候选对齐 → AI → processed / fallback
   - 第三方 → AI 归属校验 → processed / fallback
   - 空内容 → error

4. **API Key 加密兼容**：Fernet 加密新写入的 key，读取时自动解密；旧明文 key 仍可正常读取，不破坏已有数据。

5. **敏感词扫描不自动替换**：词库命中只是候选提示，传入 AI prompt 让 AI 结合语义判断，不直接机械替换。
