# 搜索缓存重构方案（按书籍实体建模）

> 状态：已废弃（不要继续执行）  
> 日期：2026-06-20  
> 范围：`legado-hub` 搜索缓存、搜索任务、阅读端搜索返回模型  
> 结论：该方案已被“双接口搜索 + AI 聚合显式模式 + 真实搜索优先/站点级缓存回退”方案替代

> 注意：本文件仅保留为历史讨论记录。  
> 后续实现请改为遵循 `search-dual-path-and-aggregate-mode-plan.zh-CN.md`。

---

## 1. 背景与问题定义

当前搜索链路的核心问题不是“缓存命中条件不够好”，而是**缓存真相源建模错误**。

现状大致是：

1. 搜索快照以 `normalized_keyword + page + source_scope` 为主键落在 `search_query_cache`
2. 阅读端和后台搜索端围绕“查询词快照”工作
3. 模糊缓存命中虽然已经尝试转向书名，但底层仍是在查询快照里二次筛
4. 命中缓存后，系统天然倾向于把“历史搜索词”当成事实，而不是把“已经拿到过的书籍结果”当成事实

这会导致几个持续性问题：

1. **缓存是按搜索字段组织的，不是按书籍组织的**
2. **同一本书换个搜索词就容易错过缓存**
3. **阅读端容易因为命中缓存而提前结束真实搜索**
4. **后台搜索和阅读端的行为模型不统一**
5. **搜索记录、搜索快照、实时会话混在一起，职责不清**

本轮重构不再修补查询级缓存，而是将搜索系统直接改造成：

- **书籍缓存持久化**
- **搜索会话内存化**
- **缓存先回、实时补充**
- **阅读端通过轮询 job 获取增量结果**

---

## 2. 本轮直接结论

### 2.1 直接重构，不做兼容

本轮按“直接收口”执行：

1. 不保留旧 `search_query_cache` 主路径兼容
2. 不保留旧“命中缓存即结束搜索”的行为
3. 不保留旧“搜索词快照是缓存真相源”的设计
4. 如有必要，直接重建数据库

### 2.2 数据库需要重建

这轮重构会改变搜索缓存和搜索任务的核心表职责，因此建议：

1. 停止后端服务
2. 删除旧数据库
3. 用新 schema 重新初始化

不做平滑迁移，不保留旧搜索缓存真相源。

---

## 3. 新的总体原则

### 3.1 缓存真相源应是书籍，不是搜索词

缓存的基本单位应该是：

- 一本书在某个书源上的搜索命中结果

而不是：

- 某个关键词在某次搜索里的返回快照

### 3.2 搜索词只是召回条件

搜索词只负责触发两类召回：

1. **按书名召回**
2. **按作者召回**

搜索词本身不再作为长期缓存主键。

### 3.3 搜索会话不是长期事实

一次搜索产生的：

- 进度
- 事件
- 当前运行状态
- 中间结果

都属于运行态数据，应放在内存中，进程重启即可清空。

### 3.4 阅读端与后台搜索端使用同一搜索模型

后台搜索页和阅读端不再走两套缓存哲学。

统一模型：

1. 先返回缓存
2. 再继续真实搜索
3. 通过 job 轮询补充实时结果

---

## 4. 新搜索模型

### 4.1 书籍缓存（持久化，TTL 7 天）

新增主缓存表：

```text
book_search_cache
```

它是搜索缓存的唯一长期真相源。

缓存保留策略：

- 默认保留 7 天
- 超过 7 天的记录视为过期
- 清理策略可以在启动时、定时任务或写入时顺手清理

### 4.2 搜索会话（内存）

新增运行时搜索会话存储：

```text
SearchSessionStore
```

职责：

1. 保存搜索 job
2. 保存实时进度
3. 保存缓存结果快照
4. 保存实时结果快照
5. 供前端和阅读端轮询

特征：

- 不落主数据库
- 进程重启即清空
- 仅服务运行期有效

### 4.3 搜索模式

搜索分两类：

1. `title`
   - 按书名匹配
   - 不关心作者

2. `author`
   - 按作者匹配
   - 不关心书名

不再默认把书名和作者混在同一模糊策略里。

### 4.4 返回来源标识

每条结果都必须带来源信息：

```json
{
  "resultSource": "cache",
  "cacheHit": true
}
```

