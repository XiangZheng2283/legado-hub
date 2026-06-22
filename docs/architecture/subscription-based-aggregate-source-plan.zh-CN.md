# 聚合书源订阅模式设计文档

> 状态：待实施  
> 日期：2026-06-20  
> 范围：legado-hub 聚合书源、用户订阅、搜索注入、章节处理  
> 决策：废弃当前搜索时聚合接口，全面转向订阅模式

---

## 1. 背景与决策

### 1.1 当前方案

当前聚合书源通过 `POST /api/console/search/aggregate` 接口在搜索时即时生成聚合壳，用户点击后才开始处理章节。

### 1.2 问题

1. 搜索时聚合结果不稳定，依赖单次搜索的源质量
2. 用户首次打开章节看到 `PROCESSING_PLACEHOLDER`
3. 后台处理与搜索流程耦合
4. 管理后台搜索页不适合普通用户直接使用

### 1.3 新方案决策

全面转向**订阅模式**：

- 提供独立的用户搜索/订阅页面
- 用户订阅小说后，后台持续处理章节
- 普通搜索自动注入已订阅小说的聚合源
- 任意用户订阅一本小说后，所有用户搜索都能看到该聚合源
- 废弃 `POST /api/console/search/aggregate`

---

## 2. 总体架构

```
用户前端（新增）
├── /subscribe/search        用户搜索页
├── /subscribe/library       我的订阅
└── BookDetailModal          书籍详情弹窗（含订阅按钮）

管理后台（现有，不变）
├── /console/search-jobs     普通搜索（自动注入聚合源）
└── /console/settings        管理设置

后端
├── /api/subscribe/search                    用户搜索
├── /api/subscribe/books/{name}              书籍详情
├── /api/subscribe/books/{name}              订阅/取消订阅
├── /api/subscribe/library                   我的订阅列表
├── /api/subscribe/books/{name}/settings     订阅设置
├── /api/console/search-jobs                 普通搜索（注入聚合源）
└── 后台调度器：检查订阅小说更新

数据库
├── novel_subscriptions      小说订阅全局表
└── user_subscriptions       用户-小说关联表

本地存储
backend/data/novels/
└── {normalized_novel_name}/
    ├── novel.json           # 元数据 + 处理进度
    └── chapters/
        ├── 第001章_xxx.md
        └── ...
```

---

## 3. 核心规则

1. **用户搜索页**与**管理后台搜索页**完全分离
2. **任意用户订阅一本小说后**，所有用户在普通搜索中都能看到该小说的 `legadohub_ai_aggregate` 源
3. **小说存储按小说名称**，不区分用户
4. **处理一章写入一章**，不再创建空文件或 pending/processed 文件夹
5. **废弃 `POST /api/console/search/aggregate`**，前端"书源聚合"模式移除
6. **普通搜索自动注入聚合源**（仅对已订阅小说）

---

## 4. 数据模型

### 4.1 `novel_subscriptions`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | |
| `novel_name` | TEXT UNIQUE | 标准化小说名，去重键 |
| `display_name` | TEXT | 原始小说名 |
| `author` | TEXT | 作者 |
| `cover_url` | TEXT | 封面 URL |
| `word_count` | TEXT | 总字数 |
| `total_chapters` | INTEGER | 总章节数 |
| `processed_chapters` | INTEGER | 已处理章节数 |
| `completed` | BOOLEAN | 是否完结 |
| `primary_source_id` | TEXT | 主源 ID |
| `candidate_sources` | TEXT(JSON) | 候选源列表 |
| `settings_json` | TEXT(JSON) | 订阅设置 |
| `last_checked_at` | TEXT | 上次检查更新时间 |
| `last_chapter_title` | TEXT | 最新章节标题 |
| `created_at` | TEXT | |
| `updated_at` | TEXT | |

### 4.2 `user_subscriptions`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | |
| `user_id` | TEXT | 用户 ID |
| `novel_name` | TEXT | 关联 novel_subscriptions |
| `settings_override` | TEXT(JSON) | 用户个性化设置（可选） |
| `created_at` | TEXT | |

### 4.3 `aggregate_chapter_tasks` 新增字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `priority` | INTEGER | 处理优先级 |
| `processing_started_at` | TEXT | 处理开始时间 |
| `novel_name` | TEXT | 归属小说 |

---

## 5. 本地存储结构

