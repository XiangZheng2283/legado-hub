# AI 聚合源后端 — 全量开发报告

> 日期：2026-06-15
> 状态：后端功能完整，前端 4 页面已构建；后端持续迭代
> 测试：133+ 个通过（含新增代理/UA/自评分测试）

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
| `dev-assets/tests/test_ai_client.py` | 251 | 17 个 AI 客户端测试 |
| `dev-assets/tests/test_lexicon.py` | 162 | 16 个敏感词扫描测试 |
| `dev-assets/tests/test_retry_logic.py` | 230 | 19 个重试/退避测试 |
| `dev-assets/tests/test_aggregate_alignment.py` | 176 | 21 个对齐 + 偏差值测试 |
| `dev-assets/tests/test_aggregate_ai_service.py` | 189 | 10 个 AI 服务测试 |
| `dev-assets/tests/test_aggregate_settings.py` | 105 | 5 个设置 + 加密测试 |
| `dev-assets/tests/test_aggregate_reviews.py` | 96 | 5 个热评测试 |
| `dev-assets/tests/test_aggregate_processor_state_machine.py` | 510 | 17 个状态机测试 |
| `dev-assets/tests/test_access_bridge_facade.py` | ~80 | search_provider 代理推导测试 |
| `frontend/src/routes/AggregateSettingsPage.tsx` | ~350 | 聚合设置页 |
| `frontend/src/routes/AggregateBookshelfPage.tsx` | ~250 | 聚合书架页 |
| `frontend/src/routes/AggregateBookDetailPage.tsx` | ~300 | 书详情页 |
| `frontend/src/routes/AggregateChapterDetailPage.tsx` | ~350 | 章节详情页 |
| `docs/devlog-ai-aggregate.md` | ~210 | 开发日志 |

### 修改文件（8 个）

| 文件 | 改动 |
|------|------|
| `backend/app/api/console.py` | test-provider / fetch-models 接入真实客户端；章节详情 JOIN 修复；热评真实抓取；返回 `aiSelfScore` |
| `backend/app/services/aggregate_processor.py` | 四路径状态机 / ai_service 注入 / TOC 缓存 / 前文校准 / 偏差值 / 主源优先级 / TOC diff / 写入 `ai_self_score` |
| `backend/app/services/aggregate_virtual_source.py` | `primary_book_id_from_payload` 支持 `source_priority` 参数 |
| `backend/app/services/aggregate_ai_service.py` | Prompt 追加自评请求；解析 `<self_rating>` 并返回 `selfScore` |
| `backend/app/services/aggregate_alignment.py` | `compute_deviation_score` 支持 `ai_self_score` 权重 0.7/0.3 |
| `backend/app/ai/models_catalog.py` | 3 → 30+ 模型 |
| `backend/app/storage/db.py` | schema + ensure_current_schema 增量补列；新增 `ai_self_score` |
| `backend/app/config.py` | 新增 `get_default_user_agent()` 全局 UA 接口 |
| `backend/app/source_plugins/fetcher.py` | 实现 `auto` 代理回退；默认 UA 使用全局接口 |
| `backend/app/source_plugins/scheduler.py` | 透传 `proxy_mode`/`proxy_url` 到 `Fetcher` 与 `PluginContext` |
| `backend/app/source_plugins/context.py` | `PluginContext` 增加 `proxy_mode`/`proxy_url` |
| `backend/app/services/access_bridge/facade.py` | `search_provider` 按插件 `proxy.mode` 推导代理；Browser fetch 接入 `use_proxy` |
| `backend/app/services/access_bridge/client.py` | Playwright `new_context(proxy=...)` 支持 |
| `backend/app/services/access_bridge/search_provider.py` | `DEFAULT_HEADERS` 使用全局 UA |
| `backend/app/services/login_browser_service.py` | 浏览器登录使用全局 UA |
| `backend/app/services/source_ping.py` | ping 请求使用全局 UA |
| `dev-assets/probes/probe_site_network.py` | 默认 UA 使用全局接口（本地抓包/探测脚本，不推送） |
| `plugins/sources/official/qidian_com_web/private/web_keepalive.py` | 改走 `ctx.access.http`，移除 `requests` 直调和硬编码 UA |
| `plugins/sources/official/qidian_com_web/source.py` | `_try_keepalive` 直接 await 异步 keepalive |
| `plugins/sources/thirdparty/biquge365_net/source.py` | 移除硬编码 UA |
| `plugins/sources/thirdparty/shuhaige_net/source.py` | 移除硬编码 UA |
| `dev-assets/tests/test_aggregate_processor.py` | +主源优先级测试 / monkeypatch 修复 |
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
| 偏差值校验 | ✅ | LCS 相似度，低于阈值自动 fallback；已接入 AI 自评分（权重 0.3） |
| AI 自评分 | ✅ | Prompt 要求输出 `<self_rating>`，解析后混合进 deviation_score |
| 敏感词扫描 | ✅ | Trie 掩码检测，接入 AI prompt |
| 前文校准 | ✅ | 前 3 章已处理内容传入 AI prompt |
| 处理状态机 | ✅ | 官方完整 / preview+候选+AI / 第三方主源 / fallback |
| 重试退避 | ✅ | 5 级递增延迟，AI_BAD_REQUEST 不重试 |
| 终态章节排除 | ✅ | retry_count≥5 / AI_BAD_REQUEST 不再入队 |
| Fallback 阅读 | ✅ | status='fallback' 也返回正文 |
| 主源优先级 | ✅ | 可配置有序列表，先匹配后降级 |
| 第三方源代理 | ✅ | 插件 `proxy.mode`（auto/always/never）作用于 HTTP/Stealth/Browser/SearchProvider |
| 全局 UA | ✅ | `app.config.get_default_user_agent()` 统一后端、访问桥、脚本、插件 UA |
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
| test_aggregate_ai_service.py | 14 | official_full / with_candidates / third_party / 未配置 / prompt 禁止凭空 / lexicon / 前文上下文 / self_rating 解析 |
| test_aggregate_alignment.py | 23 | classify / title_sim / sliding_window / align / build_json / deviation_score / self_score 权重 |
| test_db.py | 3 | schema / idempotent / ai_self_score 列 |
| test_aggregate_settings.py | 5 | 迁移 / 脱敏 / 加密 / 旧明文兼容 |
| test_aggregate_reviews.py | 5 | normalize / contract / bubble label |
| test_ai_client.py | 17 | config / chat / list_models / connectivity / errors |
| test_ai_request_builder.py | 2 | deepseek / openrouter |
| test_lexicon.py | 16 | trie / 掩码 / 空格误报 / 目录加载 |
| test_retry_logic.py | 19 | classify_error / compute_retry / max_retries / 终态排除 |
| test_db.py | 3 | schema / idempotent / ai_self_score 列 |
| test_access_bridge_facade.py | 3 | search_provider 代理推导 |
| test_fetcher.py | 11 | fetch / decode / auto 代理回退 / always / never |
| test_scheduler.py | 3 | 插件加载 / search_provider 开关 / proxy 配置透传 |
| **总计** | **133+** | |