或：

```json
{
  "resultSource": "live",
  "cacheHit": false
}
```

---

## 5. 数据库重建方案

### 5.1 删除旧搜索缓存主路径

以下旧表或旧职责不再作为搜索主路径：

1. `search_query_cache`
2. `search_results` 作为查询快照事实源的职责
3. `search_jobs` 作为长期搜索会话存储的职责

注意：

- 若 `search_results` 中有对其他功能仍有价值的字段，可以选择保留表但重定义用途
- 但它不应再成为阅读端“模糊缓存搜索”的主入口

### 5.2 新表：`book_search_cache`

建议字段：

```sql
CREATE TABLE IF NOT EXISTS book_search_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_mode TEXT NOT NULL,               -- title / author
    normalized_name TEXT NOT NULL DEFAULT '',
    normalized_author TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL,
    source_name TEXT DEFAULT '',
    raw_book_url TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    score INTEGER DEFAULT 0,
    first_seen_at TEXT DEFAULT (datetime('now')),
    last_seen_at TEXT DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL
);
```

建议索引：

```sql
CREATE INDEX IF NOT EXISTS idx_book_search_cache_title
    ON book_search_cache (match_mode, normalized_name, last_seen_at);

CREATE INDEX IF NOT EXISTS idx_book_search_cache_author
    ON book_search_cache (match_mode, normalized_author, last_seen_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_book_search_cache_unique_source_book
    ON book_search_cache (source_id, raw_book_url, match_mode);
```

### 5.3 搜索 job 不再长期落库

如果仍需要“最近任务列表”，建议只保留非常轻量的摘要表，或者直接取消数据库持久化。

本轮推荐：

- **搜索运行态只放内存**
- 如后台页面确实需要最近任务列表，可后续单独补一张只存摘要的轻量表

但这不是首轮核心需求。

### 5.4 数据库处理方式

执行方式：

1. 修改 `backend/app/storage/db.py`
2. 删除旧搜索快照主路径相关表定义
3. 新增 `book_search_cache`
4. 删除旧数据库文件
5. 启动后自动初始化新 schema

---

## 6. 新搜索执行流程

### 6.1 后台搜索页

流程：

1. 用户发起搜索
2. 根据 `matchMode` 在 `book_search_cache` 中做模糊召回
3. 立即返回：
   - 缓存命中结果
   - `jobId`
   - `status=running`
4. 后台真实搜索启动
5. 实时搜索命中结果后：
   - 更新内存 job
   - 写回 `book_search_cache`
6. 前端轮询 `/search-jobs/{jobId}` 获取新结果
7. 到达超时或全部完成后，状态变为终态

### 6.2 阅读端

阅读端遵循与后台一致的模型，但参数更保守：

1. 首次请求优先返回缓存
2. 同时启动真实搜索
3. 返回：
   - `items`
   - `jobId`
   - `status=running`
   - `liveSearchPending=true`
4. 阅读端继续轮询 job
5. 直到：
   - 搜索完成
   - 搜索失败
   - 超时结束

### 6.3 超时策略

阅读端默认超时：

- **120 秒**

在浏览器源较多、官方源较慢时，可允许提升至：

- **180 秒**

注意：

- 命中缓存后不能因为已经有结果就提前结束实时搜索
- 缓存只是首屏优化，不是搜索完成信号

---

## 7. 缓存检索规则

### 7.1 书名模式

`matchMode = title`

规则：

1. 只按 `normalized_name` 做模糊包含匹配
2. 不以作者为过滤条件
3. 返回所有书名命中的候选

适用场景：

- 阅读端按书名找书
- 后台常规搜索

### 7.2 作者模式

`matchMode = author`

规则：

1. 只按 `normalized_author` 做模糊包含匹配
2. 不以书名为过滤条件
3. 返回该作者相关候选书

适用场景：

- 按作者排查书源
- 后台调试搜索

### 7.3 去重规则

推荐按以下优先级去重：

1. `source_id + raw_book_url`
2. 若地址缺失，再退化为 `name + author + source_id`

不要只按书名去重，否则同名不同书会被错误覆盖。

---

## 8. 内存搜索会话模型

建议结构：