```
backend/data/novels/
└── {normalized_novel_name}/
    ├── novel.json
    └── chapters/
        ├── 第001章_开局.md
        ├── 第002章_入门.md
        └── ...
```

### 5.1 `novel.json` 示例

```json
{
  "novelName": "剑宗外门",
  "author": "其声喵喵然",
  "primarySourceId": "qidian_com_web",
  "candidateSources": ["69shuba_tw", "twkan_com", "kks101_com"],
  "totalChapters": 389,
  "processedChapters": 12,
  "completed": false,
  "lastChapter": "第389章 拔剑而已",
  "lastCheckedAt": "2026-06-20T10:00:00Z",
  "settings": {
    "aiEnabled": true,
    "updateIntervalMinutes": 60,
    "sourcePriority": ["auto"]
  }
}
```

---

## 6. 接口设计

### 6.1 用户搜索

```http
POST /api/subscribe/search
Content-Type: application/json

{
  "keyword": "剑宗外门",
  "page": 1
}
```

返回普通源结果列表（不含聚合源）。每个结果可点击进入书籍详情弹窗。

### 6.2 书籍详情

```http
GET /api/subscribe/books/{novel_name}
```

返回：

```json
{
  "novelName": "剑宗外门",
  "author": "其声喵喵然",
  "coverUrl": "https://...",
  "wordCount": "100万",
  "totalChapters": 389,
  "completed": false,
  "lastChapter": "第389章 拔剑而已",
  "isSubscribed": false,
  "availableSources": [
    {"sourceId": "qidian_com_web", "sourceName": "起点中文网"},
    {"sourceId": "69shuba_tw", "sourceName": "69书吧"}
  ],
  "defaultSettings": {
    "aiEnabled": true,
    "updateIntervalMinutes": 60,
    "sourcePriority": ["auto"]
  }
}
```

### 6.3 订阅小说

```http
POST /api/subscribe/books/{novel_name}
Content-Type: application/json

{
  "aiEnabled": true,
  "updateIntervalMinutes": 60,
  "sourcePriority": ["auto"]
}
```

行为：
1. 创建/更新 `novel_subscriptions`
2. 创建 `user_subscriptions`
3. 触发首次处理：搜索源 → 建聚合壳 → 取 TOC → 开始处理

### 6.4 取消订阅

```http
DELETE /api/subscribe/books/{novel_name}
```

仅删除 `user_subscriptions`。如果还有其他用户订阅，`novel_subscriptions` 保留。

### 6.5 我的订阅

```http
GET /api/subscribe/library
```

返回当前用户订阅列表。

### 6.6 普通搜索注入聚合源

```http
POST /api/console/search-jobs
Content-Type: application/json

{
  "keyword": "剑宗外门",
  "page": 1
}
```

后端行为：
1. 搜索第三方/官方源
2. 检查 `novel_subscriptions` 是否有匹配 `novel_name`
3. 如果有 → 在结果中注入 `legadohub_ai_aggregate` 源
4. 聚合源显示处理进度

---

## 7. 处理流程

### 7.1 订阅时首次处理

```
用户点击订阅
    ↓
从所有可用源搜索该书
    ↓
选择主源（官方优先，第三方按分数兜底）
    ↓
创建 novel 目录 + novel.json
    ↓
取主源 TOC
    ↓
把全部章节写入 chapters/ 目录（一章一个文件）
    ↓
按优先级加入全局处理队列
    ↓
Worker 处理 → 写入 chapters/xxx.md → 更新 novel.json
```

### 7.2 后台更新检查

```
定时扫描 novel_subscriptions
    ↓
检查主源是否有新章节
    ↓
有更新 → 更新 total_chapters → 处理新章节
    ↓
无更新 → 只更新 last_checked_at
```

### 7.3 用户点击章节

```python
def aggregate_chapter_response(chapter_url):
    chapter_id = decode(chapter_url)
    file_path = get_chapter_file(chapter_id)
    if file_path.exists() and file_path.stat().st_size > 0:
        return file_path.read_text()
    
    # 未处理：触发高优先级处理 + 返回提示语
    trigger_priority_processing(chapter_id)
    return "章节处理中，请稍后刷新..."
```

---

## 8. 并行处理设计

### 8.1 Worker 配置

```python
max_workers = 4          # 全局章节处理并发
max_per_book = 2         # 单本书并发上限
max_ai_concurrency = 2   # AI 调用并发上限
```

### 8.2 队列优先级

