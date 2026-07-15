# 订阅吞吐优化方案

> 状态：规划收口版
> 范围：`legado-hub` 订阅调度器、聚合处理器、数据库连接层
> 不包含：搜索链路、插件契约、前端控制台

---

## 1. 背景

当前订阅系统已可运行，但在"5-10 本新订阅（每本数千章积压）+ 10-20 本追更（每轮 1-3 章）"的真实场景下暴露严重吞吐瓶颈：

1. **书籍串行处理**：调度器每轮只处理一本书，积压书阻塞追更书 6+ 分钟。
2. **章节串行处理**：每本书内章节逐个处理，25 章 × 3 秒 = 75 秒/轮。
3. **积压追赶节奏慢**：积压时 recheck 间隔 1 分钟，大量时间浪费在等待中。
4. **数据库无 WAL**：SQLite 默认 `journal_mode=DELETE`，写锁全库互斥，无法并行写入。
5. **每章刷新书状态**：`_write_chapter_result` 每章都调 `_refresh_shared_book_state`（COUNT + UPDATE），写入放大严重。

**量化分析**（10 积压 × 5000 章 + 20 追更 × 2 章）：

- 当前：书籍串行 + 章节串行 + 1min recheck ≈ **75 小时**
- 优化后：书籍并行(3) + 章节并行(8) + 5s recheck ≈ **1.5 小时**
- 提升：**~50 倍**

---

## 2. 总体原则

### 2.1 保持 SQLite，不换数据库

SQLite + WAL 足以支撑本地单用户场景的并发写入。引入 PostgreSQL / DuckDB / Redis 会破坏 local-first 零依赖定位。

### 2.2 渐进式四阶段，每步可独立验证

按 A → B → C → D 顺序推进，每个阶段完成后用真实书籍测试，确认无回归再进入下一阶段。

### 2.3 不改变现有契约

- 不改插件契约（`Source` 类 async 方法）
- 不改数据库表结构（只改连接层 PRAGMA）
- 不改前端 API 契约
- 不改文件系统布局（`library/`、`cache/` 目录结构不变）

### 2.4 宿主管并发，插件管解析

并发控制（书籍级、章节级、源级、AI 级信号量）全部由宿主层调度器和处理器负责，插件不感知并发。

---

## 3. 当前瓶颈定位

### 3.1 数据库连接层

| 文件 | 行号 | 问题 |
|------|------|------|
| `db.py` | 554 | `sqlite3.connect(path)` 无 WAL、无 busy_timeout |
| `aggregate_processor.py` | 113-114 | `_conn()` 每次新建连接，无 WAL、无 busy_timeout |

**影响**：SQLite 默认 `journal_mode=DELETE`，写锁是全库级别的排他锁。并行写入会抛 `database is locked`。

### 3.2 调度器层（书籍串行）

| 文件 | 行号 | 问题 |
|------|------|------|
| `shared_book_scheduler.py` | 303 | `for book_id, ...: await self._process_book(...)` — 串行遍历 |
| `shared_book_scheduler.py` | 246 | `list_due_books(limit=effective_limit)` — 追更与积压混在同一队列 |
| `shared_book_scheduler.py` | 327 | `run_forever` 每 60s 轮询一次 |

**影响**：5 本积压书各 75 秒 = 375 秒，20 本追更书等待 6+ 分钟才被处理。

### 3.3 处理器层（章节串行）

| 文件 | 行号 | 问题 |
|------|------|------|
| `aggregate_processor.py` | 655 | `for chapter in chapters_to_process: await self._process_chapter(...)` — 串行遍历 |
| `aggregate_processor.py` | 2395 | `_write_chapter_result` 每章调 `_refresh_shared_book_state`（COUNT + UPDATE） |
| `aggregate_processor.py` | 661-666 | 积压 recheck 间隔 = `backlog_recheck_minutes()` = 1 分钟 |