```python
SearchSession(
    job_id: str,
    keyword: str,
    match_mode: str,
    page: int,
    status: str,
    created_at: float,
    deadline_at: float,
    cached_items: list[dict],
    live_items: list[dict],
    merged_items: list[dict],
    candidate_groups: list[dict],
    events: list[dict],
    completed_sources: int,
    success_count: int,
    error_count: int,
    timeout_count: int,
)
```

说明：

1. `cached_items` 表示首轮缓存召回结果
2. `live_items` 表示实时搜索命中结果
3. `merged_items` 是对外返回结果
4. `events` 只在运行时有效

---

## 9. API 行为重定义

### 9.1 阅读端搜索

`GET /api/legado/search`

首次返回：

```json
{
  "implemented": true,
  "keyword": "凡人修仙传",
  "page": 1,
  "jobId": "search_xxx",
  "status": "running",
  "liveSearchPending": true,
  "items": [
    {
      "name": "凡人修仙传",
      "author": "忘语",
      "resultSource": "cache",
      "cacheHit": true
    }
  ],
  "debug": {
    "cacheReturned": true,
    "liveSearchStarted": true,
    "timeoutSeconds": 120
  }
}
```

### 9.2 后台搜索创建

`POST /api/console/search-jobs`

返回：

```json
{
  "jobId": "search_xxx",
  "status": "running",
  "liveSearchPending": true,
  "cachedSnapshot": {
    "items": [...]
  }
}
```

### 9.3 Job 查询

`GET /api/console/search-jobs/{jobId}`

返回：

```json
{
  "jobId": "search_xxx",
  "status": "running|completed|timed_out|failed|cancelled",
  "items": [...],
  "candidateGroups": [...],
  "debug": {
    "cacheReturned": true,
    "liveSearchCompleted": false,
    "timeoutSeconds": 120
  }
}
```

---

## 10. 前端行为要求

### 10.1 后台搜索页

要求：

1. 允许选择 `matchMode`：
   - `title`
   - `author`
2. 若存在 `cachedSnapshot`，先渲染缓存结果
3. 自动轮询 `job`
4. 实时结果回来后刷新列表
5. 结果中显示：
   - `cache`
   - `live`

### 10.2 阅读端

要求：

1. 收到 `jobId + running` 后继续轮询
2. 缓存结果先显示
3. 实时结果回来后补充或覆盖缓存结果
4. 轮询终止条件：
   - `completed`
   - `timed_out`
   - `failed`
   - `cancelled`

---

## 11. 实施步骤

### 阶段 1：文档与接口定稿

1. 锁定本方案
2. 明确 `matchMode`
3. 明确阅读端轮询模型

### 阶段 2：数据库重建

1. 修改 `db.py`
2. 删除旧数据库
3. 初始化新 schema

### 阶段 3：重写缓存服务

1. 新建 `book_search_cache` 读写接口
2. 实现 7 天 TTL
3. 实现按书名 / 作者模糊检索

### 阶段 4：重写搜索会话

1. 用内存 `SearchSessionStore` 取代旧持久化 job 主路径
2. 实现缓存先回、实时补充
3. 实现结果来源标记

### 阶段 5：改 API

1. 改 `/api/legado/search`
2. 改 `/api/console/search-jobs`
3. 改 `/api/console/search-jobs/{jobId}`

### 阶段 6：改前端

1. 搜索页支持新状态与来源标记
2. 轮询逻辑适配

### 阶段 7：验证

---

## 12. 验证清单

### 功能验证

1. 同一本书，用不同关键词但书名一致时，能命中同一缓存
2. 按作者搜索时，只按作者召回
3. 阅读端首包返回缓存 + `running`
4. 轮询后能拿到 `live` 补充结果
5. 超时后状态正确变为 `timed_out`

### 数据验证

1. `book_search_cache` 正常写入
2. `expires_at` 正确为 7 天后
3. 重启进程后 job 消失，但书籍缓存仍在

### 非兼容确认

1. 旧 `search_query_cache` 不再走主路径
2. 旧查询词快照行为不再保留
3. 旧数据库可直接删除重建

---

## 13. 最终收口

这次重构的最终结论只有四句：

1. **缓存按书籍实体建，不按搜索词建。**
2. **搜索记录和实时会话不再长期落库，改为内存。**
3. **阅读端和后台统一走“缓存先回 + 实时补充 + 轮询 job”。**
4. **数据库直接重建，不做兼容。**
