# AI 聚合源实现规划

> 状态：规划中（待开发）  
> 范围：后端 AI 聚合引擎 + 控制台聚合书架 + 聚合设置分页  

---

## 1. 背景与目标

LegadoHub 已经具备虚拟聚合书源（`legadohub_ai_aggregate`）的骨架：搜索分组、聚合 URL、后台任务表、`AggregateProcessor` 等。本规划将补全真正的 AI 聚合能力，使聚合源从「占位提示」进化为可阅读、可管理、可配置的生产功能。

核心目标：

1. 以官方源为主基准，对章节进行去广告、纠错、分段、去屏蔽词续写、纠乱码等 AI 处理。
2. 当官方源不可用或章节未购买时，自动从高分第三方源补充并聚合。
3. 所有聚合结果以 Markdown 明文写入本地，便于导出与长期保存。
4. 控制台提供独立的聚合书架页面与聚合设置分页，支持进度追踪、token 统计、模型配置。
5. 搜索界面可对聚合源执行「加入处理」，而非直接阅读。

---

## 2. 术语

| 术语 | 说明 |
|------|------|
| 主源 | 聚合处理时作为基准的书源。默认官方源；官方不可用时按规则从第三方源选出。 |
| 候选源 | 聚合分组内除主源外的其他书源，用于补充主源缺失内容。 |
| 聚合任务 | `aggregate_book_tasks` 中一行，代表一本书的 AI 聚合生命周期。 |
| 占位章节 | 尚未处理完成时，本地已生成的占位 `.md` 文件，内容为「聚合处理中……请先查看其他源或稍后刷新。」 |
| 偏差值 | AI 输出与原始主源正文（去除格式后）的相似度百分比，用于校验 AI 是否过度改写。 |

---

## 3. 设计原则

1. **官方源优先**：只要官方源存在且章节可获得，就以官方源为唯一基准。
2. **降级可控**：官方源缺失/未购买时，按评分 + 进度自动选择第三方源补充。
3. **尽量少分段**：单章优先一次性送入 AI，超长再考虑分段，且分段数尽量少。
4. **上下文安全**：默认输入 token 不超过模型最大上下文的 50%，预留输出空间。
5. **证据优先**：每章记录模型、token、耗时、偏差值、来源与失败原因。
6. **本地明文**：聚合结果必须可被人直接阅读，不依赖数据库解析。
7. **失败可读**：AI 处理失败后，返回可用的原始内容，并明确标注来源与失败。

---

## 4. 数据模型

### 4.0 现有实现迁移方案

当前仓库已经存在 AI 聚合源的基础骨架，不能按新表从零重建。落地时按「兼容旧数据、渐进扩展字段、统一读取入口」迁移：

1. 保留现有 `aggregate_book_tasks` 与 `aggregate_chapter_tasks` 表，使用 `ALTER TABLE ADD COLUMN` 增量补齐新字段。
2. 保留现有已处理章节，不重新处理 `status = 'processed'` 且 `processed_content` 非空的章节。
3. 保留现有本地章节文件；数据库缺正文但文件存在时，可通过文件缓存回填或直接返回文件内容。
4. 现有 `admin_settings.contentWorkflow` 迁移为 `aggregate_settings.contentWorkflow`；迁移完成后，聚合模块只从 `aggregate_settings` 读取，避免同一设置存在两个真相源。
5. 首次启动时执行一次设置迁移：若 `aggregate_settings.contentWorkflow` 不存在且 `admin_settings.contentWorkflow` 存在，则复制旧值；复制后不删除旧值，用于兼容回滚。
6. `AggregateProcessor.DEFAULT_WORKFLOW` 仅作为代码兜底默认值，不再作为持久化配置来源。
7. 数据库版本升级必须通过 `ensure_current_schema()` 完成，已有 SQLite 数据库启动后能自动补列。

迁移时新增字段建议：

```sql
ALTER TABLE aggregate_book_tasks ADD COLUMN primary_source_id TEXT;
ALTER TABLE aggregate_book_tasks ADD COLUMN book_status TEXT DEFAULT 'unknown';
ALTER TABLE aggregate_book_tasks ADD COLUMN total_chapters INTEGER DEFAULT 0;
ALTER TABLE aggregate_book_tasks ADD COLUMN processed_chapters INTEGER DEFAULT 0;
ALTER TABLE aggregate_book_tasks ADD COLUMN failed_chapters INTEGER DEFAULT 0;
ALTER TABLE aggregate_book_tasks ADD COLUMN total_tokens INTEGER DEFAULT 0;
ALTER TABLE aggregate_book_tasks ADD COLUMN ai_enabled INTEGER DEFAULT 0;
ALTER TABLE aggregate_book_tasks ADD COLUMN last_processed_at TEXT;
ALTER TABLE aggregate_book_tasks ADD COLUMN source_map_json TEXT;       -- 第三方源搜索缓存
ALTER TABLE aggregate_book_tasks ADD COLUMN source_map_updated_at TEXT; -- sourceMap 更新时间

ALTER TABLE aggregate_chapter_tasks ADD COLUMN ai_model TEXT;
ALTER TABLE aggregate_chapter_tasks ADD COLUMN ai_prompt_tokens INTEGER DEFAULT 0;
ALTER TABLE aggregate_chapter_tasks ADD COLUMN ai_completion_tokens INTEGER DEFAULT 0;
ALTER TABLE aggregate_chapter_tasks ADD COLUMN ai_total_tokens INTEGER DEFAULT 0;
ALTER TABLE aggregate_chapter_tasks ADD COLUMN ai_latency_ms INTEGER DEFAULT 0;
ALTER TABLE aggregate_chapter_tasks ADD COLUMN deviation_score REAL DEFAULT 0.0;
ALTER TABLE aggregate_chapter_tasks ADD COLUMN fallback_source_id TEXT;
ALTER TABLE aggregate_chapter_tasks ADD COLUMN source_alignment_json TEXT;
ALTER TABLE aggregate_chapter_tasks ADD COLUMN retry_count INTEGER DEFAULT 0;
ALTER TABLE aggregate_chapter_tasks ADD COLUMN next_retry_time TEXT;
ALTER TABLE aggregate_chapter_tasks ADD COLUMN last_error_code TEXT;
ALTER TABLE aggregate_chapter_tasks ADD COLUMN official_word_count INTEGER;   -- 官方接口返回字数
ALTER TABLE aggregate_chapter_tasks ADD COLUMN fetched_word_count INTEGER;    -- 实际拉取字数
ALTER TABLE aggregate_chapter_tasks ADD COLUMN completeness_checked INTEGER DEFAULT 0; -- 是否已完成完整性检查
ALTER TABLE aggregate_chapter_tasks ADD COLUMN attribution_passed INTEGER DEFAULT 0;   -- 校对是否通过
ALTER TABLE aggregate_chapter_tasks ADD COLUMN stage TEXT DEFAULT 'fetched';  -- 'fetched' | 'completing' | 'proofreading' | 'post_processing' | 'processed' | 'fallback' | 'error'
```

并发处理约束：

1. 同一本书只允许一个处理进程推进；多个入口同时触发同一本书时，直接返回当前进度，不创建第二条处理链。
2. 已完成的书不用再处理；当 `book_status = 'completed'` 且 `status = 'completed'` 时，手动运行只返回已完成状态，除非用户明确点击「重新处理」。
3. 多本书进入处理队列时按 `next_check_time / created_at` 顺序自然排队，后台 worker 串行处理书籍。
4. 同一本书的目录刷新、章节处理、统计更新必须共用同一套后端状态，前端只轮询进度，不自行推断。

### 4.1 聚合书籍任务表（`aggregate_book_tasks`）