**影响**：25 章 × 3 秒 = 75 秒/轮 + 60 秒等待 = 135 秒/轮；5000 章 ÷ 25/轮 = 200 轮 × 135 秒 = 7.5 小时/本。

### 3.4 配置参数

| 参数 | 当前值 | 来源 |
|------|--------|------|
| `WINDOW_CHAPTER_LIMIT` | 5 | `aggregate_settings.py:21` |
| `BACKLOG_CHAPTER_LIMIT` | 25 | `aggregate_settings.py:22` |
| `BACKLOG_RECHECK_MINUTES` | 1 | `aggregate_settings.py:23` |
| `aggregateCheckIntervalMinutes` | 30 | `aggregate_settings.py:81` |
| `aiMaxConcurrency` | 2 | `aggregate_settings.py:120` |
| `periodic_limit` | 5 | `shared_book_scheduler.py:233` |

---

## 4. Phase A：WAL + 章节并行

### 4.1 目标

消除章节串行瓶颈，单本书吞吐提升 5-8 倍。

### 4.2 改动

#### A1. 启用 WAL 模式

**文件**：`backend/app/storage/db.py`

在 `init_db()` 的 `sqlite3.connect(path)` 之后、建表之前，添加：

```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA busy_timeout=5000")
```

**文件**：`backend/app/services/aggregate_processor.py`

在 `_conn()` 方法（第 113-114 行）中，连接创建后添加：

```python
def _conn(self) -> sqlite3.Connection:
    conn = sqlite3.connect(self.db_path, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
```

**说明**：WAL 模式允许读写并发（多写单读 → 实际上 WAL 是多读单写，但写不再阻塞读，且写之间通过 busy_timeout 排队而非直接报错）。`busy_timeout=5000` 让写冲突时等待 5 秒而非立即抛 `database is locked`。

#### A2. 章节并行处理

**文件**：`backend/app/services/aggregate_processor.py`

**位置**：`run_book_task` 方法，第 655 行

**当前代码**：
```python
for chapter in chapters_to_process:
    chapter_results.append(await self._process_chapter(catalog, chapter))
```

**改为**：
```python
chapter_sem = asyncio.Semaphore(self._chapter_concurrency_limit())

async def _process_one(chapter):
    async with chapter_sem:
        return await self._process_chapter(catalog, chapter)

chapter_results = await asyncio.gather(
    *[_process_one(c) for c in chapters_to_process],
    return_exceptions=True
)
chapter_results = [
    r if not isinstance(r, Exception) else self._wrap_chapter_error(c, r)
    for c, r in zip(chapters_to_process, chapter_results)
]
```

**新增方法**：
```python
def _chapter_concurrency_limit(self) -> int:
    return aggregate_settings.CHAPTER_PARALLELISM_LIMIT  # 默认 8
```

**文件**：`backend/app/services/aggregate_settings.py`

新增常量：
```python
CHAPTER_PARALLELISM_LIMIT = 8
```

#### A3. per-source 信号量

**目的**：防止同一书源被并行请求过多触发反爬。

**文件**：`backend/app/services/aggregate_processor.py`

在 `AggregateProcessor` 类中新增 `_source_sems: dict[str, asyncio.Semaphore]`，在 `_process_chapter` 中按 `source_id` 获取信号量：

```python
async def _get_source_sem(self, source_id: str) -> asyncio.Semaphore:
    if source_id not in self._source_sems:
        self._source_sems[source_id] = asyncio.Semaphore(
            aggregate_settings.PER_SOURCE_CONCURRENCY  # 默认 2
        )
    return self._source_sems[source_id]
```

在 `_process_chapter` 中：
```python
source_sem = await self._get_source_sem(source_id)
async with source_sem:
    # 原有章节内容获取逻辑
```

**文件**：`backend/app/services/aggregate_settings.py`

新增常量：
```python
PER_SOURCE_CONCURRENCY = 2
```

#### A4. AI 信号量

**目的**：限制 AI provider 并发，防止超 rate limit。

**文件**：`backend/app/services/aggregate_processor.py`

