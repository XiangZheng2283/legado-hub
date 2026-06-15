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
    status TEXT DEFAULT 'pending',            -- 'pending' | 'fetching' | 'ai_processing' | 'processed' | 'error' | 'skipped' | 'fallback'
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
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

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

## 7. 主源选择策略

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

## 8. AI 处理流程

### 8.1 单章处理状态机

```
pending -> fetching -> ai_processing -> processed
                              |
                              v
                           fallback
                              |
                              v
                           error
```

### 8.2 处理步骤

1. **拉取主源章节** → 状态 `fetching`。
2. **判断主源内容完整性**：
   - 若主源内容过短（如 < 200 字）且存在 VIP/付费标识，标记为「主源不完整」。
3. **补充候选源**（仅当主源不完整时）：
   - 按评分从高到低拉取其他候选源同章节。
   - 选择内容最长且无明显乱码的作为补充。
4. **传统净化**：空行压缩、去广告关键词。
5. **敏感词候选定位**：
   - 先用本地敏感词词库扫描原文，定位可能被 `*`、`□`、`x`、空格、谐音或拆字屏蔽的位置。
   - 词库主要来源使用 [konsheng/Sensitive-lexicon](https://github.com/konsheng/Sensitive-lexicon) 的本地副本。
   - 扫描结果只作为候选提示，不直接替换正文，避免机械误恢复。
6. **组装 Prompt**：
   - system prompt + 用户配置的系统提示词。
   - user prompt 中包含书名、作者、章节标题、前文参考、当前正文。
   - 当启用敏感词恢复时，同时传入敏感词候选、屏蔽位置和上下文片段，让 AI 结合语义做最终恢复。
7. **AI 调用** → 状态 `ai_processing`。
8. **结果校验**：
   - 官方完整正文场景：使用原文相似度校验，防止 AI 过度改写。
   - 第三方补全文 / 敏感词恢复场景：使用语义一致性 + 多源相似性校验，防止把正确补全误判为偏差过大。
   - 校验不通过时按失败分类进入重试或回退。
9. **写入结果**：
   - `processed_content` 入库。
   - 生成 `{index:06d} {title}.md` 明文文件。
10. **更新统计**：token、耗时、状态、偏差值。

### 8.2.1 AI 调用时机

不同正文来源使用不同处理路径，避免 AI 凭空补写。

1. **官方完整正文**
   - 官方源有完整正文时，先将官方正文做轻量清洗后直接写入本地 Markdown。
   - 写入后再异步调用 AI 做一次简单判断分析，检查敏感词、乱码、广告残留、明显错字和分段问题。
   - AI 分析结果通过校验后，可以覆盖本地文件；不通过时保留已写入的官方正文。
   - 这个路径不读取第三方正文，不做跨源聚合。

2. **官方不完整，但第三方通过章节校验**
   - 只能使用官方预览正文和已经通过章节对齐校验的候选源正文。
   - 调用 AI 做聚合补全文、敏感词恢复和整理。
   - Prompt 必须明确禁止凭空想象内容；未在输入正文中出现或无法从上下文确定的内容不得新增。
   - AI 输出必须通过语义一致性和多源相似性校验。

3. **第三方主源**
   - 每章处理前先调用 AI 做正文归属校验，判断该章节是否确实属于这本书。
   - 归属校验通过后，再调用 AI 做敏感词恢复、去广告和简单整理。
   - 归属校验不通过时，尝试其他候选源；无可用候选源时进入 `fallback/error`。

### 8.2.2 敏感词词库与恢复链路

敏感词恢复采用「词库定位 + AI 语义恢复」两阶段，而不是让 AI 凭空猜。

主要词库：

- 仓库：[konsheng/Sensitive-lexicon](https://github.com/konsheng/Sensitive-lexicon)
- 许可：MIT
- 用途：作为本地敏感词、变体词、风险词候选来源。

落地方式：

1. 将词库作为本地资源放入 `backend/data/lexicons/Sensitive-lexicon`，不在运行时依赖网络。
2. 启动时加载词库并构建 Trie / DFA 匹配结构，避免每章重复解析文件。
3. 扫描正文中的明显屏蔽符号：`*`、`＊`、`□`、`x`、`X`、空格拆字、同音替代、形近字替代。
4. 对每个疑似屏蔽位置截取前后上下文，结合词库命中候选生成 `blocked_word_candidates`。
5. Prompt 中把候选词作为「参考候选」传给 AI，要求 AI 只在上下文充分支持时恢复。
6. AI 输出后再次做偏差值校验，避免敏感词恢复导致剧情或语义过度改写。
7. 记录每章恢复统计：候选数量、AI 采用数量、低置信度跳过数量。

候选结构示例：

```json
{
  "blockedWordCandidates": [
    {
      "offset": 128,
      "maskedText": "杀*",
      "contextBefore": "他眼中闪过一丝",
      "contextAfter": "意，手中长剑出鞘",
      "candidates": ["杀意"],
      "confidence": 0.72
    }
  ]
}
```

安全规则：

- 词库命中不等于自动替换。
- 无上下文支持的候选必须跳过。
- 多候选冲突时交给 AI 判断；AI 无法判断时保留原文。
- 官方源完整正文只做轻量敏感词恢复与整理，不引入第三方正文。

### 8.2.3 处理窗口与队列策略

后端不能在一本书加入后一次性抓取和处理全部章节。目录可以刷新完整列表，但正文抓取、AI 调用、文件写入必须按窗口推进。

已确认规则：

- 目录刷新可以全量获取，但正文抓取每次只处理一个小窗口。
- 首次加入默认处理前 5 章。
- 阅读端打开聚合章节时，第一版直接返回本地生成的占位 Markdown 文件，不做同步等待。
- 阅读端自动缓存后续章节时，也返回对应占位 Markdown；后台 worker 按窗口自然处理，不为阅读缓存请求额外插队。
- 后台每本书每轮最多处理 5 章。
- 优先级：用户手动重试 > 新增章节 > 历史待处理章节 > 失败重试到期章节。
- 一本书处理完当前窗口后释放 worker，让队列里的下一本书继续推进。

暂不采用的方案：

- 不在章节读取接口中等待 AI 处理完成后再返回，避免阅读端请求长时间挂起。
- 不在第一版加入复杂的「当前阅读章优先」机制；该机制需要额外维护阅读触发时间、缓存预取识别、优先级队列和抢占规则，后续确认有必要再加。

### 8.3 失败降级

当 AI 调用最终失败或偏差值持续不达标时：

1. 返回主源原始内容。
2. 若主源内容不完整，返回最高评分第三方源内容。
3. 在正文结尾追加：

```markdown

---

【聚合处理提示】当前章节 AI 处理失败，来源：{source_id}。已返回原始内容，可稍后重试。
```

### 8.3.1 失败分类与重试退避

失败不能只记录字符串，需要可统计、可重试、可展示的错误码。

错误码：

| 错误码 | 场景 | 默认处理 |
|--------|------|----------|
| `SOURCE_EMPTY_CONTENT` | 书源返回空正文 | 换候选源；无候选源则 `error`。 |
| `SOURCE_TIMEOUT` | 拉取正文超时 | 延迟重试。 |
| `SOURCE_AUTH_REQUIRED` | 官方源需要登录/购买 | 尝试候选源补充；保留提示。 |
| `ALIGNMENT_LOW_CONFIDENCE` | 候选源章节对齐失败 | 不跨源补充，返回主源内容或错误。 |
| `AI_RATE_LIMITED` | AI endpoint 限流 | 延迟重试。 |
| `AI_TIMEOUT` | AI 请求超时 | 延迟重试。 |
| `AI_BAD_REQUEST` | 请求体或模型参数错误 | 不自动重试，要求用户检查设置。 |
| `AI_OUTPUT_DEVIATION` | 偏差值过低 | 调整 prompt 后重试，超过次数回退。 |
| `FILE_WRITE_FAILED` | Markdown 写入失败 | 保留数据库结果，提示文件写入失败。 |

已确认退避规则：

- 单章自动重试最多 5 次。
- 重试等待时间依次叠加：第 1 次 5 分钟、第 2 次 15 分钟、第 3 次 30 分钟、第 4 次 60 分钟、第 5 次 120 分钟。
- `AI_BAD_REQUEST` 这类明显配置错误可以直接进入失败，避免重复消耗请求。
- 5 次重试后仍失败时，章节不返回空内容，进入 `fallback`。
- `fallback` 内容优先使用官方源可用正文；官方源不可用或不完整时，使用已经通过章节对齐校验的候选源正文。
- 进入 `fallback` 后，在章节末尾追加聚合处理提示，说明 AI 处理失败以及最终采用的正文来源。
- 第一次 AI 处理失败且已经存在可用正文源时，就应立即用 `fallback` 正文替换本地占位文件，让用户先读到可用内容。
- 后续重试仍继续进行；如果后续 AI 处理成功，再用最终 AI 整理正文覆盖之前的 `fallback` 文件。
- `fallback` 是可读降级态，不是最终失败态；只有重试次数耗尽且仍无可用正文时，才进入不可读 `error`。
- 单本书连续失败章节过多时，书籍状态标记为 `error`，但不影响其他书继续排队。

### 8.4 分段策略

- 计算 prompt token（系统 prompt + 前文 + 当前正文）。
- 若总 token ≤ `modelContextLength * maxContextUseRatio`，整章一次性发送。
- 若超过：
  - 优先按段落切分，每段保留完整语义。
  - 每段仍携带标题与最小前文提示。
  - 结果按顺序拼接。
- 若单段仍超限，按句子切分（尽量避免）。
- 除非正文过长、超过模型上下文限制，或多源正文分段差异过大，不要主动重分段。
- 官方完整正文路径下，默认保留官方原始分段，只做空行压缩、明显广告清理和轻微格式整理。
- 多源补全文路径下，优先选择最可靠正文源的分段作为基准；只有多个来源分段冲突严重时，才让 AI 做保守分段整理。
- 分段结果不作为评论锚点的唯一依据，评论锚点以官方/评论来源段落为准，通过模糊匹配关联到聚合正文。

### 8.5 前文校准

处理第 N 章时，从 `aggregate_chapter_tasks` 读取本书前 `includePreviousChapters` 章的已处理内容，截取末尾约 500~1000 字作为 `context`，帮助 AI 保持人名、地名、文风一致。

### 8.6 目录变更与断更恢复

聚合任务需要能长期跟随连载书更新，因此目录刷新不能简单覆盖历史状态。

已确认规则：

1. 章节目录永远以主源为准。官方源存在时以官方源为主源；官方源不存在时，以评选出来的第三方主源为准。
2. 每次刷新目录时，将当前主源目录视为权威目录，对聚合章节表和本地 Markdown 文件做同步。
3. 主源新增章节时，新增对应 `aggregate_chapter_tasks`，状态为 `pending`。
4. 主源章节标题变更时，更新数据库标题；如该章节已写入本地 Markdown，需要按新标题重新生成文件路径。
5. 主源章节索引变更时，更新 `chapter_index`，并按新索引重新生成文件路径。
6. 主源章节仍存在但 `source_chapter_id` 变化时，标记该聚合章节为 `pending`，按新主源章节重新处理。
7. 主源章节不存在时，对应聚合章节和本地 Markdown 不继续保留旧结果；实现时可以直接删除对应文件和任务，也可以标记为 `pending` 后按新目录重新映射处理。
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
| `status` | string | `all` | `all` / `pending` / `fetching` / `ai_processing` / `processed` / `fallback` / `error` / `skipped`。 |
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

| 状态 | 前端展示 | 是否可重试 |
|------|----------|------------|
| `pending` | 等待处理 | 否 |
| `fetching` | 正在获取正文 | 否 |
| `ai_processing` | 正在 AI 处理 | 否 |
| `processed` | 已完成 | 是，作为重新处理 |
| `fallback` | 已回退原文 | 是 |
| `error` | 处理失败 | 是 |
| `skipped` | 已跳过 | 是 |

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

```
backend/data/novels/
└── legadohub_ai_aggregate/
    └── 《{书名}》/
        ├── 000001 第一章 风起.md
        ├── 000002 第二章 云涌.md
        └── ...
```

### 15.2 文件格式

```markdown
# 第一章 风起

正文第一段。

正文第二段。
```

### 15.3 元数据

数据库保留完整元数据；文件本身保持简洁，仅标题 + 正文，便于用户直接阅读。

### 15.4 文件命名与清理策略

本地 Markdown 是用户可直接阅读和长期保存的成果，因此文件路径要稳定。

已确认规则：

- 文件名格式固定为 `{chapter_index:06d} {safe_title}.md`。
- `safe_title` 需要移除 Windows 非法字符：`< > : " / \ | ? *`，并压缩连续空白。
- 文件名过长时截断标题部分，保证完整路径不超过 Windows 常见限制。
- 文件路径由主源目录驱动；主源章节标题或索引变化时，按新目录重命名或重写文件。
- 主源章节删除时，本地对应 Markdown 文件也删除。
- 删除聚合任务时，默认同步删除本地 Markdown 文件，因为这些文件是聚合任务产物。
- 第一版只保存最终 Markdown，不保存原始正文、AI 处理正文、失败回退正文的多版本文件。
- 如需调试原始正文或候选源正文，只在数据库调试字段或日志中短期保存，不写入用户可读目录。
- 数据库需要保存当前文件路径，便于后续标题/索引变化和任务删除时清理旧文件。

---

## 16. 实施路线

### Phase 1：AI Provider 与设置基础

1. 创建 `backend/app/ai/` 模块：
   - `models_catalog.py`：内置模型元数据（参考 pi 的 `models.generated.ts`）。
   - `compat.py`：根据 `provider` / `baseUrl` / `model` 自动推断 `compat`，支持 `compatOverrides` 覆盖。
   - `request_builder.py`：根据 `compat` 与 `thinkingLevel` 构造 OpenAI 兼容请求体。
   - `client.py`：`httpx` 异步客户端、流式响应解析、错误处理。
   - `encryption.py`：API Key Fernet 加密与脱敏。
2. 实现 OpenAI 兼容 Provider、模型列表获取、连通性测试。
3. 新增 `aggregate_settings` 表与读写封装。
4. 新增 `/api/console/aggregate-settings` API（含 `test-provider`、`fetch-models`）。
5. 前端新增 `/console/aggregate-settings` 分页，模型选择自动填充上下文长度，思考强度使用下拉选项框。

### Phase 2：主源选择与任务队列

1. 实现 `AggregatePrimarySelector`。
2. 扩展 `aggregate_book_tasks` 字段。
3. 修改 `AggregateProcessor.enqueue_book` 支持主源自动选择。
4. 实现「主动选择聚合源才加入书架」的判断。
5. 补充单元测试。

### Phase 3：AI 单章处理与偏差校验

1. 实现 `AggregateAIService`。
2. 引入 `konsheng/Sensitive-lexicon` 本地词库，构建敏感词候选扫描器。
3. 实现 Prompt 渲染、前文校准、敏感词候选注入、分段策略。
4. 实现偏差值计算（代码 + AI 综合）。
5. 修改 `_process_chapter` 接入 AI，实现失败降级。
6. 扩展 `aggregate_chapter_tasks` 与 `aggregate_ai_usage`。

### Phase 4：占位文件与本地存储

1. 未处理章节读取时生成占位 `.md`。
2. AI 处理完成后写入正式 `.md`。
3. 验证本地文件可直接阅读。

### Phase 5：聚合书架页面

1. 新增 `/console/aggregate-books` 列表页。
2. 新增 `/console/aggregate-books/:bookId` 详情页。
3. 实现章节预览、本章说、统计、重试。

### Phase 6：搜索界面改造

1. 后端搜索返回中保留聚合源标记。
2. 前端搜索界面聚合源按钮改为「加入处理」。

### Phase 7：验收与文档

1. 跑通完整测试套件。
2. 更新 README 与插件契约文档中的 AI 聚合说明。

### 16.1 测试验收矩阵

| 模块 | 测试内容 | 建议测试文件 |
|------|----------|--------------|
| 数据迁移 | 旧库启动后自动补齐 `aggregate_*` 新字段，旧任务仍可读取。 | `backend/tests/test_db.py` |
| 设置迁移 | `admin_settings.contentWorkflow` 能迁移到 `aggregate_settings.contentWorkflow`，后续读取只走新表。 | `backend/tests/test_aggregate_settings.py` |
| 队列并发 | 同一本书重复触发只返回同一进度，不创建重复任务；多本书按顺序处理。 | `backend/tests/test_aggregate_processor.py` |
| 已完成跳过 | `completed + processed` 的书不会被后台重复处理。 | `backend/tests/test_aggregate_processor.py` |
| 章节对齐 | 索引一致标题相似时可补充；标题差异大时拒绝跨源补充。 | `backend/tests/test_aggregate_alignment.py` |
| 处理窗口 | 首次加入、阅读触发、后台轮询都只处理限定窗口。 | `backend/tests/test_aggregate_processor.py` |
| 目录变更 | 新增章节被追加，已处理章节不因标题变更重跑。 | `backend/tests/test_aggregate_processor.py` |
| 敏感词词库 | 词库可加载，屏蔽符上下文能生成候选，候选不会被机械替换。 | `backend/tests/test_sensitive_lexicon.py` |
| AI 请求构造 | 不同 `compat` 与 `thinkingLevel` 生成正确请求体。 | `backend/tests/test_ai_request_builder.py` |
| 偏差校验 | 高相似文本通过，低相似文本触发重试或回退。 | `backend/tests/test_aggregate_deviation.py` |
| 失败退避 | timeout、rate limit、bad request 对应不同 retry 策略。 | `backend/tests/test_aggregate_retry.py` |
| 文件落盘 | 文件名清洗、重复写入、删除任务时同步清理本地 Markdown。 | `backend/tests/test_novel_file_cache.py` |
| 控制台 API | 列表分页、章节分页、详情响应、设置脱敏。 | `backend/tests/test_plugin_console_api.py` |
| 评论映射 | 聚合章节评论能映射回主源章节，并保留章评与热评结构。 | `backend/tests/test_aggregate_reviews.py` |
| 热评匹配 | 起点热评能从摘要接口提取，并通过模糊匹配关联到聚合正文片段。 | `backend/tests/test_aggregate_reviews.py` |
| 前端构建 | 聚合书架、设置页、搜索按钮改造后能通过构建。 | `frontend` 的 `npm run build` |

---

## 17. 风险与待确认

| 风险 | 影响 | 应对 |
|------|------|------|
| AI 输出过度改写 | 正文失真 | 偏差值校验 + 低 temperature + 重试机制 |
| 官方源 VIP 章节只有预览 | 聚合结果短 | 自动拉取第三方源补充，prompt 明确要求补充 |
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