> 注：部分旧测试（引用已移除的 `qidian_com` 插件或缺失 fixture）当前未纳入计数，属于历史遗留清理项。

---

## 六、下一阶段 TODO

| 优先级 | 项目 | 状态 | 说明 |
|--------|------|------|------|
| P1 | 前端验证与联调 | ✅ | 启动前后端，验证页面与 API 对接；已修复 qidian 目录 URL、进度统计、章节详情字段 |
| P1 | qidian_com_web 插件确认 | ✅ | 插件 ID 与 chapter_reviews 能力已确认 |
| P2 | AI 自评分 prompt | ✅ | Prompt 追加 `<self_rating>`；deviation_score = code*0.7 + self*0.3 |
| P2 | 候选 TOC 分页 | ⏳ | 当前只取第一页，大量章节时可能漏匹配 |
| P2 | 后端可观测性增强 | ⏳ | 聚合任务日志、耗时分布、AI 调用链路追踪 |
| P3 | 目录断更恢复 | ⏳ | 长期连载书断更后恢复更新的处理 |
| P3 | 前端主源拖拽排序 | ⏳ | 当前只有增删，拖拽排序需引入 dnd 库 |

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

6. **第三方源代理策略**：插件 `proxy.mode` 统一作用于 HTTP/Stealth/Browser/SearchProvider；`auto` 模式先直连、失败后按配置回退代理；`always`/`never` 显式控制。浏览器访问桥通过 Playwright `new_context(proxy=...)` 接入代理。

7. **全局 User-Agent**：新增 `app.config.get_default_user_agent()`，所有后端服务、访问桥、脚本和插件默认读取 `backend/config/source_pool.json` 的 `default_user_agent`，避免硬编码 UA。

8. **AI 自评分混合偏差值**：AI 输出末尾输出 `<self_rating>0.XX</self_rating>`，解析后移除标签；`deviation_score = code_similarity * 0.7 + ai_self_score * 0.3`；未输出评分时回退到纯代码相似度，保持兼容。