在 `AggregateProcessor.__init__` 中新增：
```python
self._ai_sem = asyncio.Semaphore(aggregate_settings.aiMaxConcurrency)  # 默认 2
```

在 `_process_chapter` 中 AI 处理部分包裹 `async with self._ai_sem:`。

### 4.3 预期效果

- 单本书 25 章 × 3 秒 ÷ 8 并行 ≈ **10 秒/轮**（原 75 秒）
- 含 1min recheck = 70 秒/轮（原 135 秒）
- 5000 章 ÷ 25/轮 × 70 秒 = **2.3 小时/本**（原 7.5 小时）

### 4.4 验证

1. 启动服务，用真实书籍订阅测试
2. 观察日志确认章节并行执行（多个 `_process_chapter` 交错日志）
3. 确认无 `database is locked` 错误
4. 确认章节内容正确写入 `library/` 目录
5. 确认 `aggregate_chapter_tasks` 状态正确更新

---

## 5. Phase B：书籍并行

### 5.1 目标

消除书籍串行瓶颈，多本书同时处理，吞吐再提升 3-5 倍。

### 5.2 改动

#### B1. 调度器书籍并行

**文件**：`backend/app/services/shared_book_scheduler.py`

**位置**：`run_periodic_once` 方法，第 303 行

**当前代码**：
```python
for book_id, trigger, payload in scheduled:
    processed_items.append(await self._process_book(book_id, trigger, payload))
```

**改为**：
```python
book_sem = asyncio.Semaphore(self._book_concurrency_limit())

async def _process_one(book_id, trigger, payload):
    async with book_sem:
        return await self._process_book(book_id, trigger, payload)

processed_items = await asyncio.gather(
    *[_process_one(b, t, p) for b, t, p in scheduled],
    return_exceptions=True
)
```

**新增方法**：
```python
def _book_concurrency_limit(self) -> int:
    return aggregate_settings.BOOK_PARALLELISM_LIMIT  # 默认 3
```

**文件**：`backend/app/services/aggregate_settings.py`

新增常量：
```python
BOOK_PARALLELISM_LIMIT = 3
```

#### B2. lease 并行安全性

**已有保障**：`_process_book`（第 362 行）为每本书独立获取 `SharedBookLockService` 文件锁，不同书的锁文件路径不同，天然支持并行。

**需确认**：`SharedBookLockService` 内部 guard lock（`msvcrt.locking` / `fcntl.flock`）是全局的还是 per-book 的。如果是全局 guard lock，并行书籍的 acquire/release 会串行化但耗时极短（毫秒级），不影响吞吐。

### 5.3 预期效果

- 3 本书并行，每本 10 秒/轮 = 3 本 × 25 章 = 75 章每 10 秒
- 10 积压书 × 5000 章 ÷ 75 章每 10 秒 = **111 分钟**（Phase A 单本需 138 分钟 × 10 = 23 小时）
- 追更书（1-3 章）在 3 个并发槽中几乎零等待

### 5.4 验证

1. 同时订阅 3-5 本真实书籍
2. 观察日志确认多本书 `_process_book` 交错执行
3. 确认每本书的 lease 独立获取/释放
4. 确认无锁冲突或 lease 串扰
5. 确认追更书不被积压书阻塞

---

## 6. Phase C：双车道调度

### 6.1 目标

追更书（少量待处理）优先于积压书（大量待处理），确保追更响应延迟 < 30 秒。

### 6.2 改动

#### C1. 拆分 list_due_books

**文件**：`backend/app/services/aggregate_processor.py`

**位置**：`list_due_books` 方法，第 532-557 行

**当前**：单查询返回所有到期书籍。

**改为**：新增 `list_due_books_split` 方法，返回 `(fast_lane, slow_lane)`：