```sql
CREATE TABLE IF NOT EXISTS aggregate_book_tasks (
    aggregate_book_id TEXT PRIMARY KEY,
    name TEXT,
    author TEXT,
    aggregate_payload_json TEXT,
    primary_book_id TEXT,
    primary_source_id TEXT,
    book_status TEXT DEFAULT 'unknown',       -- 'ongoing' | 'completed' | 'unknown'
    total_chapters INTEGER DEFAULT 0,
    processed_chapters INTEGER DEFAULT 0,
    failed_chapters INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',             -- 'active' | 'error' | 'completed' | 'paused'
    interval_minutes INTEGER DEFAULT 30,
    last_check_time TEXT,
    next_check_time TEXT,
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    ai_enabled INTEGER DEFAULT 0,
    last_processed_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

### 4.2 聚合章节任务表（`aggregate_chapter_tasks`）

```sql
CREATE TABLE IF NOT EXISTS aggregate_chapter_tasks (
    chapter_id TEXT PRIMARY KEY,
    aggregate_book_id TEXT NOT NULL,
    source_chapter_id TEXT,
    chapter_index INTEGER,
    title TEXT,
    status TEXT DEFAULT 'fetched',            -- 'fetched' | 'completing' | 'proofreading' | 'post_processing' | 'processed' | 'fallback' | 'error' | 'skipped'
    content_length INTEGER DEFAULT 0,
    processed_content TEXT,
    last_processed_at TEXT,
    error TEXT,
    ai_model TEXT,
    ai_prompt_tokens INTEGER DEFAULT 0,
    ai_completion_tokens INTEGER DEFAULT 0,
    ai_total_tokens INTEGER DEFAULT 0,
    ai_latency_ms INTEGER DEFAULT 0,
    deviation_score REAL DEFAULT 0.0,         -- 偏差值 0~1
    fallback_source_id TEXT,                  -- 最终回退来源
    source_alignment_json TEXT,               -- 章节对齐/来源决策记录
    retry_count INTEGER DEFAULT 0,
    next_retry_time TEXT,
    last_error_code TEXT,
    official_word_count INTEGER,              -- 官方接口返回字数
    fetched_word_count INTEGER,               -- 实际拉取字数
    completeness_checked INTEGER DEFAULT 0,   -- 是否已完成完整性检查
    attribution_passed INTEGER DEFAULT 0,     -- 校对归属校验是否通过
    stage TEXT DEFAULT 'fetched',             -- 当前所处生命周期阶段
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

状态语义更新：

| 状态 | 含义 |
|------|------|
| `fetched` | Stage 1 已完成，已拉取主源正文 |
| `completing` | Stage 2 完整性补全中 |
| `proofreading` | Stage 3 校对中 |
| `post_processing` | Stage 4 后处理中 |
| `processed` | 全部阶段完成 |
| `fallback` | 处理失败但已有可用正文 |
| `error` | 无可用正文 |
| `skipped` | 特殊章节跳过 |

### 4.3 AI 调用明细表（`aggregate_ai_usage`）

```sql
CREATE TABLE IF NOT EXISTS aggregate_ai_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aggregate_book_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    status TEXT,                              -- 'success' | 'error' | 'skipped'
    error TEXT,
    deviation_score REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now'))
);
```

### 4.4 聚合设置表（`aggregate_settings`）

由于聚合设置字段较多，单独成表，避免 `admin_settings` 过度膨胀。

```sql
CREATE TABLE IF NOT EXISTS aggregate_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);
```

### 4.5 第三方源搜索缓存表（`aggregate_source_map`）

`sourceMap` 主存储在 `metadata.json`，数据库表作为索引和搜索缓存，便于快速查询某书在某源上的详情页。

```sql
CREATE TABLE IF NOT EXISTS aggregate_source_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aggregate_book_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    book_url TEXT NOT NULL,
    score INTEGER DEFAULT 0,
    last_chapter TEXT,
    progress INTEGER DEFAULT 0,
    search_tier TEXT DEFAULT 'tier1',         -- 'tier1' | 'tier2'
    matched_at TEXT,
    search_failed_at TEXT,
    search_fail_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(aggregate_book_id, source_id)
);
```

设计说明：

- 与 `metadata.json` 的 `sourceMap` 保持同步；写入时双写，读取时以 `metadata.json` 为准。
- `search_failed_at` / `search_fail_count` 用于失败退避。
- `search_tier` 用于分级搜索策略。

---

## 5. 设置 Schema

`aggregate_settings` 中存储 `contentWorkflow` 与 `aiProviderConfig` 两部分。

### 5.1 `contentWorkflow` 内容工作流

```json
{
  "aggregationMode": "balanced",
  "autoAggregate": true,
  "processAggregateOnRead": true,
  "aggregateCheckIntervalMinutes": 30,
  "returnOnlyAggregateSource": false,
  "sourceCandidateLimit": 6,
  "purifyMode": "conservative",

  "primarySourceMode": "official",
  "minSourceScore": 100,

  "aiEnabled": true,
  "blockedWordRepair": true,
  "sensitiveLexiconEnabled": true,
  "sensitiveLexiconPath": "backend/data/lexicons/Sensitive-lexicon",
  "includePreviousChapters": 3,
  "deviationThreshold": 0.90,

  "completenessRatio": 0.85,
  "minChapterLength": 200,
  "sourceSearchEnabled": true,
  "sourceSearchTier": "tier1",
  "sourceSearchConcurrency": 5,
  "sourceSearchCacheTtlHours": 24,
  "sourceFetchConcurrency": 5,
  "agentMaxSteps": 5,
  "agentAttributionThreshold": 0.85,
  "agentSelfRatingThreshold": 0.85,

  "promptTemplate": "...",
  "systemPrompt": "..."
}
```

字段说明：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `primarySourceMode` | string | `official` | 主源选择模式：`official` / `best_progress` / `best_score`。 |
| `minSourceScore` | int | 100 | 普通书源参与主源竞选的最低评分。 |
| `aiEnabled` | bool | false | 是否启用 AI 处理。 |
| `blockedWordRepair` | bool | true | 是否对屏蔽词进行续写修复。 |
| `sensitiveLexiconEnabled` | bool | true | 是否启用敏感词词库辅助恢复。 |
| `sensitiveLexiconPath` | string | `backend/data/lexicons/Sensitive-lexicon` | 本地敏感词库路径，默认使用 `konsheng/Sensitive-lexicon` 的本地副本。 |
| `includePreviousChapters` | int | 3 | AI 处理时携带前几章已处理内容作为校准。 |
| `deviationThreshold` | float | 0.90 | 偏差值阈值，可选 0.95 / 0.90 / 0.80。 |
| `completenessRatio` | float | 0.85 | 实际字数 / 官方字数 >= 该值视为完整。 |
| `minChapterLength` | int | 200 | 无官方字数时的最小完整章节长度。 |
| `sourceSearchEnabled` | bool | true | 订阅时是否自动搜索第三方源。 |
| `sourceSearchTier` | string | `tier1` | 默认搜索的书源分级：`tier1` / `tier2` / `all`。 |
| `sourceSearchConcurrency` | int | 5 | 全源搜索并发数。 |
| `sourceSearchCacheTtlHours` | int | 24 | sourceMap 缓存 TTL。 |
| `sourceFetchConcurrency` | int | 5 | Stage 1 主源正文拉取并发数。 |
| `agentMaxSteps` | int | 5 | 单个 Stage 内 Agent 最大步数。 |
| `agentAttributionThreshold` | float | 0.85 | 归属校验通过阈值。 |
| `agentSelfRatingThreshold` | float | 0.85 | 后处理自评通过阈值。 |
| `promptTemplate` | string | - | 用户 prompt 模板。 |
| `systemPrompt` | string | - | 系统 prompt。 |

### 5.2 `aiProviderConfig` AI Provider 配置

参考 [cc-switch](https://github.com/farion1231/cc-switch) 与 [opencode](https://github.com/anomalyco/opencode) 的 provider / request 设计，保留小说场景所需的可配置集：

```json
{
  "provider": "openai_compatible",
  "name": "DeepSeek",
  "baseUrl": "https://api.deepseek.com/v1",
  "apiKey": "<加密存储>",
  "apiKeyField": "api_key",
  "model": "deepseek-chat",

  "modelContextLength": 256000,
  "maxContextUseRatio": 0.5,
  "maxOutputTokens": 8192,
  "timeoutMs": 120000,

  "aiMaxConcurrency": 2,
  "bookDefaultConcurrency": 1,

  "temperature": 0.3,
  "topP": 1.0,
  "frequencyPenalty": 0,
  "presencePenalty": 0,
  "seed": 0,

  "endpointCandidates": [],
  "modelsUrl": "",
  "customHeaders": {},
  "customBodyParams": {},

  "thinkingLevel": "medium",
  "compatOverrides": {}
}
```

字段说明：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `provider` | string | `openai_compatible` | 协议类型，现阶段固定为此，预留扩展。 |
| `baseUrl` | string | - | OpenAI 兼容 endpoint，例如 `https://api.deepseek.com/v1`。 |
| `apiKey` | string | - | API Key，数据库加密存储。 |
| `model` | string | - | 默认模型。 |
| `modelContextLength` | int | 256000 | 模型标称最大上下文长度。 |
| `maxContextUseRatio` | float | 0.5 | 默认最多使用模型上下文的 50%。 |
| `maxOutputTokens` | int | 8192 | 单次最大输出 token。 |
| `timeoutMs` | int | 120000 | AI 请求超时。 |
| `aiMaxConcurrency` | int | 2 | 全局 AI 调用并发。 |
| `bookDefaultConcurrency` | int | 1 | 单本书默认章节并发。 |
| `temperature` | float | 0.3 | 采样温度。 |
| `topP` | float | 1.0 | nucleus sampling。 |
| `frequencyPenalty` | float | 0 | 频率惩罚。 |
| `presencePenalty` | float | 0 | 存在惩罚。 |
| `seed` | int | 0 | 随机种子，0 表示不固定。 |
| `endpointCandidates` | list | [] | 备用 endpoint 列表（测速/切换用，预留）。 |
| `modelsUrl` | string | "" | 获取模型列表的自定义 URL，缺省使用 `/v1/models`。 |
| `customHeaders` | dict | {} | 自定义请求头。 |
| `customBodyParams` | dict | {} | 自定义请求体参数，用于兼容特殊 endpoint。 |
| `thinkingLevel` | string | `"medium"` | 思考强度，选项：`off` / `minimal` / `low` / `medium` / `high` / `xhigh`。后端按模型映射到 provider 原生参数。 |
| `compatOverrides` | dict | `{}` | 覆盖自动推断的兼容层字段，高级调试用。 |

---

## 5.3 复用 `earendil-works/pi` 协议库的策略

### 5.3.1 为什么不能直接复用

`earendil-works/pi` 的 `@earendil-works/pi-ai` 是 TypeScript / npm 包，而 LegadoHub 后端是 Python。直接依赖或子进程调用都会引入不必要的运行时耦合与部署复杂度。因此采用**设计移植**而非**代码依赖**：

- 不引入 pi 的 npm 包或 TypeScript 运行时。
- 仅把小说场景真正需要的元数据、兼容层、思考强度映射，移植到 Python 后端。

### 5.3.2 移植内容

| pi 资产 | 来源文件 | LegadoHub 用途 |
|---------|----------|----------------|
| 模型元数据 | `packages/ai/src/models.generated.ts` | 内置 `MODEL_CONTEXT_LENGTHS` / `MODEL_MAX_TOKENS` / `MODEL_REASONING` 映射表，前端选模型时自动填充上下文长度与输出上限。 |
| 兼容层 `compat` | `packages/ai/src/providers/openai-completions.ts` | 后端根据 `provider` / `baseUrl` / `model` 自动推断 `compat`，并允许 `compatOverrides` 覆盖。 |
| `thinkingLevelMap` | `packages/ai/src/models.generated.ts` | 把 UI 的 `thinkingLevel` 翻译成各 provider 原生参数。 |

### 5.3.3 `compat` 字段设计

兼容层字段参考 pi 的 `OpenAICompletionsCompat`，结合小说场景精简：

| 字段 | 类型 | 自动推断依据 | 说明 |
|------|------|--------------|------|
| `maxTokensField` | string | provider / baseUrl | `max_tokens`（Moonshot / Together / Chutes / NVIDIA 等）或 `max_completion_tokens`（OpenAI 标准）。 |
| `thinkingFormat` | string | provider / baseUrl / `model.reasoning` | `openai` / `deepseek` / `zai` / `qwen` / `qwen-chat-template` / `openrouter` / `together` / `ant-ling` / `string-thinking`。 |
| `supportsDeveloperRole` | bool | provider / baseUrl | 是否用 `developer` 角色替代 `system`（OpenAI 官方 reasoning 模型、OpenRouter 上的 anthropic/openai 模型）。 |
| `supportsReasoningEffort` | bool | provider / baseUrl | 是否支持原生 `reasoning_effort`。 |
| `supportsUsageInStreaming` | bool | provider / baseUrl | 流式响应是否请求 `stream_options.include_usage`。 |
| `requiresReasoningContentOnAssistantMessages` | bool | provider | DeepSeek 等要求 assistant 历史消息带 `reasoning_content`。 |
| `requiresThinkingAsText` | bool | provider | 是否把 thinking 块当纯文本发送。 |
| `supportsStrictMode` | bool | provider | 工具 `strict` 字段兼容性。 |

### 5.3.4 `thinkingLevel` 下拉选项与模型映射

前端使用**下拉选项框**（不是滑块），选项固定为：

- `off`
- `minimal`
- `low`
- `medium`
- `high`
- `xhigh`

后端根据模型内置的 `thinkingLevelMap` 把抽象级别映射为 provider 原生值。例如：

```python
# 内置模型元数据示例
MODELS_CATALOG = {
    "deepseek-chat": {
        "contextWindow": 65536,
        "maxTokens": 8192,
        "reasoning": True,
        "thinkingLevelMap": {
            "off": None,
            "minimal": "low",
            "low": "low",
            "medium": "medium",
            "high": "high",
            "xhigh": "high",
        },
        "compat": {"thinkingFormat": "deepseek"},
    },
    "claude-opus-4-7": {
        "contextWindow": 1000000,
        "maxTokens": 128000,
        "reasoning": True,
        "thinkingLevelMap": {
            "off": None,
            "xhigh": "xhigh",
        },
        "compat": {"thinkingFormat": "openai"},
    },
}
```

当 `thinkingLevel` 不在模型的 `thinkingLevelMap` 中时，降级到最接近的低级别；若模型不支持 reasoning，则强制为 `off`。

### 5.3.5 后端请求体构造

`request_builder.py` 根据 `compat.thinkingFormat` 生成不同请求体片段：

| `thinkingFormat` | 行为 |
|------------------|------|
| `openai` | 若 `reasoning` 且 `thinkingLevel != off`，设置 `reasoning_effort = thinkingLevelMap[level]`。 |
| `deepseek` | 设置 `thinking.type = enabled/disabled`；若支持 `reasoning_effort` 再设置该字段。 |
| `zai` | 设置 `thinking.type = enabled/disabled`。 |
| `qwen` | 设置 `enable_thinking = True/False`。 |
| `qwen-chat-template` | 设置 `chat_template_kwargs.enable_thinking` 与 `preserve_thinking`。 |
| `openrouter` | 设置嵌套 `reasoning.effort`。 |
| `together` | 设置 `reasoning.enabled` 与可选 `reasoning_effort`。 |
| `ant-ling` | 设置 `reasoning.effort`。 |
| `string-thinking` | 设置 `thinking` 为字符串级别。 |

### 5.3.6 模块划分

新增 `backend/app/ai/` 模块：

```
backend/app/ai/
├── __init__.py
├── models_catalog.py      # 内置模型元数据（从 pi 提取）
├── compat.py              # compat 自动推断 + 用户覆盖
├── request_builder.py     # 根据 compat 构造 OpenAI 兼容请求体
├── client.py              # httpx 异步客户端、流式解析、错误处理
├── encryption.py          # API Key Fernet 加密
└── tokenizer.py           # 简单 token 估算（字符 / 4 兜底）
```

---

## 6. AI Provider 客户端

### 6.1 协议

采用 OpenAI Chat Completions 兼容协议，覆盖 OpenAI、DeepSeek、硅基流动、Kimi、Moonshot、Ollama 等主流服务。

请求格式：

```json
POST {baseUrl}/chat/completions
{
  "model": "deepseek-chat",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "temperature": 0.3,
  "max_tokens": 8192
}
```

实际请求体由 `request_builder.py` 根据 `compat` 与 `thinkingLevel` 动态生成：

- `max_tokens` / `max_completion_tokens` 由 `compat.maxTokensField` 决定。
- 思考相关字段由 `compat.thinkingFormat` 决定（见 5.3.5）。
- `system` / `developer` 角色由 `compat.supportsDeveloperRole` 决定。
- `stream_options.include_usage` 由 `compat.supportsUsageInStreaming` 决定是否追加。

### 6.2 模型列表获取

调用 `GET {baseUrl}/models`（或 `modelsUrl` 覆盖），返回模型 ID 列表供前端下拉选择。

### 6.3 模型上下文长度管理

[earendil-works/pi](https://github.com/earendil-works/pi) 的 `packages/ai/src/models.generated.ts` 包含大量模型的 `contextWindow` 与 `maxTokens`，其数据主要来自 [models.dev](https://models.dev/api.json) 的 `limit.context` / `limit.output`，并辅以 OpenRouter、Vercel AI Gateway 等来源的拉取与人工修正。

LegadoHub 参考该机制，采用「内置映射 + 可选 models.dev 同步 + 用户可覆盖」的策略：

1. **内置常见模型映射表**（初始值参考 pi / models.dev）：

```python
MODEL_CONTEXT_LENGTHS = {
    # OpenAI
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4.1": 1000000,
    "gpt-4.1-mini": 1000000,
    "gpt-5.4": 272000,
    "gpt-5.5": 272000,
    "o3": 200000,
    "o4-mini": 200000,

    # DeepSeek
    "deepseek-chat": 64000,
    "deepseek-reasoner": 64000,
    "deepseek-v3": 163840,
    "deepseek-r1": 128000,

    # Anthropic
    "claude-3-5-sonnet-20241022": 200000,
    "claude-3-7-sonnet-20250219": 200000,
    "claude-3-opus-20240229": 200000,
    "claude-3-5-haiku-20241022": 200000,
    "claude-opus-4-6": 1000000,
    "claude-opus-4-7": 1000000,
    "claude-opus-4-8": 1000000,
    "claude-sonnet-4-6": 1000000,

    # Moonshot / Kimi
    "moonshot-v1-8k": 8192,
    "moonshot-v1-32k": 32768,
    "moonshot-v1-128k": 131072,
    "kimi-k2-5": 262143,
    "kimi-k2.6": 262143,

    # Qwen
    "qwen-max": 32768,
    "qwen-plus": 131072,
    "qwen-turbo": 131072,
    "qwen-long": 10000000,
    "qwen3-235b-a22b": 262144,

    # GLM
    "glm-4": 131072,
    "glm-4-plus": 131072,
    "glm-4-long": 1000000,
    "glm-4.7": 204800,
    "glm-5": 202752,

    # MiniMax
    "minimax-m2": 204608,
    "minimax-m2.5": 196608,

    # Mistral
    "mistral-large-3": 256000,

    # SiliconFlow / 其他兼容
    "Pro/deepseek-ai/DeepSeek-V3": 64000,
    "Pro/deepseek-ai/DeepSeek-R1": 64000,
}
```

2. **可选同步脚本**：可编写 `scripts/sync-model-contexts.py`，定期从 `https://models.dev/api.json` 拉取并更新内置映射，减少手动维护。
3. **自动推断**：前端选择模型时，如果模型 ID 命中内置映射，自动填充 `modelContextLength`。
4. **用户覆盖**：用户可手动修改上下文长度，用于未收录模型或自定义微调模型。
5. **安全上限**：实际发送 prompt 时，token 数不超过 `modelContextLength * maxContextUseRatio`，默认 `maxContextUseRatio = 0.5`。

### 6.4 API Key 安全

- 使用 Fernet 对称加密后存入 `aggregate_settings`。
- 加密密钥从环境变量 `LEGADOHUB_AI_ENCRYPTION_KEY` 读取；未设置时生成并写入日志警告。
- 接口返回时脱敏：`sk-...xxxx`。

---

## 7. 主源选择与章节对齐

> 本章规则是 §8 四阶段流程的组成部分：
> - §7.1~§7.3 的主源选择属于 **Stage 1: 订阅初始化**。
> - §7.4 的跨书源章节对齐属于 **Stage 2: 完整性补全** 中 `align_chapter` tool 的实现细节。

### 7.1 默认规则

1. **官方源优先**：聚合分组中只要存在官方源，就将其作为候选主源集合。
2. **官方源选择**：在官方源候选中，按评分最高选择；评分相同则选进度最新。
3. **官方源不可用**：当官方源无结果、章节获取失败或正文过短（疑似未购买预览）时，进入第三方源竞选。
4. **第三方源竞选**：
   - 仅保留评分 ≥ `minSourceScore` 的书源。
   - 按章节进度最新排序；进度相同则按评分最高排序。
5. **兜底**：以上均无可用源时，返回评分最高的任意书源。

已确认主源优先级：

1. 官方源存在时，官方源永远优先。
2. 官方源不存在或不可用时，从第三方源中选择章节进度最新的源作为主源。
3. 进度相同或无法判断进度时，再比较评分。
4. 低于 `minSourceScore` 的第三方源不能成为主源，除非没有其他可用源。
5. 第三方源被选为主源后，仍不能默认信任其正文，需要进行正文归属校验。

第三方主源正文归属校验：

- 当主源不是官方源时，每章正文处理前，需要让 AI 结合书名、作者、章节标题、前后章节摘要、当前正文片段判断该章节是否确实属于这本小说。
- 校验重点包括：主角名、核心设定、上下文衔接、章节标题、叙事风格、是否混入其他小说正文。
- AI 只返回结构化判断：`belongsToBook`、`confidence`、`reason`。
- `confidence` 低于阈值时，该章节不能写入最终 Markdown，应尝试其他候选源或进入 `fallback/error`。
- 该校验用于防止第三方源正文错乱、串书、广告正文伪装章节等问题。

归属校验结果建议写入 `source_alignment_json`：

```json
{
  "belongsToBook": true,
  "belongingConfidence": 0.92,
  "belongingReason": "主角名、章节标题和前文事件连续"
}
```

### 7.2 章节进度比较

章节进度优先使用主源 `BookDetail` 中的 `lastChapter` 字段解析出的章节号；解析失败时使用 `toc` 返回的章节总数。

```python
def _extract_chapter_number(last_chapter: str) -> int:
    patterns = [
        r"第\s*(\d+)\s*章",
        r"第\s*(\d+)\s*篇",
        r"(\d+)\s*[、.]\s*",
    ]
    for pat in patterns:
        m = re.search(pat, last_chapter)
        if m:
            return int(m.group(1))
    return 0
```

### 7.3 书籍状态获取

`book_status` 从主源 `BookDetail.status` 或 `BookDetail.kind` 中推断：

- 包含 `连载`、`ongoing`、`未完结` → `ongoing`
- 包含 `完结`、`completed`、`完本` → `completed`
- 其他 → `unknown`

### 7.4 跨书源章节对齐规则

高优先级规则：官方源章节有完整正文时，官方源就是唯一真源。此时跳过跨源聚合步骤，不读取第三方正文，只对官方正文做敏感词清洗、去广告、空行整理等轻量处理，然后直接写入本地 Markdown 文件。

官方源章节不完整、不可读、未购买或正文过短时，才从候选源寻找可补充章节。候选源必须通过「索引邻域 + 标题校验 + 官方预览正文滑动匹配」三段校验，才允许用于补全。

已确认的对齐策略：

1. **官方完整正文优先**：官方源完整时不跨源补充，不调用候选源正文。
2. **索引邻域候选**：优先取相同 `chapter_index = N` 的候选章节；失败后尝试 `N-2` 到 `N+2` 范围内的章节。
3. **标题校验**：对候选章节标题做标准化后，与主源标题比较；标题相似度默认阈值为 `0.80`。
4. **预览正文校验**：用官方源可获取的预览正文，与第三方源正文前部做滑动匹配。
5. **正文预处理**：比较前先对第三方正文开头做轻量清洗，移除广告、站点提示、重复标题、作者说等噪声。
6. **预览长度**：官方预览默认取前 `80` 到 `200` 个有效字符；如果官方预览过短，最低可使用 `40` 个有效字符。
7. **滑动窗口**：第三方正文在前 `1000` 个有效字符内滑动匹配，避免正文前有站点提示导致误判。
8. **通过条件**：标题相似度 `>= 0.80` 且预览正文相似度 `>= 0.70`，视为同一章。
9. **兜底通过**：预览正文相似度 `>= 0.88` 时，即使标题略有差异，也可以视为低风险补充。
10. **低置信度处理**：未达到阈值时不跨源补充，返回主源预览或失败提示，避免错章污染。
11. **特殊章节处理**：番外、上架感言、请假条、作者单章等特殊章节，第一版不跨源补充，只保留主源结果。

落库要求：

- 每章把最终对齐结果写入 `source_alignment_json`。
- 记录候选源、候选章节索引、候选章节标题、标题相似度、预览正文相似度、最终置信度、采用/拒绝原因。
- 官方源完整正文直接采用时，`source_alignment_json.reason = "official_full_content"`。

`source_alignment_json` 字段：

| 字段 | 说明 |
|------|------|
| `primarySourceId` | 主源 ID。官方源存在时为官方源；官方源不存在时为评选出的第三方主源。 |
| `primaryChapterId` | 主源章节 ID，用于回溯原始章节。 |
| `primaryChapterIndex` | 主源章节序号。 |
| `primaryTitle` | 主源章节标题。 |
| `primaryPreviewTextHash` | 主源可获取正文预览的哈希，不直接保存预览原文。 |
| `candidateSourceId` | 候选补充源 ID；不需要第三方补充时为空。 |
| `candidateChapterId` | 候选源章节 ID。 |
| `candidateChapterIndex` | 候选源章节序号。 |
| `candidateTitle` | 候选源章节标题。 |
| `candidateContentLength` | 候选源正文长度。 |
| `titleSimilarity` | 标题相似度，范围 `0~1`。 |
| `previewSimilarity` | 主源预览正文与候选源正文的滑动匹配相似度，范围 `0~1`。 |
| `confidence` | 最终对齐置信度，范围 `0~1`。 |
| `accepted` | 是否接受该候选源作为补充。 |
| `reason` | 采用或拒绝原因。 |
| `selectedContentSource` | 最终正文来源：`official` / `candidate` / `fallback_official` / `fallback_candidate` / `ai_processed`。 |

示例：

```json
{
  "primarySourceId": "qidian_com",
  "primaryChapterId": "qidian_com:...",
  "primaryChapterIndex": 128,
  "primaryTitle": "第一百二十八章 风起",
  "primaryPreviewTextHash": "sha256:...",
  "candidateSourceId": "example_com",
  "candidateChapterId": "example_com:...",
  "candidateChapterIndex": 128,
  "candidateTitle": "第一百二十八章 风起",
  "candidateContentLength": 3560,
  "titleSimilarity": 0.94,
  "previewSimilarity": 0.89,
  "confidence": 0.91,
  "accepted": true,
  "reason": "title_and_preview_matched",
  "selectedContentSource": "candidate"
}
```

---

## 8. Agent 驱动的章节处理流程

本章描述订阅加入后的完整生命周期。核心变化：把“主源拉取 → 候选源补充 → AI 整理”的硬编码流水线，改为 **Agent 决策 + Tools 调用** 的四阶段模型。基础拉取（Stage 1）保持确定性；完整性补全、校对、后处理三个阶段由 Agent 通过 Tools 完成。

### 8.1 订阅生命周期四阶段

```text
┌─────────────────────────────────────────────────────────────────────┐
│  Stage 1: 订阅初始化（Subscription Bootstrap）                       │
│  - 选定主源                                                          │
│  - 拉取全书目录 + 全部章节正文（含 preview）                         │
│  - 并发搜索全部书源，缓存每本书的详情页 URL（sourceMap）             │
│  - 写入 metadata.json / process.jsonl / aggregate_book_tasks         │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Stage 2: 完整性补全（Completeness Completion）                      │
│  - 用官方字数 vs 实际拉取字数判断完整性                              │
│  - 不完整时 Agent 调用 source tool 从第三方源拉取                    │
│  - 输出完整或尽力补全的正文                                          │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Stage 3: 校对（Proofreading / Attribution）                         │
│  - Agent 判断章节是否确实属于本书                                    │
│  - 发现串书/错误时，调用 source tool 换源重拉                        │
│  - 输出 content_approved 或 fallback                                 │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Stage 4: 后处理（Post-processing）                                  │
│  - Agent 决定是否需要净化、去屏蔽词、校对整理                        │
│  - 每个动作对应一个 tool，按需调用                                   │
│  - 输出最终 .md 文件                                                 │
└─────────────────────────────────────────────────────────────────────┘
```

### 8.2 Stage 1: 订阅初始化

#### 8.2.1 主源选择

- 默认官方源优先。
- 若用户配置了 `sourcePriority`，按优先级选第一个可用源。
- 主源一旦选定，在订阅生命周期内不随意变更；仅当主源整书失效（目录不可达、全部章节为空）时才允许重新竞选。

#### 8.2.2 全书目录与正文拉取

- **目录**：一次性拉取全书目录，写入 `aggregate_chapter_tasks`。
- **正文**：并发拉取全部章节正文，允许 preview/不完整。
- 每章记录：
  - `official_word_count`：官方接口返回的本章字数（优先使用）。
  - `fetched_word_count`：实际拉取到的正文字数。
  - `content`：原始正文（可为 preview）。
  - 状态初始为 `fetched`。

字数统计规则：

```python
def count_chinese_chars(text: str) -> int:
    """统计中文字符、常见标点、数字、ASCII 单词，忽略纯空白。"""
    ...
```

#### 8.2.3 全书源搜索与 sourceMap

订阅初始化阶段，除了拉取主源，还要**并发搜索全部已启用书源**，找到本书在第三方源上的详情页地址。

搜索结果写入 `metadata.json` 的 `sourceMap`：

```json
{
  "sourceMap": {
    "kks101_com": {
      "bookUrl": "https://kks101.com/book/12345",
      "score": 120,
      "lastChapter": "第 388 章 风起",
      "progress": 388,
      "matchedAt": "2026-06-25T10:00:00Z",
      "searchTier": "tier1"
    }
  }
}
```

搜索阶段**不拉取第三方正文**，只存详情页 URL、评分、进度等元数据。

#### 8.2.4 书源过多处理策略

当已启用书源数量较多时（>20），需要避免全量并发搜索导致被封 IP 或任务耗时过长。

| 策略 | 说明 |
|---|---|
| **分级搜索** | 书源按质量分为 `tier1`（官方/大站）和 `tier2`（小站/镜像）。订阅时只搜 `tier1`；`tier2` 在补全失败时按需搜索。 |
| **缓存 TTL** | `sourceMap` 缓存 24h~7d，避免同一本书频繁全量搜索。 |
| **并发限制** | 全源搜索全局并发 <= 5，单源失败不影响其他源。 |
| **失败退避** | 源搜索失败时记录 `search_failed_at`，下次延长重试间隔。 |
| **用户白名单** | 设置中可指定“仅搜索”“不用于聚合”的书源。 |

#### 8.2.5 处理窗口调整

Stage 1 允许一次性拉取全书目录和正文（IO 密集，成本低）。Stage 2~4 的 AI 处理仍按窗口推进，避免一次性发起大量 AI 调用。

已确认规则：

- 目录刷新可以全量获取。
- Stage 1 正文拉取可一次性完成，但需控制并发（建议每源 <= 5）。
- Stage 2~4 每轮最多处理 5 章。
- 优先级：用户手动重试 > 新增章节 > 历史待处理章节 > 失败重试到期章节。

### 8.3 Stage 2: 完整性补全

#### 8.3.1 完整性判断

```python
def is_chapter_complete(fetched_content: str, official_word_count: int | None) -> bool:
    fetched_count = count_chinese_chars(fetched_content)
    if official_word_count and official_word_count > 0:
        ratio = fetched_count / official_word_count
        return ratio >= COMPLETENESS_RATIO  # 默认 0.85，可配置
    return fetched_count >= MIN_CHAPTER_LENGTH  # 兜底 200 字
```

- 官方字数 > 0 时，以字数比例为准。
- 官方无字数时，以绝对长度兜底。
- 特殊章节（番外、上架感言、请假条）跳过完整性补全。

#### 8.3.2 补全 Agent Loop

不完整的章节进入补全 Agent。Agent 根据当前状态选择调用 source tool 拉取第三方正文，或结束补全。

```text
1. 读取 sourceMap，按评分/进度排序候选源。
2. 选择下一个未尝试的候选源。
3. 调用 fetch_chapter_from_source(source_id, book_url, chapter_index, title)。
4. 调用 align_chapter(candidate_content, official_preview, title) 判断是否同一章。
5. 若对齐通过 → aggregate_contents 或直接采用，结束 Stage 2。
6. 若未通过 → 回到步骤 2，直到候选源耗尽。
7. 全部失败 → 标记 `completeness_failed`，携带最佳可用内容进入 Stage 3（校对 agent 决定）。
```

#### 8.3.3 Stage 2 Tools

| Tool | 输入 | 输出 |
|---|---|---|
| `fetch_chapter_from_source` | `source_id`, `book_url`, `chapter_index`, `title` | 第三方源对应章节正文、URL、字数 |
| `align_chapter` | `candidate_content`, `official_preview`, `title` | `is_same`, `confidence`, `reason` |
| `aggregate_contents` | `contents: list[str]`, `official_preview: str` | 聚合后的完整正文 |
| `self_rate` | `content` | `score`, `reason` |

### 8.4 Stage 3: 校对

所有章节（无论 Stage 2 是否补全）都进入校对 Agent。

#### 8.4.1 校对 Agent Loop

```text
1. 调用 attribution_check(content, book_name, author, title, previous_context)。
2. 若 confidence >= threshold → 通过，进入 Stage 4。
3. 若 confidence < threshold → 可能串书/广告正文/严重错误。
   a. 调用 find_alternative_source(chapter_index, excluded_source_ids)。
   b. 调用 fetch_chapter_from_source 拉取新源正文。
   c. 再次 attribution_check。
4. 多次失败后 → fallback（写入最佳可用内容 + 提示）。
```

#### 8.4.2 归属校验

归属校验返回结构化结果：

```json
{
  "belongsToBook": true,
  "confidence": 0.94,
  "reason": "主角名、章节标题和前文事件连续",
  "issues": []
}
```

校验重点：

- 主角名、核心设定是否一致。
- 上下文事件是否衔接。
- 章节标题是否匹配。
- 叙事风格是否明显不同。
- 是否混入其他小说正文或广告正文。

#### 8.4.3 Stage 3 Tools

| Tool | 输入 | 输出 |
|---|---|---|
| `attribution_check` | `content`, `book_name`, `author`, `title`, `previous_context` | `belongsToBook`, `confidence`, `reason`, `issues` |
| `find_alternative_source` | `chapter_index`, `excluded_source_ids` | 新的可用源及 `book_url` |
| `fetch_chapter_from_source` | 同上 | 同上 |

### 8.5 Stage 4: 后处理

校对通过后，进入后处理 Agent。后处理 Agent 根据正文内容决定调用哪些 tools。

#### 8.5.1 后处理 Agent Loop

```text
1. detect_blocked_words(content) → 有候选则 unmask_blocked_words。
2. purify(content) → 去广告、去站点提示、规范化格式。
3. proofread(content, previous_context) → 错字修正、分段整理。
4. self_rate(content) → score >= 0.85 可结束。
5. score < 0.85 时，可再次 proofread 或接受当前结果（记录提示）。
```

后处理 Agent 不一定需要 LLM 决策；第一阶段可用固定规则链，后续再升级为 LLM 决策。

#### 8.5.2 Stage 4 Tools

| Tool | 输入 | 输出 |
|---|---|---|
| `purify` | `content` | 去广告、去站点提示、压缩空行后的正文 |
| `detect_blocked_words` | `content` | 屏蔽词候选列表 |
| `unmask_blocked_words` | `content`, `candidates` | 恢复屏蔽词后的正文 |
| `proofread` | `content`, `previous_context` | 错字修正、格式整理后的正文 |
| `self_rate` | `content` | `score`, `reason` |

### 8.6 Source Tool / MCP-like 书源工具接口

为了让 Agent 能够调用书源，需要把书源访问封装成统一的工具接口。Agent 不需要知道书源插件、登录、反爬等细节，只通过标准接口请求数据。

#### 8.6.1 设计目标

- Agent 只调用高层工具函数，不直接访问插件。
- 所有书源访问走统一入口，便于缓存、限流、重试、审计。
- 未来新增书源时，只需在 Source Tool 层注册，不需要改 Agent 逻辑。
- 接口设计参考 MCP（Model Context Protocol）的 tool 调用语义。

#### 8.6.2 接口定义

```python
class SourceTool:
    """MCP-like interface exposed to the chapter processing agent."""

    async def search_book(
        self,
        query: str,
        author: str | None = None,
        source_ids: list[str] | None = None,
    ) -> list[SourceBookResult]:
        """Search for a book across sources."""

    async def get_book_detail(
        self,
        source_id: str,
        book_url: str,
    ) -> SourceBookDetail:
        """Fetch book detail page metadata."""

    async def get_chapter_list(
        self,
        source_id: str,
        book_url: str,
    ) -> list[SourceChapterItem]:
        """Fetch full chapter list from a source."""

    async def get_chapter_content(
        self,
        source_id: str,
        chapter_url: str,
    ) -> SourceChapterContent:
        """Fetch a single chapter's raw content."""
```

Agent 实际调用的 tool 函数更精简：

```python
async def fetch_chapter_from_source(
    source_id: str,
    book_url: str,
    chapter_index: int,
    chapter_title: str,
) -> dict:
    """
    Tool exposed to agent.
    Returns {
        "sourceId": "...",
        "chapterUrl": "...",
        "title": "...",
        "content": "...",
        "wordCount": 3500,
        "fetchedAt": "..."
    }
    """
```

#### 8.6.3 Source Tool 与 Agent 的集成

```text
┌─────────────────────────────────────────┐
│         ChapterProcessingAgent          │
│  - 维护 state                           │
│  - 调用 LLM 或规则决策                  │
│  - 调度 tools                           │
└─────────────────────────────────────────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
┌────────────┐ ┌──────────┐ ┌──────────┐
│ SourceTool │ │ AI Tools │ │ Text Ops │
└────────────┘ └──────────┘ └──────────┘
       │
       ▼
┌─────────────────────────────────────┐
│     Source Plugin Runtime           │
│  - 登录态管理                       │
│  - 缓存                             │
│  - 限流/重试                        │
└─────────────────────────────────────┘
```

### 8.7 Agent 决策模型

#### 8.7.1 阶段内决策

- **Stage 2 补全**、**Stage 3 校对** 建议由 LLM 决策（选择哪个源、是否通过对齐结果、是否换源）。
- **Stage 4 后处理** 第一阶段可用规则链，后续升级为 LLM 决策。

#### 8.7.2 决策 Prompt 结构

```markdown
你是小说章节处理协调器。当前任务：{stage}

书籍信息：
- 书名：{book_name}
- 作者：{author}
- 章节：{chapter_index} {title}

当前状态：
- 已处理步数：{step_count}
- 当前正文来源：{source_trace}
- 当前质量分：{current_score}
- 可用 tools：{tool_descriptions}

请输出下一步要调用的 tool：
{"tool": "...", "input": {...}, "reason": "..."}
或输出 {"tool": "finish", "reason": "..."}
```

### 8.8 失败降级与重试

#### 8.8.1 失败分类

在 Agent 模型下，失败分类需要扩展：

| 错误码 | 场景 | 默认处理 |
|--------|------|----------|
| `SOURCE_EMPTY_CONTENT` | 书源返回空正文 | 换源；无源则 fallback。 |
| `SOURCE_TIMEOUT` | 拉取正文超时 | 延迟重试。 |
| `SOURCE_AUTH_REQUIRED` | 官方源需要登录/购买 | 尝试候选源补充。 |
| `SOURCE_SEARCH_FAILED` | 源搜索失败 | 记录失败时间，延长重试。 |
| `ALIGNMENT_LOW_CONFIDENCE` | 候选源章节对齐失败 | 换源或 fallback。 |
| `ATTRIBUTION_LOW_CONFIDENCE` | 校对归属校验失败 | 换源或 fallback。 |
| `AI_RATE_LIMITED` | AI endpoint 限流 | 延迟重试。 |
| `AI_TIMEOUT` | AI 请求超时 | 延迟重试。 |
| `AI_BAD_REQUEST` | 请求体或模型参数错误 | 不自动重试。 |
| `AI_OUTPUT_DEVIATION` | 偏差值过低 | 调整 prompt 后重试。 |
| `FILE_WRITE_FAILED` | Markdown 写入失败 | 保留数据库结果，提示文件写入失败。 |

#### 8.8.2 重试退避

- 单章自动重试最多 5 次。
- 退避时间：5min / 15min / 30min / 60min / 120min。
- Stage 2 和 Stage 3 的“换源重试”不计入 AI 调用重试次数，但单源失败次数过多时标记该源为不可靠。
- 第一次 AI 处理失败且存在可用正文源时，立即写入 `fallback` 正文替换占位文件。
- 5 次 AI 重试后仍失败，保留 `fallback`；无可用正文时进入 `error`。

### 8.9 偏差值校验

#### 8.9.1 官方完整正文校验

当 Stage 2 未触发补全（主源完整）时，AI 输出应与主源原文保持高相似度。

偏差值 = 代码相似度 × 0.7 + AI 自评分映射 × 0.3

- 代码相似度：去除空格标点后的 LCS / SequenceMatcher。
- AI 自评分映射：`score = 1 - (rating - 1) / 9`。

#### 8.9.2 第三方补全校验

当 Stage 2 触发补全时，不能只看字面相似度，应使用语义一致性 + 多源互相相似性。

- `semanticConfidence >= 0.85`。
- AI 输出与至少一个已对齐候选源相似度 `>= 0.75`。
- 官方预览可用时，AI 输出必须语义覆盖预览关键事件。

### 8.10 分段策略

- 计算 prompt token（系统 prompt + 前文 + 当前正文）。
- 若总 token ≤ `modelContextLength * maxContextUseRatio`，整章一次性发送。
- 若超过：
  - 优先按段落切分，每段保留完整语义。
  - 每段仍携带标题与最小前文提示。
  - 结果按顺序拼接。
- 若单段仍超限，按句子切分（尽量避免）。
- 官方完整正文路径下，默认保留官方原始分段，只做空行压缩、明显广告清理和轻微格式整理。
- 多源补全文路径下，优先选择最可靠正文源的分段作为基准；只有多个来源分段冲突严重时，才让 AI 做保守分段整理。

### 8.11 前文校准

处理第 N 章时，从 `aggregate_chapter_tasks` 读取本书前 `includePreviousChapters` 章的已处理内容，截取末尾约 500~1000 字作为 `context`，帮助 AI 保持人名、地名、文风一致。

### 8.12 目录变更与断更恢复

聚合任务需要能长期跟随连载书更新，因此目录刷新不能简单覆盖历史状态。

已确认规则：

1. 章节目录永远以主源为准。官方源存在时以官方源为主源；官方源不存在时，以评选出来的第三方主源为准。
2. 每次刷新目录时，将当前主源目录视为权威目录，对聚合章节表和本地 Markdown 文件做同步。
3. 主源新增章节时，新增对应 `aggregate_chapter_tasks`，状态为 `fetched`，等待 Stage 2~4 处理。
4. 主源章节标题变更时，更新数据库标题；如该章节已写入本地 Markdown，需要按新标题重新生成文件路径。
5. 主源章节索引变更时，更新 `chapter_index`，并按新索引重新生成文件路径。
6. 主源章节仍存在但 `source_chapter_id` 变化时，标记该聚合章节为 `fetched`，按新主源章节重新处理。
7. 主源章节不存在时，对应聚合章节和本地 Markdown 不继续保留旧结果；实现时可以直接删除对应文件和任务，也可以标记为 `fetched` 后按新目录重新映射处理。
8. 主源切换后，目录和后续处理全部以新主源为准；受影响章节需要重新建立映射，已不匹配的本地文件删除或重新处理。
9. 断更后恢复更新时，以主源最新目录追加新章，并按同一套规则处理标题、索引和消失章节。

文件同步要求：

- 数据库中必须记录当前文件路径，便于标题或索引变化时删除旧文件。
- 删除文件失败不能中断目录刷新，但必须记录 `FILE_DELETE_FAILED`。
- 目录同步完成后，`processed_chapters`、`total_chapters`、`failed_chapters` 需要重新统计。

---

## 9. 占位文件与读取行为

### 9.1 占位文件生成

当用户打开聚合源书籍目录或尝试读取尚未处理完成的章节时：

1. 后端立即为该章节生成占位 `.md` 文件，内容为：

```markdown
# {章节标题}

聚合处理中……请先查看其他源或稍后刷新。
```

2. `aggregate_chapter_response` 返回：

```json
{
  "implemented": true,
  "chapterId": "...",
  "title": "...",
  "content": "聚合处理中……请先查看其他源或稍后刷新。",
  "debug": {
    "aggregate": true,
    "status": "pending"
  }
}
```

### 9.2 自动加入处理书架

仅当用户**主动选择 AI 聚合源**进入阅读时，才调用 `AggregateProcessor.enqueue_book()`。

判定条件：阅读端请求的 `book_id` 解码后 `source_id == VIRTUAL_SOURCE_ID`，且该书尚未在 `aggregate_book_tasks` 中或状态不是 `completed`。

---

## 10. 偏差值校验

### 10.1 计算方式

校验策略按正文来源拆分，不能用同一套「和主源原文相似」规则覆盖所有场景。

### 10.1.1 官方完整正文校验

官方源有完整正文时，官方源是唯一真源。AI 只允许做敏感词恢复、去广告、空行整理和轻微错字修复，因此使用偏保守的原文相似度校验。

偏差值 = 代码相似度 × 0.7 + AI 自评分映射 × 0.3

**代码相似度**：

1. 对 AI 输出和原始主源正文分别做预处理：
   - 去除换行、空格、制表符。
   - 去除标点符号。
   - 统一繁简（可选）。
2. 使用最长公共子序列（LCS）或 difflib.SequenceMatcher 计算相似度。
3. 得分 = 2 * LCS / (len(a) + len(b))。

**AI 自评分映射**：

请求 AI 对输出进行自评：

> 请评估你对原文的改写程度：1=几乎未改，10=大幅改写。只返回 1~10 的数字。

映射为：`score = 1 - (rating - 1) / 9`。

### 10.1.2 第三方补全文 / 敏感词恢复校验

当官方源不完整，需要第三方补全文，或正文存在大量屏蔽词恢复时，AI 输出可能与官方预览不完全相似。此时不能只看字面相似度，应使用「语义一致性 + 多源互相相似性」。

校验输入：

- 书名、作者、章节标题。
- 主源可获取的预览正文。
- 被采用的候选源正文。
- 其他通过章节对齐的候选源正文摘要。
- AI 输出正文。
- 前后章节摘要。

语义一致性校验：

- 让 AI 判断输出是否仍属于同一本书、同一章节。
- 检查主角名、核心设定、当前事件、上下文衔接是否一致。
- 检查是否出现明显串书、广告正文、站点提示、无关章节。
- 输出结构化结果：`semanticConsistent`、`semanticConfidence`、`reason`。

多源互相相似性校验：

- 对通过章节对齐的多个候选源正文做标准化。
- 比较 AI 输出与候选源正文的相似度。
- 比较候选源之间的相似度，判断候选源是否本身一致。
- 当多个候选源彼此相似，且 AI 输出与多数候选源语义一致时，可以通过。
- 当候选源之间差异大时，降低置信度，优先回退到最可靠正文源。

通过条件：

- `semanticConfidence >= 0.85`。
- 至少一个已对齐候选源与 AI 输出正文相似度 `>= 0.75`。
- 若有两个以上候选源通过对齐，则 AI 输出应与多数候选源保持相似。
- 官方预览正文可用时，AI 输出必须包含或语义覆盖预览中的关键事件。

失败处理：

- 语义一致性失败：进入 `AI_OUTPUT_DEVIATION`，重试。
- 多源相似性失败：尝试更换候选源；无可用候选源时进入 `fallback`。
- 重试 5 次仍失败：按 8.3.1 的 fallback 规则写入可用正文源。

### 10.2 阈值配置

| 设置项 | 可选值 | 说明 |
|--------|--------|------|
| `deviationThreshold` | 0.95 / 0.90 / 0.80 | 偏差值低于阈值时重试或回退。 |

推荐默认 `0.90`。

### 10.3 重试逻辑

- 校验不达标时，最多自动重试 5 次。
- 每次重试可调整 prompt、候选源或敏感词候选提示，但不得引入未经输入支持的新剧情。
- 第一次失败且存在可用正文源时，先写入 `fallback` 正文替换占位文件。
- 5 次仍不达标时，保留 `fallback` 正文；如果没有任何可用正文源，才进入不可读 `error`。

---

## 11. 聚合书架页面

### 11.1 路由

- `/console/aggregate-books`：聚合书架列表
- `/console/aggregate-books/:bookId`：单书详情

### 11.2 书架列表

展示字段：

| 字段 | 说明 |
|------|------|
| 书名 | `aggregate_book_tasks.name` |
| 作者 | `aggregate_book_tasks.author` |
| 状态 | `book_status`（连载/完结/未知） |
| 章节进度 | `processed_chapters / total_chapters` |
| Token 消耗 | `total_tokens` |
| 主源 | `primary_source_id` |
| 最近处理 | `last_processed_at` |
| 操作 | 查看详情、重新处理、删除 |

Tab 切换：「全部 / 进行中 / 已完成 / 失败」。

### 11.3 单书详情页

Tab 1「章节」：
- 章节列表：标题、索引、状态、token、偏差值。
- 点击章节：右侧抽屉打开 Markdown 正文预览。
- 失败章节：显示错误原因 + 重试按钮。

Tab 2「本章说」：
- 调用 `chapter_reviews` 展示章评与热评。
- 展示结构调整为「章评在上，热评在下」。
- 章评包含章末热评、普通本章说、作家说。
- 热评来自当前阅读页中的热门段评，不再把每段段评作为正文后气泡逐段展示。
- 热评点击后进入对应段落评论窗口，窗口内再展示该段完整评论列表。
- 聚合章节自身不生成评论，只映射回主源章节或最终采用的补充源章节。

Tab 3「统计」：
- 总 token、模型、平均耗时、失败率、来源分布。

Tab 4「设置」：
- 单本书是否启用 AI、并发数覆盖、优先级。

---

## 12. API 设计

### 12.1 聚合书架

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/console/aggregate-books` | 列出聚合书籍 |
| GET | `/api/console/aggregate-books/{book_id}` | 单书详情 |
| POST | `/api/console/aggregate-books/{book_id}/run` | 手动触发/重新处理 |
| POST | `/api/console/aggregate-books/{book_id}/pause` | 暂停处理 |
| POST | `/api/console/aggregate-books/{book_id}/resume` | 恢复处理 |
| DELETE | `/api/console/aggregate-books/{book_id}` | 删除聚合任务 |
| GET | `/api/console/aggregate-books/{book_id}/chapters` | 章节列表 |
| GET | `/api/console/aggregate-books/{book_id}/chapters/{chapter_id}` | 单章正文 |
| POST | `/api/console/aggregate-books/{book_id}/chapters/{chapter_id}/retry` | 重试单章 |
| GET | `/api/console/aggregate-books/{book_id}/chapters/{chapter_id}/reviews` | 本章说 |

### 12.1.1 分页与过滤

列表接口必须分页，避免控制台一次性加载大量章节或书籍。

`GET /api/console/aggregate-books` query：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | int | 1 | 页码，从 1 开始。 |
| `pageSize` | int | 20 | 每页数量，最大 100。 |
| `status` | string | `all` | `all` / `active` / `completed` / `paused` / `error`。 |
| `keyword` | string | 空 | 按书名、作者模糊搜索。 |
| `sort` | string | `updated_desc` | `updated_desc` / `created_desc` / `progress_desc` / `tokens_desc`。 |

响应：

```json
{
  "items": [
    {
      "bookId": "legadohub_ai_aggregate:...",
      "name": "示例书名",
      "author": "作者",
      "status": "active",
      "bookStatus": "ongoing",
      "primarySourceId": "qidian_com",
      "totalChapters": 1200,
      "processedChapters": 42,
      "failedChapters": 1,
      "progress": 0.035,
      "totalTokens": 123456,
      "lastProcessedAt": "2026-06-14T01:23:45Z",
      "nextCheckTime": "2026-06-14T01:53:45Z",
      "lastError": ""
    }
  ],
  "page": 1,
  "pageSize": 20,
  "total": 1
}
```

`GET /api/console/aggregate-books/{book_id}/chapters` query：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | int | 1 | 页码，从 1 开始。 |
| `pageSize` | int | 50 | 每页数量，最大 200。 |
| `status` | string | `all` | `all` / `fetched` / `completing` / `proofreading` / `post_processing` / `processed` / `fallback` / `error` / `skipped`。 |
| `keyword` | string | 空 | 按章节标题模糊搜索。 |

响应：

```json
{
  "items": [
    {
      "chapterId": "legadohub_ai_aggregate:...",
      "chapterIndex": 1,
      "title": "第一章",
      "status": "processed",
      "contentLength": 3200,
      "aiModel": "deepseek-chat",
      "aiTotalTokens": 5200,
      "deviationScore": 0.96,
      "fallbackSourceId": "",
      "retryCount": 0,
      "lastProcessedAt": "2026-06-14T01:23:45Z",
      "error": ""
    }
  ],
  "page": 1,
  "pageSize": 50,
  "total": 1
}
```

`GET /api/console/aggregate-books/{book_id}/chapters/{chapter_id}` 响应：

```json
{
  "chapterId": "legadohub_ai_aggregate:...",
  "chapterIndex": 1,
  "title": "第一章",
  "status": "processed",
  "content": "Markdown 正文",
  "source": {
    "primarySourceId": "qidian_com",
    "fallbackSourceId": "",
    "alignment": {}
  },
  "ai": {
    "enabled": true,
    "model": "deepseek-chat",
    "promptTokens": 3000,
    "completionTokens": 2200,
    "totalTokens": 5200,
    "latencyMs": 8000,
    "deviationScore": 0.96
  },
  "error": ""
}
```

`GET /api/console/aggregate-books/{book_id}/chapters/{chapter_id}/reviews` 响应：

```json
{
  "chapterId": "legadohub_ai_aggregate:...",
  "mappedChapterId": "qidian_com:...",
  "mappedSourceId": "qidian_com",
  "mappingReason": "primary_source",
  "chapterEndHot": [],
  "chapterEnd": [],
  "authorReviews": [],
  "hotParagraphReviews": [
    {
      "paragraphId": 59,
      "paragraphText": "原评论来源段落文本或摘要",
      "matchedText": "聚合正文中模糊匹配到的文本片段",
      "matchConfidence": 0.91,
      "hotCommentCount": 34,
      "totalCommentCount": 45,
      "topReviews": []
    }
  ],
  "paragraphs": {},
  "summary": {
    "chapterEndHot": 0,
    "chapterEnd": 0,
    "authorReviews": 0,
    "hotParagraphReviews": 0,
    "paragraphs": 0,
    "paragraphReviewCount": 0
  },
  "debug": {
    "aggregate": true,
    "reviewSource": "primary_source"
  }
}
```

评论映射规则：

1. 默认映射回主源章节评论，保证官方源 VIP 预览章节也能查看完整章评和段评。
2. 如果正文最终使用候选源回退，但主源章节仍可获取评论，评论仍使用主源。
3. 只有当主源章节没有评论能力，且候选源明确提供评论能力时，才允许映射到候选源。
4. 聚合章节不混合多个来源的评论，避免同一段落评论语境错乱。
5. 不再按正文每段追加段评气泡；段评改为热评入口。
6. 热评优先来自起点新版本机制中的热门段评数据，例如摘要数据中的 `HasHotComment`、`Getparagraphshotcommentcounts` 和 `Reviews`。
7. 热评与聚合正文通过段落原文或段落摘要做模糊匹配，不能强依赖 AI 整理后的段落编号。
8. 热评气泡在阅读页右上角展示，例如「热评 22」；点击后打开当前页热评列表。
9. 点击某条热评时，根据 `paragraphId` 跳转到对应段落评论窗口，再加载该段完整评论列表。
10. 每章末尾仍显示总评论入口，点开后展示类似当前后端模拟样式：上方章评，下面接热评/段评列表。
11. 评论接口必须透传 `chapterEndHot`、`chapterEnd`、`authorReviews`、`hotParagraphReviews`；`paragraphs` 仅作为点开某段后的完整评论数据，不作为默认正文气泡展示数据。

起点热评数据来源：

- App 抓包样本中 `getchapterrepagesummary` 返回 `Getparagraphshotcommentcounts`，包含各 `ParagraphId` 的热门评论计数。
- 同一摘要响应中的 `Reviews` 可直接返回当前章节或当前页热门评论，并带有 `ParagraphId`、`ReviewId`、`Content`、`Type`。
- `getparagraphscomments` 可按 `paragraphId` 拉取某段完整评论列表，用于点击热评后的详情窗口。
- Web 端 `reviewsummary4m` 中也有 `isHotSegment` / `isHotComment`，可作为兼容信号。

状态语义：

| 状态 | 含义 | 前端展示 | 是否可重试 |
|------|------|----------|------------|
| `fetched` | Stage 1 已完成，已拉取主源正文 | 已抓取 | 否 |
| `completing` | Stage 2 完整性补全中 | 补全中 | 否 |
| `proofreading` | Stage 3 校对中 | 校对中 | 否 |
| `post_processing` | Stage 4 后处理中 | 整理中 | 否 |
| `processed` | 全部阶段完成 | 已完成 | 是，作为重新处理 |
| `fallback` | 处理失败但已有可用正文 | 已回退原文 | 是 |
| `error` | 无可用正文 | 处理失败 | 是 |
| `skipped` | 特殊章节跳过 | 已跳过 | 是 |

### 12.2 聚合设置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/console/aggregate-settings` | 获取聚合设置 |
| POST | `/api/console/aggregate-settings` | 保存聚合设置 |
| POST | `/api/console/aggregate-settings/test-provider` | 测试 Provider 连通性 |
| POST | `/api/console/aggregate-settings/fetch-models` | 从 endpoint 拉取模型列表 |

设置接口响应时必须脱敏 `apiKey`，并额外返回 `hasApiKey`：

```json
{
  "contentWorkflow": {},
  "aiProviderConfig": {
    "provider": "openai_compatible",
    "baseUrl": "https://api.deepseek.com/v1",
    "model": "deepseek-chat",
    "apiKey": "sk-...abcd",
    "hasApiKey": true
  }
}
```

### 12.3 阅读入口

已有 `Catalog._aggregate_book_detail` 会调用 `AggregateProcessor().enqueue_book()`，需增加条件：仅当用户主动选择聚合源时加入。

---

## 13. 搜索界面集成

在后端搜索与控制台搜索任务结果中，聚合源条目（`sourceId == legadohub_ai_aggregate`）的交互按钮改为：

- **加入处理**：将聚合书加入 `aggregate_book_tasks` 队列，并返回提示「已加入 AI 聚合书架」。
- 不直接打开阅读详情，避免用户读到未处理完成的占位内容。

前端 `SearchJobs.tsx` 中需识别 `item.aggregate` 并渲染对应按钮。

---

## 14. Prompt 设计

### 14.1 系统 Prompt

```markdown
你是一名专业网络小说编辑。你的任务是对用户提供的小说章节进行清洗、校正和整理，同时严格保持原文剧情、风格、人称和角色名不变。

处理要求：
1. 删除与正文无关的内容：广告、推广语、作者感言、导航链接、盗版网站水印、APP 下载提示等。
2. 修正 OCR 错误、乱码、错字、重复字。
3. 正确分段：对话独立成段，场景转换空一行，避免过度分段或长段不分。
4. 如果存在屏蔽词（如 *、□、x 替代的字），优先参考系统提供的敏感词候选，并根据上下文合理恢复，保持语义通顺。
5. 当主源内容明显不完整（如只有几十字预览）时，以主源为框架，结合其他来源补充完整正文。
6. 不要凭空想象或新增输入正文中不存在、且无法由上下文确定的剧情。
7. 不要添加前言、总结、标题或任何格式说明，只返回正文。
```

### 14.2 用户 Prompt 模板

```markdown
本书信息：
- 书名：{book_name}
- 作者：{author}
- 当前章节：{title}

前文参考（保持风格一致）：
{context}

当前章节正文：
{content}

敏感词恢复候选（仅供参考，不要机械替换）：
{blocked_word_candidates}

请直接返回处理后的正文：
```

变量说明：

| 变量 | 含义 |
|------|------|
| `book_name` | 书名 |
| `author` | 作者 |
| `title` | 章节标题 |
| `context` | 前若干章末尾内容 |
| `content` | 当前章节原始正文（主源 + 必要时补充的候选源） |
| `blocked_word_candidates` | 由本地敏感词词库和屏蔽符扫描得到的恢复候选 |

---

## 15. 文件存储

### 15.1 目录结构

订阅聚合书（长期保存）：

```
backend/data/novels/
└── legadohub/
    └── {书名}_{作者}/
        ├── metadata.json
        ├── 000001 第一章 风起.md
        ├── 000002 第二章 云涌.md
        └── ...
```

第三方书源缓存（临时，可清理）：

```
backend/data/novels/
└── {source-domain}/
    └── {encoded-book-key}/
        ├── 000001 第一章.md
        └── ...
```

- `legadohub/` 存放订阅聚合书，按 `书名_作者` 组织，便于用户本地整理。
- `metadata.json` 记录 `bookId`、`bookName`、`author`、`sourceId`、`chapterCount` 等，方便外部程序读取。
- 第三方书源缓存按 `来源域名/编码书籍键` 组织，`encoded-book-key` 为 `book_id` 或 `source_id:chapter_url` 的短哈希，后台定期清理。

### 15.2 文件格式

```markdown
# 第一章 风起

正文第一段。

正文第二段。
```

### 15.3 元数据

数据库保留完整元数据；订阅书目录下额外写入 `metadata.json`，便于用户或外部工具直接识别目录内容。文件正文保持简洁，仅标题 + 正文，便于直接阅读。

### 15.4 文件命名与清理策略

本地 Markdown 是用户可直接阅读和长期保存的成果，因此文件路径要稳定。

已确认规则：

- 文件名格式固定为 `{chapter_index:06d} {safe_title}.md`。
- `safe_title` 需要移除 Windows 非法字符：`< > : " / \ | ? *`，并压缩连续空白。
- 文件名过长时截断标题部分，保证完整路径不超过 Windows 常见限制。
- 订阅书目录格式为 `书名_作者`，作者为空时退化为 `书名`。
- 文件路径由主源目录驱动；主源章节标题或索引变化时，按新目录重命名或重写文件。
- 主源章节删除时，本地对应 Markdown 文件也删除。
- 删除聚合任务时，默认同步删除本地 Markdown 文件，因为这些文件是聚合任务产物。
- 第一版只保存最终 Markdown，不保存原始正文、AI 处理正文、失败回退正文的多版本文件。
- 如需调试原始正文或候选源正文，只在数据库调试字段或日志中短期保存，不写入用户可读目录。
- 数据库需要保存当前文件路径，便于后续标题/索引变化和任务删除时清理旧文件。
- 第三方书源缓存目录为临时目录，AggregateProcessor 每运行若干轮后清理超过 TTL 的缓存目录。

### 15.5 启动扫描与恢复

服务启动时自动扫描 `backend/data/novels/legadohub/` 下的 `metadata.json`：

1. 若 `metadata.json` 对应的书籍在 `aggregate_book_tasks` 中不存在，则根据 metadata 重建该书记录。
2. 扫描目录下的 `.md` 章节文件，按文件名解析章节序号与标题。
3. 若某章节在 `aggregate_chapter_tasks` 中不存在，则根据文件内容恢复该章节记录。
4. 恢复后的书籍可立即在阅读端搜索和继续追更，已下载章节不会被重复处理。
5. 扫描过程跳过已存在的章节，避免重复数据。

### 15.6 订阅即会话：处理事件流（预计规划）

> 参考 AI 终端会话存储方式（如 Kimi Code CLI 的 `~/.kimi/sessions/{workdir}/{session_id}/context.jsonl`），将每个订阅书视为一个会话，处理过程以事件流形式持久化到本地 JSONL 文件。

#### 设计原则

- **一个订阅一个会话**：会话与 `aggregate_book_id` / 书籍目录一一对应，不拆分到章节，避免目录爆炸。
- **事件流追加写**：处理过程中的关键步骤以 JSON Lines 形式追加写入 `process.jsonl`，不修改历史内容。
- **目录自包含**：会话元数据、事件流、章节正文放在同一个书籍目录下，便于迁移和外部工具读取。
- **数据库为辅，文件为主**：事件流作为处理日志的权威来源，数据库保留索引和最新状态。

#### 目录结构

```
backend/data/novels/legadohub/{书名}_{作者}/
├── metadata.json              # 会话元数据（含 processLog 路径）
├── process.jsonl              # 处理事件流
├── 000001 第一章.md
├── 000002 第二章.md
└── ...
```

#### metadata.json 扩展字段

```json
{
  "bookId": "...",
  "bookName": "...",
  "author": "...",
  "processLog": "process.jsonl",
  "lastProcessedAt": "2026-06-25T10:00:00Z",
  "lastProcessedChapterIndex": 388
}
```

#### process.jsonl 事件类型

每条事件至少包含 `ts`（ISO-8601 时间戳）、`event`（事件类型），以及事件相关字段。事件按四阶段组织：

**Stage 1: 订阅初始化**

```json
{"ts":"2026-06-25T10:00:00Z","event":"book_task_start","bookId":"..."}
{"ts":"2026-06-25T10:00:01Z","event":"primary_source_selected","sourceId":"qidian_com","bookUrl":"..."}
{"ts":"2026-06-25T10:00:02Z","event":"toc_fetched","totalChapters":633}
{"ts":"2026-06-25T10:00:03Z","event":"source_search_start","tier":"tier1"}
{"ts":"2026-06-25T10:00:04Z","event":"source_search_result","sourceId":"kks101_com","bookUrl":"...","score":120,"progress":388}
{"ts":"2026-06-25T10:00:05Z","event":"source_search_failed","sourceId":"example_com","errorCode":"SOURCE_SEARCH_FAILED"}
{"ts":"2026-06-25T10:00:06Z","event":"chapter_fetch","chapterIndex":1,"source":"qidian_com_app","classification":"preview","officialWordCount":3500,"fetchedWordCount":120}
{"ts":"2026-06-25T10:00:07Z","event":"stage1_complete","totalChapters":633,"fetchedChapters":633}
```

**Stage 2: 完整性补全**

```json
{"ts":"2026-06-25T10:00:08Z","event":"completeness_check","chapterIndex":1,"officialWordCount":3500,"fetchedWordCount":120,"complete":false}
{"ts":"2026-06-25T10:00:09Z","event":"tool_call","chapterIndex":1,"stage":"completing","tool":"fetch_chapter_from_source","sourceId":"kks101_com"}
{"ts":"2026-06-25T10:00:10Z","event":"tool_result","chapterIndex":1,"stage":"completing","tool":"align_chapter","confidence":0.91,"accepted":true}
{"ts":"2026-06-25T10:00:11Z","event":"completeness_complete","chapterIndex":1,"sourceId":"kks101_com","wordCount":3450}
```

**Stage 3: 校对**

```json
{"ts":"2026-06-25T10:00:12Z","event":"tool_call","chapterIndex":1,"stage":"proofreading","tool":"attribution_check"}
{"ts":"2026-06-25T10:00:13Z","event":"tool_result","chapterIndex":1,"stage":"proofreading","tool":"attribution_check","belongsToBook":true,"confidence":0.94}
{"ts":"2026-06-25T10:00:14Z","event":"proofreading_complete","chapterIndex":1,"passed":true}
```

**Stage 4: 后处理**

```json
{"ts":"2026-06-25T10:00:15Z","event":"tool_call","chapterIndex":1,"stage":"post_processing","tool":"detect_blocked_words","candidateCount":3}
{"ts":"2026-06-25T10:00:16Z","event":"tool_call","chapterIndex":1,"stage":"post_processing","tool":"unmask_blocked_words"}
{"ts":"2026-06-25T10:00:17Z","event":"tool_call","chapterIndex":1,"stage":"post_processing","tool":"proofread"}
{"ts":"2026-06-25T10:00:18Z","event":"tool_result","chapterIndex":1,"stage":"post_processing","tool":"self_rate","score":0.92}
{"ts":"2026-06-25T10:00:19Z","event":"chapter_write","chapterIndex":1,"status":"processed","contentLength":3401}
```

**通用事件**

```json
{"ts":"2026-06-25T10:00:20Z","event":"ai_call","chapterIndex":1,"stage":"post_processing","tool":"proofread","model":"mimo-v2.5","promptTokens":1234,"completionTokens":6789,"totalTokens":8023}
{"ts":"2026-06-25T10:00:21Z","event":"chapter_error","chapterIndex":3,"stage":"completing","errorCode":"SOURCE_TIMEOUT","retryable":true}
{"ts":"2026-06-25T10:00:22Z","event":"chapter_fallback","chapterIndex":3,"sourceId":"qidian_com_app","reason":"all_sources_failed"}
```

事件字段说明：

| 事件 | 说明 |
|------|------|
| `book_task_start` | 书籍处理任务启动 |
| `primary_source_selected` | Stage 1 主源选定 |
| `toc_fetched` | 目录拉取完成 |
| `source_search_start` | 开始搜索第三方源 |
| `source_search_result` | 搜索到可用源 |
| `source_search_failed` | 某源搜索失败 |
| `chapter_fetch` | 单章主源正文拉取完成 |
| `stage1_complete` | Stage 1 完成 |
| `completeness_check` | 完整性判断 |
| `completeness_complete` | 完整性补全完成 |
| `tool_call` | Agent 调用某个 tool |
| `tool_result` | Tool 执行结果 |
| `proofreading_complete` | 校对完成 |
| `ai_call` | 发起 AI 调用 |
| `chapter_write` | 写入最终 .md |
| `chapter_error` | 章节处理错误 |
| `chapter_fallback` | 章节进入 fallback |

#### 与现有系统的配合

- 事件流不替代当前 `aggregate_chapter_tasks` 中的状态字段和 `policy_snapshot_json`，而是作为更完整、更适合人类阅读和外部审计的处理日志。
- 前端「处理日志」可先继续读取 `processing-logs` API；未来可新增读取 `process.jsonl` 的接口，提供更详细的时间线。
- 文件末尾的 YAML trace block 可逐步精简，仅保留关键摘要，详细信息以 `process.jsonl` 为准。

---

## 16. 实施路线

### Phase 1：AI Provider 与设置基础

1. 创建 `backend/app/ai/` 模块：
   - `models_catalog.py`：内置模型元数据。
   - `compat.py`：根据 `provider` / `baseUrl` / `model` 自动推断 `compat`。
   - `request_builder.py`：根据 `compat` 与 `thinkingLevel` 构造请求体。
   - `client.py`：`httpx` 异步客户端、流式响应解析、错误处理。
   - `encryption.py`：API Key Fernet 加密与脱敏。
2. 实现 OpenAI 兼容 Provider、模型列表获取、连通性测试。
3. 新增 `aggregate_settings` 表与读写封装。
4. 新增 `/api/console/aggregate-settings` API（含 `test-provider`、`fetch-models`）。
5. 前端新增 `/console/aggregate-settings` 分页。

### Phase 2：订阅初始化与 Source Tool

1. 实现 `AggregatePrimarySelector`（主源选择，Stage 1 的一部分）。
2. 扩展 `aggregate_book_tasks` 字段（sourceMap、字数等）。
3. 实现 `SourceTool` / MCP-like 书源工具接口：
   - `search_book`
   - `get_book_detail`
   - `get_chapter_list`
   - `get_chapter_content`
   - 对 Agent 暴露的 `fetch_chapter_from_source`
4. 实现全源搜索与 `sourceMap` 缓存，支持分级搜索、并发限制、失败退避。
5. 修改 `AggregateProcessor`：
   - `bootstrap_book`：一次性拉取全书目录 + 全部章节正文。
   - 写入 `metadata.json` 的 `sourceMap`。
6. 新增 `aggregate_source_map` 表与同步逻辑。

### Phase 3：Agent 驱动的章节处理

1. 创建 `backend/app/services/chapter_tools/` 目录，实现独立 tools：
   - `purify_tool.py`
   - `attribution_tool.py`
   - `aggregate_tool.py`
   - `unmask_tool.py`
   - `proofread_tool.py`
   - `self_rating_tool.py`
   - `fetch_chapter_tool.py`（封装 SourceTool）
2. 实现 `ChapterProcessingAgent`：
   - 维护 `ChapterProcessingState`。
   - Stage 2 完整性补全 loop。
   - Stage 3 校对 loop。
   - Stage 4 后处理 loop（第一阶段可用规则链）。
3. 将现有 `AggregateAIService` 的三个大方法迁移到 tools，保持旧接口作为兼容层。
4. 修改 `_process_chapter`，改为调用 `ChapterProcessingAgent`。
5. 扩展 `aggregate_chapter_tasks` 阶段字段与状态。

### Phase 4：偏差校验与失败降级

1. 实现 `compute_deviation_score`（官方完整正文 + 第三方补全两条路径）。
2. 实现失败分类与重试退避。
3. 实现 `fallback` 写入策略。
4. 扩展 `aggregate_ai_usage` 记录 AI 调用明细。

### Phase 5：占位文件与本地存储

1. 未处理章节读取时生成占位 `.md`。
2. Agent 处理完成后写入正式 `.md`。
3. 实现 `process.jsonl` 事件追加写。
4. 验证本地文件可直接阅读。

### Phase 6：聚合书架页面

1. 新增 `/console/aggregate-books` 列表页。
2. 新增 `/console/aggregate-books/:bookId` 详情页。
3. 实现章节预览、本章说、统计、重试。

### Phase 7：搜索界面改造

1. 后端搜索返回中保留聚合源标记。
2. 前端搜索界面聚合源按钮改为「加入处理」。

### Phase 8：验收与文档

1. 跑通完整测试套件。
2. 更新 README 与插件契约文档中的 AI 聚合说明。

### 16.1 测试验收矩阵

| 模块 | 测试内容 | 建议测试文件 |
|------|----------|--------------|
| 数据迁移 | 旧库启动后自动补齐 `aggregate_*` 新字段，旧任务仍可读取。 | `dev-assets/tests/test_db.py` |
| 设置迁移 | `admin_settings.contentWorkflow` 能迁移到 `aggregate_settings.contentWorkflow`。 | `dev-assets/tests/test_aggregate_settings.py` |
| Source Tool | `fetch_chapter_from_source` 能正确调用书源插件并返回正文。 | `dev-assets/tests/test_source_tool.py` |
| 全源搜索 | 分级搜索、并发限制、sourceMap 缓存、失败退避。 | `dev-assets/tests/test_source_search.py` |
| 完整性判断 | 官方字数 vs 实际字数比例正确。 | `dev-assets/tests/test_completeness_check.py` |
| Agent Loop | Stage 2~4 能按状态推进，tool 调用可记录。 | `dev-assets/tests/test_chapter_processing_agent.py` |
| 章节对齐 | 索引一致标题相似时可补充；标题差异大时拒绝。 | `dev-assets/tests/test_aggregate_alignment.py` |
| 归属校验 | 串书/广告正文能被识别并换源。 | `dev-assets/tests/test_attribution_check.py` |
| 处理窗口 | Stage 1 可全量拉取，Stage 2~4 按窗口推进。 | `dev-assets/tests/test_aggregate_processor.py` |
| 目录变更 | 新增章节被追加，已处理章节不因标题变更重跑。 | `dev-assets/tests/test_aggregate_processor.py` |
| 敏感词词库 | 词库可加载，屏蔽符上下文能生成候选，候选不会被机械替换。 | `dev-assets/tests/test_sensitive_lexicon.py` |
| AI 请求构造 | 不同 `compat` 与 `thinkingLevel` 生成正确请求体。 | `dev-assets/tests/test_ai_request_builder.py` |
| 偏差校验 | 高相似文本通过，低相似文本触发重试或回退。 | `dev-assets/tests/test_aggregate_deviation.py` |
| 失败退避 | timeout、rate limit、bad request 对应不同 retry 策略。 | `dev-assets/tests/test_aggregate_retry.py` |
| process.jsonl | 事件追加写、数据库状态同步。 | `dev-assets/tests/test_process_jsonl.py` |
| 文件落盘 | 文件名清洗、重复写入、删除任务时同步清理本地 Markdown。 | `dev-assets/tests/test_novel_file_cache.py` |
| 控制台 API | 列表分页、章节分页、详情响应、设置脱敏。 | `dev-assets/tests/test_plugin_console_api.py` |
| 评论映射 | 聚合章节评论能映射回主源章节，并保留章评与热评结构。 | `dev-assets/tests/test_aggregate_reviews.py` |
| 热评匹配 | 起点热评能从摘要接口提取，并通过模糊匹配关联到聚合正文片段。 | `dev-assets/tests/test_aggregate_reviews.py` |
| 前端构建 | 聚合书架、设置页、搜索按钮改造后能通过构建。 | `frontend` 的 `npm run build` |

---

## 17. 风险与待确认

| 风险 | 影响 | 应对 |
|------|------|------|
| AI 输出过度改写 | 正文失真 | 偏差值校验 + 低 temperature + 重试机制 |
| 官方源 VIP 章节只有预览 | 聚合结果短 | Stage 2 Agent 自动拉取第三方源补充 |
| Agent 决策错误 | 选错源、过度补全 | tool 结果日志 + 人工重试 + 阈值约束 |
| 书源搜索被封 IP | 无法获取第三方源 | 分级搜索 + 并发限制 + 缓存 TTL |
| sourceMap 与第三方源过期 | 补全时 URL 失效 | 缓存 TTL + 搜索失败退避 + 按需刷新 |
| 长章节 token 超限 | 成本/失败 | 分段策略 + 最大上下文使用比例限制 |
| AI endpoint 不稳定 | 任务失败率高 | 最多重试 5 次 + 首次失败先写入可用 fallback 正文 |
| API Key 泄露 | 安全 | Fernet 加密 + 接口脱敏 |
| 并发过高压垮 endpoint | 稳定性 | 全局 + 单书并发控制 |
| 用户误点「加入处理」 | 资源浪费 | 二次确认 + 可删除任务 |

### 已确认收口事项

1. 聚合结果 `.md` 文件头部不加 YAML frontmatter；书名、作者、来源、处理时间、token、偏差值等元数据只保存在数据库。
2. 偏差值计算第一版不引入中文分词；如后续误判较多，再考虑字符 n-gram 相似度。
3. 热评气泡第一版使用通用样式，依赖阅读页主题变量自动适配，不为每个主题单独写样式。
4. 热评气泡显示文案为「热评 N」，不带来源名前缀。

---

## 18. 参考

- [cc-switch](https://github.com/farion1231/cc-switch)：AI Provider 配置参数设计参考（`baseUrl`、`apiKey`、`model`、`endpointCandidates`、`modelsUrl` 等）。
- [opencode](https://github.com/anomalyco/opencode)：请求体与 provider 抽象参考（`temperature`、`top_p`、`frequencyPenalty`、`presencePenalty`、`max_tokens`、`customBodyParams` 等）。
- [earendil-works/pi](https://github.com/earendil-works/pi)：协议库设计移植来源。具体移植 `packages/ai/src/models.generated.ts`（模型元数据、`thinkingLevelMap`）与 `packages/ai/src/providers/openai-completions.ts`（`compat` 兼容层）到 Python 后端。pi 本身通过 [models.dev](https://models.dev/api.json) 的 `limit.context` / `limit.output` 获取并维护模型数据。
- `docs/architecture/source-plugin-contract.md`：书源插件契约。
- `backend/app/services/aggregate_processor.py`：现有聚合处理器。
- `backend/app/services/aggregate_virtual_source.py`：虚拟聚合源实现。