| 优先级 | 场景 |
|--------|------|
| 1 | 用户当前点击的章节 |
| 2 | 用户点击章节的后 3 章 |
| 3 | 订阅新小说的前 10 章 |
| 4 | 后台更新章节 |
| 5 | 空闲时预读后续章节 |

### 8.3 用户跳转到后面章节

如果用户点击第 N 章：
- 第 N 章立即入队（优先级 1）
- 第 N+1, N+2, N+3 章入队（优先级 2）
- 第 1 至 N-1 章暂停或低优先级处理
- 仅在该小说之前没有本地数据时生效

---

## 9. AI 处理路径

| 主源 | 内容分类 | 处理方式 |
|------|---------|---------|
| 官方 | full | `_purify_content` + AI 净化 + 屏蔽词修复 |
| 官方 | preview | AI 聚合：官方 preview 为框架 + 第三方候选源补全 |
| 官方 | empty | 按分数降序找第三方候选源 full 内容 → AI 净化 |
| 第三方 | full | `_purify_content` + AI 净化 |
| 第三方 | preview/empty | 按分数降序找候选源 full → 规则/AI 净化 |

候选源查找：**串行按分数降序尝试**，命中即停。章节标题做模糊匹配（中文数字/阿拉伯数字归一化）。

---

## 10. 前端页面

### 10.1 用户搜索页 `/subscribe/search`

- 搜索框
- 结果列表（普通源书籍卡片）
- 点击卡片 → 书籍详情弹窗

### 10.2 书籍详情弹窗

显示：
- 封面
- 书名
- 作者
- 总字数
- 总章节数
- 完结状态
- 最新章节
- 可用源列表
- 订阅按钮

订阅配置：
- AI 聚合开关
- AI 净化开关
- 更新检查间隔
- 源优先级（默认自动）

### 10.3 我的订阅页 `/subscribe/library`

- 已订阅小说列表
- 处理进度条
- 最新章节
- 取消订阅

### 10.4 管理后台变更

- 移除"书源聚合"模式按钮
- 普通搜索结果中自动显示已订阅小说的聚合源

---

## 11. 实施顺序

### 阶段 1：基础数据层
1. 创建 `novel_subscriptions`、`user_subscriptions` 表
2. `aggregate_chapter_tasks` 新增字段
3. 创建小说目录结构工具

### 阶段 2：订阅后端 API
1. `POST /api/subscribe/search`
2. `GET /api/subscribe/books/{name}`
3. `POST /api/subscribe/books/{name}`
4. `GET /api/subscribe/library`
5. `DELETE /api/subscribe/books/{name}`

### 阶段 3：处理引擎
1. 全局章节队列 + Worker 池
2. 订阅时首次处理
3. 官方 preview AI 聚合
4. 候选源串行查找 + 模糊匹配

### 阶段 4：普通搜索注入
1. 修改 `search-jobs` 接口
2. 根据订阅表注入聚合源
3. 移除 `search/aggregate` 接口

### 阶段 5：前端用户页
1. `/subscribe/search`
2. `/subscribe/library`
3. 书籍详情弹窗

### 阶段 6：后台更新调度
1. 定时检查订阅小说更新
2. 新章节自动处理

### 阶段 7：验证
1. 端到端订阅流程
2. 搜索注入
3. 章节处理
4. 后台更新

---

## 12. 依赖与风险

### 12.1 依赖

- 用户系统：需要用户登录才能区分"我的订阅"
- 前端路由：新增 `/subscribe/*` 页面

### 12.2 风险

1. **存储膨胀**：每本订阅小说所有章节落盘，需要磁盘监控
2. **AI 成本**：官方 preview 强制 AI 聚合，调用量较大
3. **源站压力**：后台持续检查更新，需要限流
4. **多用户共享**：任意用户订阅所有人可见，可能被滥用

---

## 13. 与当前代码的关系

### 13.1 保留

- `aggregate_virtual_source.py`：聚合壳生成逻辑，改为订阅时调用
- `aggregate_processor.py`：章节处理核心，简化路径后保留
- `aggregate_ai_service.py`：AI 服务保留
- 搜索双路径/双超时/官方源开关：保留在普通搜索中

### 13.2 废弃

- `POST /api/console/search/aggregate` 接口
- 前端"书源聚合"模式
- 搜索后预处理 `_schedule_aggregate_preprocessing`

### 13.3 新增

- 订阅相关 API 和表
- 用户前端页面
- 小说目录管理工具
- 后台更新调度器