```python
def list_due_books_split(
    self,
    fast_limit: int,
    slow_limit: int,
) -> tuple[list[DueBook], list[DueBook]]:
    """返回 (快车道, 慢车道)。

    快车道：待处理章节数 <= WINDOW_CHAPTER_LIMIT 的书（追更）。
    慢车道：待处理章节数 > WINDOW_CHAPTER_LIMIT 的书（积压）。
    """
    conn = self._conn()
    try:
        base_where = (
            "WHERE status IN ('active','error') "
            "AND (next_check_time IS NULL OR next_check_time <= ?) "
        )
        base_order = "ORDER BY COALESCE(next_check_time, created_at)"

        fast_sql = (
            f"{base_where} "
            f"AND (total_chapters - processed_chapters) <= ? "
            f"{base_order} LIMIT ?"
        )
        slow_sql = (
            f"{base_where} "
            f"AND (total_chapters - processed_chapters) > ? "
            f"{base_order} LIMIT ?"
        )
        now = _now()
        fast = conn.execute(fast_sql, (now, WINDOW_CHAPTER_LIMIT, fast_limit)).fetchall()
        slow = conn.execute(slow_sql, (now, WINDOW_CHAPTER_LIMIT, slow_limit)).fetchall()
        return [self._row_to_due_book(r) for r in fast], [self._row_to_due_book(r) for r in slow]
    finally:
        conn.close()
```

#### C2. 调度器双车道处理

**文件**：`backend/app/services/shared_book_scheduler.py`

**位置**：`run_periodic_once` 方法，第 246 行附近

**改为**：
```python
fast_lane, slow_lane = processor.list_due_books_split(
    fast_limit=effective_limit,
    slow_limit=max(effective_limit - len(fast_lane), 1),
)

# 快车道优先处理
scheduled = self._merge_with_manual_queue(fast_lane, slow_lane)
```

**策略**：快车道先处理完，慢车道用剩余并发槽。如果快车道为空，慢车道占满全部槽位。

### 6.3 预期效果

- 20 本追更书每轮 < 5 秒处理完
- 积压书用剩余槽位，不影响追更响应
- 追更响应延迟从 6+ 分钟 → **< 30 秒**

### 6.4 验证

1. 同时有积压书和追更书到期
2. 确认追更书先被处理
3. 确认积压书在追更书处理完后开始
4. 确认追更书的 `next_check_time` 正常递推

---

## 7. Phase D：连续追赶 + 批量刷新

### 7.1 目标

积压时 recheck 间隔从 1min 降到 5s，消除等待浪费；去除每章状态刷新，减少 50% DB 写入。

### 7.2 改动

#### D1. 积压连续追赶

**文件**：`backend/app/services/aggregate_processor.py`

**位置**：`run_book_task` 方法，第 661-666 行

**当前**：
```python
if pending_after_run > 0 and len(chapter_results) >= chapter_limit:
    next_check = now + timedelta(minutes=self.backlog_recheck_minutes())
```

**改为**：
```python
if pending_after_run > 0 and len(chapter_results) >= chapter_limit:
    recheck_seconds = aggregate_settings.BACKLOG_RECHECK_SECONDS  # 默认 5
    next_check = now + timedelta(seconds=recheck_seconds)
```

**文件**：`backend/app/services/aggregate_settings.py`

新增常量：
```python
BACKLOG_RECHECK_SECONDS = 5
```

#### D2. 单次任务超时保护

**文件**：`backend/app/services/aggregate_processor.py`

**位置**：`run_book_task` 方法开头

**新增**：
```python
max_duration = aggregate_settings.MAX_BOOK_TASK_SECONDS  # 默认 600
deadline = time.monotonic() + max_duration
# ... 在章节并行循环后检查
if time.monotonic() > deadline:
    logger.warning("book task exceeded max duration, yielding", ...)
    break
```

**文件**：`backend/app/services/aggregate_settings.py`

新增常量：
```python
MAX_BOOK_TASK_SECONDS = 600  # 10 分钟
```

#### D3. 批量状态刷新

**文件**：`backend/app/services/aggregate_processor.py`

**位置**：`_write_chapter_result` 方法，第 2395 行

**当前**：每章处理完后调 `_refresh_shared_book_state`。

**改为**：删除 `_write_chapter_result` 中的 `_refresh_shared_book_state` 调用。

**位置**：`run_book_task` 方法，第 722 行

**已有**：`run_book_task` 在所有章节处理完后已调用 `_refresh_shared_book_state`。

**效果**：从"每章 1 次 COUNT + UPDATE"变为"每批 1 次"，25 章一批时 DB 写入减少 96%。

### 7.3 预期效果

- 积压追赶：5s recheck 替代 1min → 等待时间减少 92%
- DB 写入：每批 25 章从 25 次 COUNT+UPDATE → 1 次 → 写入减少 96%
- 5000 章总时间：200 轮 × (10 秒处理 + 5 秒等待) = **50 分钟/本**（Phase B 3 本并行 = 17 分钟/3 本）

### 7.4 验证

1. 积压书连续处理，观察 recheck 间隔是否为 5 秒
2. 确认任务超过 10 分钟时正常 yield
3. 确认 `_refresh_shared_book_state` 仅在批次结束时调用
4. 确认书状态（processed_chapters、search_visibility）正确更新
5. 确认无状态不一致或计数偏差

---

## 8. 配置参数汇总

### 8.1 新增参数（aggregate_settings.py）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `CHAPTER_PARALLELISM_LIMIT` | 8 | 单本书内章节并行度 |
| `BOOK_PARALLELISM_LIMIT` | 3 | 调度器同时处理的书籍数 |
| `PER_SOURCE_CONCURRENCY` | 2 | 同一书源的并行请求限制 |
| `BACKLOG_RECHECK_SECONDS` | 5 | 积压追赶 recheck 间隔（秒） |
| `MAX_BOOK_TASK_SECONDS` | 600 | 单次任务最长持续时间 |

### 8.2 现有参数（不变）

| 参数 | 值 | 说明 |
|------|-----|------|
| `WINDOW_CHAPTER_LIMIT` | 5 | 追更每轮章节数 |
| `BACKLOG_CHAPTER_LIMIT` | 25 | 积压每轮章节数 |
| `aiMaxConcurrency` | 2 | AI provider 并发 |
| `aggregateCheckIntervalMinutes` | 30 | 追更检查间隔 |
| `periodic_limit` | 5 | 每轮调度上限 |

### 8.3 可选：app_config.json 运行时调参

上述新增参数后续可选暴露到 `backend/config/app_config.json` 的 `aggregate` 节点，支持运行时热调。当前阶段先用代码常量，验证稳定后再暴露。

---

## 9. 测试方案

### 9.1 测试环境

- 本地开发机，已启动服务
- 真实书源插件已加载（20 thirdparty + 3 official）
- AI provider: deepseek（已配置）

### 9.2 测试用例

#### TC-A：单本积压书吞吐（Phase A 验证）

1. 订阅一本 1000+ 章的真实小说
2. 观察第一轮处理：25 章并行，耗时应 < 15 秒
3. 观察 recheck：5 秒后开始下一轮
4. 确认无 `database is locked` 错误
5. 确认章节文件正确写入 `backend/data/library/`

#### TC-B：多本积压书并行（Phase B 验证）

1. 同时订阅 3 本 1000+ 章的真实小说
2. 观察日志：3 本书 `_process_book` 交错
3. 确认各书 lease 独立
4. 确认总吞吐 ≈ 单本 × 3

#### TC-C：混合场景追更优先（Phase C 验证）

1. 先订阅 3 本积压书（各 500+ 章）
2. 在积压处理过程中，订阅 2 本追更书（各 < 10 章）
3. 确认追更书在下一轮调度中优先处理
4. 确认追更书响应延迟 < 30 秒

#### TC-D：连续追赶 + 批量刷新（Phase D 验证）

1. 订阅一本 500+ 章小说
2. 观察 recheck 间隔 = 5 秒
3. 观察日志：`_refresh_shared_book_state` 仅在批次结束调用
4. 确认任务超过 10 分钟时正常 yield 并重新调度

#### TC-E：回归测试

1. 运行 `pytest ../dev-assets/tests/test_aggregate_processor_state_machine.py`
2. 运行 `pytest ../dev-assets/tests/test_stage1_bootstrap_and_update.py`
3. 确认现有测试全部通过

### 9.3 监控指标

测试时观察以下指标（从日志或 `aggregate_operation_logs` 表提取）：

- 单轮章节处理耗时
- recheck 实际间隔
- `database is locked` 错误次数
- 每秒处理章节数（chapters/sec）
- 书状态刷新频率
- lease 获取/释放成功率

---

## 10. 风险与缓解

### 10.1 SQLite WAL 限制

**风险**：WAL 模式下写入仍是串行的（单写多读），高并发写仍可能排队。

**缓解**：`busy_timeout=5000` 提供排队缓冲；`MAX_BOOK_TASK_SECONDS=600` 防止单任务长时间占锁。实测如果排队严重，降低 `CHAPTER_PARALLELISM_LIMIT` 到 4-5。

### 10.2 源反爬触发

**风险**：章节并行导致同一书源短时间大量请求，触发 IP 封禁或验证码。

**缓解**：`PER_SOURCE_CONCURRENCY=2` 限制同一书源并发；如仍触发，降至 1。

### 10.3 AI rate limit

**风险**：并行章节同时请求 AI，超出 provider rate limit。

**缓解**：`_ai_sem = Semaphore(aiMaxConcurrency=2)` 限制 AI 并发。

### 10.4 内存占用

**风险**：多本书 × 多章节并行，内存占用上升。

**缓解**：`BOOK_PARALLELISM_LIMIT=3` × `CHAPTER_PARALLELISM_LIMIT=8` = 24 个并发章节，每章内容通常 < 100KB，总内存 < 2.4MB，可接受。

### 10.5 错误传播

**风险**：`asyncio.gather(return_exceptions=True)` 中单个章节失败被吞掉。

**缓解**：`_wrap_chapter_error` 将异常转为错误结果，写入 `aggregate_chapter_tasks` 的 `last_error_code` + `retry_count`，由现有重试机制处理。

### 10.6 回滚

每个 Phase 独立，可单独回滚：
- Phase A 回滚：恢复串行 for 循环，WAL 可保留（WAL 对串行无副作用）
- Phase B 回滚：恢复串行书籍遍历
- Phase C 回滚：恢复单队列 `list_due_books`
- Phase D 回滚：恢复 1min recheck + 每章状态刷新

---

## 11. 实施顺序

```
Phase A (WAL + 章节并行)
  ├── A1: db.py + aggregate_processor.py 启用 WAL
  ├── A2: run_book_task 章节并行
  ├── A3: per-source 信号量
  ├── A4: AI 信号量
  └── 验证 TC-A + TC-E

Phase B (书籍并行)
  ├── B1: run_periodic_once 书籍并行
  ├── B2: lease 并行安全确认
  └── 验证 TC-B + TC-E

Phase C (双车道调度)
  ├── C1: list_due_books_split
  ├── C2: 调度器双车道处理
  └── 验证 TC-C + TC-E

Phase D (连续追赶 + 批量刷新)
  ├── D1: recheck 5s
  ├── D2: 任务超时保护
  ├── D3: 批量状态刷新
  └── 验证 TC-D + TC-E
```

每个 Phase 完成后用真实书籍测试，确认无回归再进入下一 Phase。

---

## 12. 预期总效果

| 场景 | 当前 | 优化后 | 提升 |
|------|------|--------|------|
| 单本 5000 章积压 | 7.5 小时 | 50 分钟 | 9x |
| 10 本 5000 章积压 | 75 小时 | 1.5 小时 | 50x |
| 20 本追更（1-3 章） | 6+ 分钟响应 | < 30 秒响应 | 12x |
| 混合场景（10 积压 + 20 追更） | 追更被阻塞 | 追更无感知 | — |
